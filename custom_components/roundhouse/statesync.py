"""Publish entity states and icons for the tiles on a device."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from . import codec, icons, rendering
from .publisher import PayloadTooLargeError

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)


class StateSync:
    """Keep the `state/` and `icon/` topics of a device current."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the sync."""
        self._hass = hass
        self._device = device
        self._translator = rendering.Translator(hass)
        self._entities: frozenset[str] = frozenset()
        self._card_icons: dict[str, str] = {}
        self._entity_icon: dict[str, str] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def translator(self) -> rendering.Translator:
        """Return the translator, shared with the preview."""
        return self._translator

    @callback
    def async_stop(self) -> None:
        """Stop tracking and cancel the publishes in progress."""
        self._drop_listeners()
        for task in list(self._tasks):
            task.cancel()

    def _drop_listeners(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    async def async_sync(
        self, entities: frozenset[str], card_icons: dict[str, str] | None = None
    ) -> None:
        """Track `entities`, publish their states, and clear the rest."""
        async with self._lock:
            self._drop_listeners()
            self._entities = entities
            self._card_icons = card_icons or {}
            if entities:
                await self._hass.async_add_executor_job(icons.warm)
                domains, platforms = rendering.entity_domains(self._hass, set(entities))
                await self._translator.async_load(domains, platforms)
                self._unsubs.append(
                    async_track_state_change_event(
                        self._hass, list(entities), self._on_state
                    )
                )
                self._unsubs.append(
                    self._hass.bus.async_listen(
                        er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry
                    )
                )
            for entity_id in sorted(entities):
                await self._publish(entity_id)
            await self._clear_unused()

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        self._spawn(event.data["entity_id"])

    @callback
    def _on_registry(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id in self._entities:
            self._spawn(entity_id)

    @callback
    def _spawn(self, entity_id: str) -> None:
        task = self._hass.async_create_task(self._publish_locked(entity_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publish_locked(self, entity_id: str) -> None:
        async with self._lock:
            if entity_id in self._entities:
                await self._publish(entity_id)
                await self._clear_unused_icons()

    async def _publish(self, entity_id: str) -> None:
        profile = self._device.profile
        if profile is None or self._device.error is not None:
            return
        try:
            message = rendering.render_state(
                self._hass, self._translator, entity_id, self._card_icons.get(entity_id)
            )
            self._entity_icon[entity_id] = await self._ensure_icon(
                message["icon"], profile["icon_px"]
            )
            await self._device.publisher.async_publish(
                f"state/{entity_id}", codec.encode(message)
            )
        except PayloadTooLargeError as err:
            _LOGGER.error("State not published: %s", err)
        except Exception:
            _LOGGER.exception("Rendering %s failed", entity_id)

    async def _ensure_icon(self, name: str, size: int) -> str:
        """Publish the icon mask once and return its subtopic."""
        topic = f"icon/{codec.icon_topic_name(name)}"
        if topic in self._device.publisher.owned:
            return topic
        try:
            payload = await rendering.async_icon_payload(self._hass, name, size)
            await self._device.publisher.async_publish(topic, payload)
        except Exception:
            _LOGGER.exception("Icon %s failed", name)
        return topic

    async def _clear_unused(self) -> None:
        publisher = self._device.publisher
        for topic in sorted(publisher.owned):
            if topic.startswith("state/") and topic[6:] not in self._entities:
                await publisher.async_clear(topic)
        self._entity_icon = {
            e: t for e, t in self._entity_icon.items() if e in self._entities
        }
        await self._clear_unused_icons()

    async def _clear_unused_icons(self) -> None:
        publisher = self._device.publisher
        in_use = set(self._entity_icon.values())
        for topic in sorted(publisher.owned):
            if topic.startswith("icon/") and topic not in in_use:
                await publisher.async_clear(topic)
