"""Clear what a removed device leaves behind, retrying its retained topics."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from . import issues
from .const import STALE_SETTLE_SECONDS, store_key
from .publisher import Publisher

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
_DATA = "roundhouse_purges"

# A clear that failed, or ran while the broker was away, is retried this often.
RETRY_SECONDS = 60.0


async def async_purge(hass: HomeAssistant, device_id: str) -> None:
    """Clear what a removed device leaves: retained topics, stores, and issues."""
    if not await _async_clear_topics(hass, device_id):
        _LOGGER.warning("Retained topics of %s not cleared, will retry", device_id)
        _pending(hass).schedule(device_id)
    alerts: Store[dict[str, Any]] = Store(
        hass, STORE_VERSION, store_key(device_id, "alerts")
    )
    names = [
        f"alert_{a['id']}"
        for a in ((await alerts.async_load()) or {}).get("alerts", [])
    ]
    for name in [*names, "alerts", "views", "presence"]:
        store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, store_key(device_id, name)
        )
        await store.async_remove()
    issues.clear_device_issues(hass, device_id)


@callback
def async_cancel(hass: HomeAssistant, device_id: str) -> None:
    """Stop clearing the topics of a device that is set up again."""
    pending: _Pending | None = hass.data.get(_DATA)
    if pending is not None:
        pending.cancel(device_id)


async def _async_clear_topics(hass: HomeAssistant, device_id: str) -> bool:
    """Clear the device's retained topics once; return True when none is left.

    A broker that is away delivers no retained message, so the run fails.
    """
    if not mqtt.is_connected(hass):
        return False
    publisher = Publisher(hass, device_id, 0)  # a clear has an empty payload
    try:
        await publisher.async_clear_stale(STALE_SETTLE_SECONDS)
    except HomeAssistantError as err:
        _LOGGER.debug("Retained topics of %s not cleared: %s", device_id, err)
        return False
    finally:
        publisher.async_stop()  # the purge retries the whole run, not the publisher
    return not publisher.pending_clears and mqtt.is_connected(hass)


def _pending(hass: HomeAssistant) -> _Pending:
    pending: _Pending | None = hass.data.get(_DATA)
    if pending is None:
        pending = hass.data[_DATA] = _Pending(hass)
    return pending


class _Pending:
    """The removed devices whose retained topics are still to be cleared."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_stop)

    @callback
    def schedule(self, device_id: str) -> None:
        @callback
        def fire(_now: datetime) -> None:
            self._timers.pop(device_id, None)
            self._tasks[device_id] = self._hass.async_create_background_task(
                self._run(device_id), f"roundhouse purge {device_id}"
            )

        self._timers[device_id] = async_call_later(self._hass, RETRY_SECONDS, fire)

    async def _run(self, device_id: str) -> None:
        try:
            if await _async_clear_topics(self._hass, device_id):
                _LOGGER.info("Retained topics of %s cleared", device_id)
            else:
                self.schedule(device_id)
        finally:
            self._tasks.pop(device_id, None)

    @callback
    def cancel(self, device_id: str) -> None:
        if (timer := self._timers.pop(device_id, None)) is not None:
            timer()
        if (task := self._tasks.pop(device_id, None)) is not None:
            task.cancel()

    @callback
    def _on_stop(self, _event: Event) -> None:
        for device_id in [*self._timers, *self._tasks]:
            self.cancel(device_id)
