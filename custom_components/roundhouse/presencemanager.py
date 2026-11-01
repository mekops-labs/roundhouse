"""Presence of one device in Home Assistant: the timer and the stored time."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_PRESENCE_GRACE_HOURS,
    OPT_PRESENCE_GRACE_HOURS,
    presence_signal,
)
from .presence import Presence

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


def _now() -> float:
    return dt_util.utcnow().timestamp()


class PresenceManager:
    """Own the presence state machine, its timer, and its persistence."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._device = device
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"roundhouse.{device.device_id}.presence"
        )
        hours = device.entry.options.get(
            OPT_PRESENCE_GRACE_HOURS, DEFAULT_PRESENCE_GRACE_HOURS
        )
        self._presence = Presence(hours * 3600)
        self._timer: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Restore the offline time."""
        stored = await self._store.async_load()
        since = (stored or {}).get("offline_since")
        if isinstance(since, int | float):
            self._presence.offline_since = float(since)

    @callback
    def async_stop(self) -> None:
        """Cancel the timer."""
        if self._timer:
            self._timer()
            self._timer = None

    @property
    def state(self) -> str | None:
        """Return `home`, `not_home`, or None while unknown."""
        return self._presence.state(_now())

    @property
    def offline_since(self) -> float | None:
        """Return when the device went offline, if it is."""
        return self._presence.offline_since

    async def async_on_availability(self, value: str) -> None:
        """Apply an availability message."""
        changed = self._presence.on_availability(value, _now())
        self._arm_timer()
        if changed:
            await self._store.async_save(
                {"offline_since": self._presence.offline_since}
            )
        # Always tell the entity: the first message turns unknown into a state.
        self._notify()

    def _notify(self) -> None:
        async_dispatcher_send(self._hass, presence_signal(self._device.device_id))

    def _arm_timer(self) -> None:
        self.async_stop()
        left = self._presence.seconds_left(_now())
        if left is None or left <= 0:
            return
        when = dt_util.utcnow().timestamp() + left
        self._timer = async_track_point_in_utc_time(
            self._hass, self._on_expiry, dt_util.utc_from_timestamp(when)
        )

    @callback
    def _on_expiry(self, _now_time: datetime) -> None:
        self._timer = None
        _LOGGER.debug("Presence grace of %s ran out", self._device.device_id)
        self._notify()
