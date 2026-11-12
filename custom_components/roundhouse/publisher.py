"""Retained-topic publisher for one device.

Publishes through Home Assistant's MQTT integration, tracks the retained topics
it owns, and clears the ones it no longer owns.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.components import mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

# A send that failed (the broker is away) is tried again this often.
RETRY_SECONDS = 5.0

# Topics Roundhouse publishes; the device owns every other topic under it.
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
        # What each owned topic should hold. It is recorded before the send, so
        # a failed send never leaves an older value to be republished later.
        self._published: dict[str, bytes] = {}
        self._unsent: set[str] = set()  # owned topics whose last send failed
        self._unsent_clear: set[str] = set()  # topics whose clearing failed
        self._retry: CALLBACK_TYPE | None = None
        self._closed = False

    @property
    def owned(self) -> frozenset[str]:
        """The subtopics currently held retained."""
        return frozenset(self._published)

    @property
    def pending_clears(self) -> frozenset[str]:
        """The subtopics whose clearing failed and is still to be retried."""
        return frozenset(self._unsent_clear)

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
        """Publish a retained payload unless it is unchanged; return True if sent.

        A failed send is not an error: the payload stays the desired value of the
        topic, and it is sent again on a timer and after a reconnect. A stopped
        publisher sends nothing.
        """
        if self._closed:
            return False
        if len(payload) > self.max_payload:
            raise PayloadTooLargeError(
                f"{self._prefix}{subtopic}: {len(payload)} > {self.max_payload}"
            )
        if self._published.get(subtopic) == payload and subtopic not in self._unsent:
            return False
        self._published[subtopic] = payload
        self._unsent_clear.discard(subtopic)
        return await self._try_send(subtopic, payload)

    async def _try_send(self, subtopic: str, payload: bytes) -> bool:
        if self._closed:
            return False
        try:
            await self._send(subtopic, payload)
        except (HomeAssistantError, TimeoutError) as err:
            if self._closed:  # stopped while the send was in flight
                return False
            _LOGGER.warning(
                "Not sent, will retry: %s%s (%s)",
                self._prefix,
                subtopic,
                err or type(err).__name__,
            )
            self._unsent.add(subtopic)
            self._arm_retry()
            return False
        self._unsent.discard(subtopic)
        return True

    def _arm_retry(self) -> None:
        if self._retry is None and not self._closed:
            self._retry = async_call_later(self._hass, RETRY_SECONDS, self._on_retry)

    async def _on_retry(self, _now: datetime) -> None:
        self._retry = None
        await self._flush()

    async def _flush(self) -> None:
        """Send again what failed."""
        for subtopic in sorted(self._unsent):
            if subtopic in self._published:
                await self._try_send(subtopic, self._published[subtopic])
            else:
                self._unsent.discard(subtopic)
        for subtopic in sorted(self._unsent_clear):
            await self._try_clear(subtopic)

    @callback
    def async_stop(self) -> None:
        """Stop sending for good and cancel the retry timer."""
        self._closed = True
        if self._retry is not None:
            self._retry()
            self._retry = None

    async def async_send_transient(self, subtopic: str, payload: bytes) -> None:
        """Send a message that is neither retained nor tracked, at QoS 1."""
        if len(payload) > self.max_payload:
            raise PayloadTooLargeError(
                f"{self._prefix}{subtopic}: {len(payload)} > {self.max_payload}"
            )
        await mqtt.async_publish(
            self._hass,
            self._prefix + subtopic,
            payload,
            qos=1,
            retain=False,
            encoding=None,
        )

    async def async_clear(self, subtopic: str) -> None:
        """Clear one retained topic."""
        if self._published.pop(subtopic, None) is not None:
            self._unsent.discard(subtopic)
            await self._try_clear(subtopic)

    async def _try_clear(self, subtopic: str) -> None:
        if self._closed:
            return
        try:
            await self._send(subtopic, b"")
        except (HomeAssistantError, TimeoutError) as err:
            if self._closed:
                return
            _LOGGER.warning(
                "Not cleared, will retry: %s%s (%s)",
                self._prefix,
                subtopic,
                err or type(err).__name__,
            )
            self._unsent_clear.add(subtopic)
            self._arm_retry()
            return
        self._unsent_clear.discard(subtopic)

    async def async_clear_all_except(self, keep: frozenset[str]) -> None:
        """Clear every owned topic that is not in `keep`."""
        for subtopic in self.owned - keep:
            await self.async_clear(subtopic)

    async def async_resync(self) -> None:
        """Publish every held payload again, for example after a reconnect."""
        for subtopic, payload in list(self._published.items()):
            await self._try_send(subtopic, payload)
        for subtopic in sorted(self._unsent_clear):
            await self._try_clear(subtopic)

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
            await self._try_clear(subtopic)
        return stale
