"""Keep the published view definition in step with the dashboard."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from . import digest, issues, layout, lovelace_io
from .const import CONF_SLUG, OPT_SNAPSHOT_VIEW
from .debounce import Debounce

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


class ViewSync:
    """Digest the device's dashboard and hand the result to the device."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the sync."""
        self._hass = hass
        self._device = device
        self._slug: str = device.entry.data[CONF_SLUG]
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"roundhouse.{device.device_id}.views"
        )
        self._last_good: dict[str, dict[str, Any]] = {}
        self._overflowing: set[str] = set()
        self._entities: frozenset[str] = frozenset()
        self._lock = asyncio.Lock()
        self._debounce = Debounce(hass, lovelace_io.UPDATE_WAIT, self.async_refresh)
        self._unsubs: list[CALLBACK_TYPE] = []
        self.last_digest: digest.DigestResult | None = None
        self.last_overflows: list[layout.Overflow] = []
        # `config`, `strategy`, or `missing`; None before the first digest.
        self.dashboard_state: str | None = None

    async def async_start(self) -> None:
        """Load the stored definitions, publish, and watch for changes."""
        stored = await self._store.async_load()
        profile = self._device.profile
        if (
            stored
            and profile
            and stored.get("fingerprint") == layout.profile_fingerprint(profile)
        ):
            self._last_good = {v["path"]: v for v in stored["views"]}
        self._unsubs.append(
            lovelace_io.async_watch(self._hass, self._slug, self._debounce)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_update
            )
        )
        await self.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Stop watching."""
        self._debounce.cancel()
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _on_registry_update(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        ids = {event.data.get("entity_id"), event.data.get("old_entity_id")}
        if ids & self._entities:
            self._debounce.trigger()

    def _friendly_name(self, entity_id: str) -> str | None:
        state = self._hass.states.get(entity_id)
        return state.name if state else None

    async def async_refresh(self) -> None:
        """Digest the dashboard again and publish what changed."""
        async with self._lock:
            device = self._device
            if device.profile is None:
                return
            try:
                await self._refresh(device.profile)
            except Exception:
                _LOGGER.exception("Digest of %s failed", self._slug)
            await device.async_publish_all()

    async def _refresh(self, profile: dict[str, Any]) -> None:
        device = self._device
        state = await lovelace_io.async_load_dashboard(self._hass, self._slug)
        issues.clear_dashboard_issues(self._hass, device.device_id)
        self.dashboard_state = state.kind
        if state.config is not None and digest.is_strategy(state.config):
            self.dashboard_state = "strategy"
        if (
            state.kind != "config"
            or state.config is None
            or digest.is_strategy(state.config)
        ):
            kind = "deleted" if state.kind == "missing" else "strategy"
            issues.raise_dashboard_issue(self._hass, device.device_id, kind)
            self._reset()
            device.set_views(dict(layout.EMPTY_VIEWS), {}, {})
            return

        result = digest.digest(state.config, self._friendly_name)
        published, overflows = layout.merge(result.views, self._last_good, profile)
        self._last_good = {v["path"]: v for v in published}
        self._sync_overflow_issues(overflows, profile)
        self.last_digest, self.last_overflows = result, overflows
        self._entities = frozenset(t.entity_id for v in result.views for t in v.tiles)
        option = device.entry.options.get(OPT_SNAPSHOT_VIEW, "")
        card_icons = {
            t.entity_id: t.icon for v in result.views for t in v.tiles if t.icon
        }
        device.set_views(
            {
                "views": published,
                "snapshot_view": layout.snapshot_view(published, profile, option),
                "skipped": result.skipped_total,
            },
            card_icons,
            result.skipped,
        )
        await self._store.async_save(
            {
                "fingerprint": layout.profile_fingerprint(profile),
                "views": published,
            }
        )

    def _reset(self) -> None:
        for path in self._overflowing:
            issues.clear_overflow(self._hass, self._device.device_id, path)
        self._overflowing.clear()
        self._last_good = {}
        self._entities = frozenset()
        self.last_digest, self.last_overflows = None, []

    def _sync_overflow_issues(
        self, overflows: list[layout.Overflow], profile: dict[str, Any]
    ) -> None:
        now = {o.path for o in overflows}
        for path in self._overflowing - now:
            issues.clear_overflow(self._hass, self._device.device_id, path)
        for o in overflows:
            issues.raise_overflow(
                self._hass,
                self._device.device_id,
                o.path,
                o.title,
                o.excess,
                o.capacity,
            )
        self._overflowing = now
