"""The charging state of a panel with a battery."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, status_signal
from .device import Device
from .entity import RoundhouseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the charging sensor once the device reports a charging state."""
    device: Device = hass.data[DOMAIN][entry.entry_id]
    added = False

    @callback
    def add() -> None:
        nonlocal added
        if not added and device.status and device.status.get("charging") is not None:
            added = True
            async_add_entities([Charging(entry, device)])

    add()
    if not added:
        entry.async_on_unload(
            async_dispatcher_connect(hass, status_signal(device.device_id), add)
        )


class Charging(RoundhouseEntity, BinarySensorEntity):
    """Whether the panel is charging."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the sensor."""
        super().__init__(entry, device, "charging", status_signal(device.device_id))

    @property
    def is_on(self) -> bool | None:
        """Return the charging state."""
        value = (self._device.status or {}).get("charging")
        return bool(value) if value is not None else None
