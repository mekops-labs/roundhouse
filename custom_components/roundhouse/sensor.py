"""Sensors of a panel: battery, power mode, contract version, unread alerts."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, alerts_signal, status_signal
from .device import Device
from .entity import RoundhouseEntity


def _remove_skipped_cards(hass: HomeAssistant, device_id: str) -> None:
    """Remove the skipped-cards sensor that an earlier version added."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{device_id}_skipped_cards"
    )
    if entity_id:
        registry.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors the device supports."""
    device: Device = hass.data[DOMAIN][entry.entry_id]
    _remove_skipped_cards(hass, device.device_id)
    entities: list[RoundhouseEntity] = [
        ContractVersion(entry, device),
        UnreadAlerts(entry, device),
    ]
    if "sleep" in (device.profile or {}).get("features", []):
        entities.append(PowerMode(entry, device))
    async_add_entities(entities)

    added = False

    @callback
    def add_battery() -> None:
        nonlocal added
        if not added and device.status and device.status.get("battery") is not None:
            added = True
            async_add_entities([Battery(entry, device)])

    add_battery()
    if not added:
        entry.async_on_unload(
            async_dispatcher_connect(hass, status_signal(device.device_id), add_battery)
        )


class ContractVersion(RoundhouseEntity, SensorEntity):
    """The contract version the device announced."""

    _attr_translation_key = "contract_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the sensor."""
        super().__init__(entry, device, "contract_version")

    @property
    def native_value(self) -> str | None:
        """Return the announced version."""
        value = (self._device.profile or {}).get("contract")
        return str(value) if value else None


class UnreadAlerts(RoundhouseEntity, SensorEntity):
    """The alerts nobody has acknowledged."""

    _attr_translation_key = "unread_alerts"

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the sensor."""
        super().__init__(
            entry, device, "unread_alerts", alerts_signal(device.device_id)
        )

    @property
    def native_value(self) -> int:
        """Return the unread count."""
        return self._device.alerts.unread


class PowerMode(RoundhouseEntity, SensorEntity):
    """The power mode the device reports."""

    _attr_translation_key = "power_mode"

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the sensor."""
        super().__init__(entry, device, "power_mode", status_signal(device.device_id))

    @property
    def native_value(self) -> str | None:
        """Return the reported mode."""
        mode = (self._device.status or {}).get("power_mode")
        return str(mode) if mode else None


class Battery(RoundhouseEntity, SensorEntity):
    """The battery level the device reports."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, entry: ConfigEntry, device: Device) -> None:
        """Initialize the sensor."""
        super().__init__(entry, device, "battery", status_signal(device.device_id))

    @property
    def native_value(self) -> int | None:
        """Return the level."""
        level = (self._device.status or {}).get("battery")
        return int(level) if level is not None else None
