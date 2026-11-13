"""Roundhouse: an editor and MQTT bridge for panel devices."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from . import editor, services
from .const import CONF_DEVICE_ID, DOMAIN
from .device import Device
from .deviceinfo import device_info
from .panelreg import async_register_panel
from .purge import async_cancel, async_purge

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["binary_sensor", "device_tracker", "notify", "sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""
    services.async_register(hass)
    editor.async_register_commands(hass)
    await async_register_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Roundhouse device entry."""
    async_cancel(hass, entry.data[CONF_DEVICE_ID])  # a removed device added again
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
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **device_info(entry)
    )
    await device.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Roundhouse device entry."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear the retained topics, stores, and issues of a removed device."""
    await async_purge(hass, entry.data[CONF_DEVICE_ID])
