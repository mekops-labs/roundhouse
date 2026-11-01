"""The Home Assistant device of a panel."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo

from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_PROFILE, DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Describe the device of a config entry, from its announced profile."""
    device_id: str = entry.data[CONF_DEVICE_ID]
    model: str = entry.data[CONF_MODEL]
    profile = entry.data.get(CONF_PROFILE) or {}
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=f"{model.capitalize()} {device_id}",
        model=model,
        sw_version=profile.get("fw"),
    )


def find_device(hass: HomeAssistant, entry: ConfigEntry) -> DeviceEntry | None:
    """Return the registry entry of the panel of a config entry.

    Home Assistant deprecated `async_get_device` for the identifier lookup in
    favor of `async_get_device_by_identifier`; the previous release only has the
    old one.
    """
    registry = dr.async_get(hass)
    identifier = (DOMAIN, entry.data[CONF_DEVICE_ID])
    lookup = getattr(registry, "async_get_device_by_identifier", None)
    if lookup is not None:
        found: DeviceEntry | None = lookup(identifier, entry.entry_id)
        return found
    return registry.async_get_device(identifiers={identifier})
