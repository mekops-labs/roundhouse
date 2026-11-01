"""One notify entity per device: a message becomes an `event` alert."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import Device
from .deviceinfo import device_info

try:  # the feature class moved to `const` in a later Home Assistant release
    from homeassistant.components.notify.const import NotifyEntityFeature
except ImportError:
    from homeassistant.components.notify import (  # type: ignore[attr-defined]
        NotifyEntityFeature,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the notify entity of a device."""
    device: Device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RoundhouseNotify(entry, device)])


class RoundhouseNotify(NotifyEntity):
    """Send a plain message to the panel as an `event` alert."""

    _attr_has_entity_name = True
    _attr_name = "Alert"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the entity."""
        self._device = device
        self._attr_unique_id = f"{device.device_id}_notify"
        self._attr_device_info: DeviceInfo = device_info(entry)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Turn a notify message into an alert."""
        await self._device.alerts.async_add(
            title=title or str(self._attr_device_info.get("name", "Roundhouse")),
            message=message,
            severity="event",
        )
