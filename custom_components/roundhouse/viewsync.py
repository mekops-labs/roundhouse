"""Own a device's views: store them, check saves, and publish the definition."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from . import codec, icons, issues, layout, viewrules
from .const import store_key
from .debounce import Debounce

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 2

# Wait for further registry changes before publishing a renamed entity again.
NAME_WAIT = 2.0

STARTER_TITLE = "Home"


class _ViewStore(Store[dict[str, Any]]):
    """The views of one device; the first store version held a digest."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Drop the digest of the first version: views are authored now."""
        return {}


@dataclass
class SaveResult:
    """The outcome of a save: the new state, a conflict, or the broken rules."""

    revision: int
    views: list[dict[str, Any]] = field(default_factory=list)
    conflict: bool = False
    errors: list[viewrules.RuleError] = field(default_factory=list)
    # The runtime stopped (the entry reloads); the caller retries on the new one.
    stopped: bool = False

    @property
    def ok(self) -> bool:
        """Return whether the save was stored."""
        return not self.conflict and not self.errors and not self.stopped


def _tile(raw: Any) -> Any:
    """Keep the fields of a tile that Roundhouse stores; leave the rest to checks."""
    if not isinstance(raw, Mapping):
        return raw
    tile = {k: raw[k] for k in ("entity_id", "name", "icon", "controls") if k in raw}
    return {k: v for k, v in tile.items() if v is not None and v != ""}


def _view(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stored shape of a view, with a path for a new one."""
    tiles = raw.get("tiles")
    path = raw.get("path")
    return {
        "path": uuid.uuid4().hex[:8] if path is None else path,
        "title": raw.get("title"),
        "layout": raw.get("layout"),
        "tiles": [_tile(t) for t in tiles] if isinstance(tiles, list) else tiles,
    }


class ViewSync:
    """Store the device's views and keep the published definition in step."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the sync."""
        self._hass = hass
        self._device = device
        self._store: Store[dict[str, Any]] = _ViewStore(
            hass, STORE_VERSION, store_key(device.device_id, "views")
        )
        self._overflowing: set[str] = set()
        self._entities: frozenset[str] = frozenset()
        self._lock = asyncio.Lock()
        self._debounce = Debounce(hass, NAME_WAIT, self.async_refresh)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._stopped = False
        self.revision = 0
        self.views: list[dict[str, Any]] = []
        self.snapshot: str | None = None
        self.overflows: list[layout.Overflow] = []

    async def async_start(self) -> None:
        """Load the stored views, publish, and follow entity renames."""
        data = await self._store.async_load() or {}
        profile = self._device.profile
        if "views" in data:
            self.revision = int(data["revision"])
            self.views = list(data["views"])
            self.snapshot = data.get("snapshot")
        elif profile:
            self.revision = 1
            self.views = [self._starter(profile)]
            await self._save()
        self._unsubs.append(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_update
            )
        )
        await self.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Stop watching and cancel a refresh in progress."""
        self._stopped = True
        self._debounce.async_stop()
        while self._unsubs:
            self._unsubs.pop()()

    @staticmethod
    def _starter(profile: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "path": uuid.uuid4().hex[:8],
            "title": STARTER_TITLE,
            "layout": layout.densest(profile),
            "tiles": [],
        }

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "revision": self.revision,
                "views": self.views,
                "snapshot": self.snapshot,
            }
        )

    def _friendly_name(self, entity_id: str) -> str | None:
        state = self._hass.states.get(entity_id)
        return state.name if state else None

    async def async_refresh(self) -> None:
        """Publish the stored views again, for a changed profile or name."""
        async with self._lock:
            await self._publish()

    def _definition(
        self,
        views: list[dict[str, Any]],
        snapshot: str | None,
        profile: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[layout.Overflow]]:
        """Return the `views` payload of these views and the views left out."""
        published, overflows = layout.fit(views, profile, self._friendly_name)
        payload = {
            "views": published,
            "snapshot_view": layout.snapshot_view(published, profile, snapshot),
            "skipped": 0,
        }
        return payload, overflows

    async def _publish(self) -> None:
        device = self._device
        profile = device.profile
        if self._stopped or profile is None:
            return
        payload, self.overflows = self._definition(self.views, self.snapshot, profile)
        self._sync_overflow_issues()
        self._entities = frozenset(
            t["entity_id"] for v in self.views for t in v["tiles"]
        )
        overrides = viewrules.icon_overrides(self.views)
        device.set_views(payload, {e: i for e, i in overrides.items() if i})
        await device.async_publish_all()

    def _size_error(
        self,
        views: list[dict[str, Any]],
        snapshot: str | None,
        profile: Mapping[str, Any],
    ) -> viewrules.RuleError | None:
        """Return an error when the definition exceeds the device's payload limit."""
        payload, _ = self._definition(views, snapshot, profile)
        size = len(codec.encode(payload))
        limit = self._device.publisher.max_payload
        if size <= limit:
            return None
        return viewrules.RuleError(
            "too_large",
            f"The views take {size} bytes and the device accepts at most {limit}; "
            "remove tiles or views",
        )

    async def async_save(
        self,
        revision: int,
        views: Sequence[Mapping[str, Any]],
        snapshot: str | None,
    ) -> SaveResult:
        """Check the views and, when every rule holds, store and publish them."""
        profile = self._device.profile
        if profile is None:
            raise ValueError("The device has no profile yet")
        await self._hass.async_add_executor_job(icons.warm)
        async with self._lock:
            if self._stopped:
                return SaveResult(self.revision, stopped=True)
            if revision != self.revision:
                return SaveResult(self.revision, conflict=True)
            candidate = [_view(v) for v in views]
            errors = viewrules.validate(
                candidate, snapshot, profile, icon_known=icons.known
            )
            if not errors:
                too_large = self._size_error(candidate, snapshot, profile)
                errors = [too_large] if too_large else []
            if errors:
                return SaveResult(self.revision, errors=errors)
            self.revision += 1
            self.views, self.snapshot = candidate, snapshot
            await self._save()
            await self._publish()
            return SaveResult(self.revision, views=self.views)

    @callback
    def _on_registry_update(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        old = event.data.get("old_entity_id")
        new = event.data["entity_id"]
        if old and old != new and old in self._entities:
            self._device.entry.async_create_background_task(
                self._hass,
                self._async_rename(old, new),
                f"roundhouse rename {self._device.device_id}",
            )
        elif new in self._entities:
            self._debounce.trigger()

    async def _async_rename(self, old: str, new: str) -> None:
        """Follow an entity whose ID changed: its tiles take the new ID."""
        async with self._lock:
            if self._stopped:
                return
            changed = False
            for view in self.views:
                for tile in view["tiles"]:
                    if tile["entity_id"] == old:
                        tile["entity_id"] = new
                        changed = True
            if not changed:
                return  # a save removed the tiles while this waited for the lock
            self.revision += 1
            await self._save()
            await self._publish()

    def _sync_overflow_issues(self) -> None:
        device_id = self._device.device_id
        now = {o.path for o in self.overflows}
        for path in self._overflowing - now:
            issues.clear_overflow(self._hass, device_id, path)
        for o in self.overflows:
            issues.raise_overflow(
                self._hass,
                device_id,
                o.path,
                o.title,
                o.excess,
                o.capacity,
                layout_gone=o.layout_gone,
            )
        self._overflowing = now
