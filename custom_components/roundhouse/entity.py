"""Shared base of the device's entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .device import Device
from .deviceinfo import device_info


class RoundhouseEntity(Entity):
    """An entity of a panel: named after the device, updated by signals."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: ConfigEntry, device: Device, key: str, *signals: str
    ) -> None:
        """Initialize the entity; it refreshes on each signal."""
        self._device = device
        self._signals = signals
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to the signals."""
        for signal in self._signals:
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._refresh)
            )

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()
