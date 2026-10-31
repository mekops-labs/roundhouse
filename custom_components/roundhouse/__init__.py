"""Roundhouse: Home Assistant dashboards for MQTT panel devices."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .device import Device


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Roundhouse device entry."""
    device = Device(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = device
    # Home Assistant also updates an entry for discovery keys; reload only
    # when the data or the options really change.
    snapshot = (dict(entry.data), dict(entry.options))

    async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
        if (dict(entry.data), dict(entry.options)) != snapshot:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    entry.async_on_unload(device.async_stop)
    await device.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Roundhouse device entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
