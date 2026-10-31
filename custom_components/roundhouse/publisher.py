"""Retained-topic publisher for one device.

Publishes through Home Assistant's MQTT integration, tracks the retained topics
it owns, and clears the ones it no longer owns.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

# Topics Roundhouse publishes; the device owns every other topic under its prefix.
_OWNED_PREFIXES = ("meta", "views", "state/", "icon/", "alert/")


class PayloadTooLargeError(ValueError):
    """A payload exceeds the device's `max_payload`."""


def _is_ours(subtopic: str) -> bool:
    return any(
        subtopic == p or (p.endswith("/") and subtopic.startswith(p))
        for p in _OWNED_PREFIXES
    )


class Publisher:
    """Publish and track the retained topics of one device."""

    def __init__(self, hass: HomeAssistant, device_id: str, max_payload: int) -> None:
        """Initialize the publisher."""
        self._hass = hass
        self._prefix = f"roundhouse/{device_id}/"
        self.max_payload = max_payload
        self._published: dict[str, bytes] = {}

    @property
    def owned(self) -> frozenset[str]:
        """The subtopics currently held retained."""
        return frozenset(self._published)

    async def _send(self, subtopic: str, payload: bytes) -> None:
        await mqtt.async_publish(
            self._hass,
            self._prefix + subtopic,
            payload,
            qos=1,
            retain=True,
            encoding=None,
        )

    async def async_publish(self, subtopic: str, payload: bytes) -> bool:
        """Publish a retained payload unless it is unchanged; return True if sent."""
        if len(payload) > self.max_payload:
            raise PayloadTooLargeError(
                f"{self._prefix}{subtopic}: {len(payload)} > {self.max_payload}"
            )
        if self._published.get(subtopic) == payload:
            return False
        await self._send(subtopic, payload)
        self._published[subtopic] = payload
        return True

    async def async_clear(self, subtopic: str) -> None:
        """Clear one retained topic."""
        if self._published.pop(subtopic, None) is not None:
            await self._send(subtopic, b"")

    async def async_clear_all_except(self, keep: frozenset[str]) -> None:
        """Clear every owned topic that is not in `keep`."""
        for subtopic in self.owned - keep:
            await self.async_clear(subtopic)

    async def async_resync(self) -> None:
        """Publish every held payload again, for example after a reconnect."""
        for subtopic, payload in list(self._published.items()):
            await self._send(subtopic, payload)

    async def async_clear_stale(self, settle: float) -> list[str]:
        """Clear retained topics under the prefix that this publisher does not own.

        Collects retained messages for `settle` seconds. Returns the cleared
        subtopics.
        """
        seen: set[str] = set()

        @callback
        def collect(msg: mqtt.ReceiveMessage) -> None:
            if msg.retain and msg.payload:
                seen.add(msg.topic.removeprefix(self._prefix))

        unsubscribe = await mqtt.async_subscribe(
            self._hass, self._prefix + "#", collect, qos=1, encoding=None
        )
        done: asyncio.Future[None] = self._hass.loop.create_future()

        @callback
        def finish(_now: datetime) -> None:
            if not done.done():
                done.set_result(None)

        cancel = async_call_later(self._hass, settle, finish)
        try:
            await done
        finally:
            cancel()
            unsubscribe()
        stale = sorted(s for s in seen if _is_ours(s) and s not in self._published)
        for subtopic in stale:
            _LOGGER.debug("Clearing stale retained topic %s%s", self._prefix, subtopic)
            await self._send(subtopic, b"")
        return stale
