"""The presence of a panel as a device tracker."""

from __future__ import annotations

from typing import Any

# The classes moved between modules; the package re-exports them in every
# release.
from homeassistant.components.device_tracker import (  # type: ignore[attr-defined]
    SourceType,
    TrackerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, presence_signal
from .device import Device
from .entity import RoundhouseEntity

try:
    # Home Assistant 2026.10 and later: a connection tracker that does not
    # assume a MAC address, and the home for `location_name`'s replacement.
    from homeassistant.components.device_tracker import (  # type: ignore[attr-defined]
        BaseScannerEntity,
    )
except ImportError:
    BaseScannerEntity = None  # type: ignore[assignment,misc]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the presence tracker."""
    device: Device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PanelTracker(entry, device)])


def _init(self: Any, entry: ConfigEntry, device: Device) -> None:
    RoundhouseEntity.__init__(
        self, entry, device, "presence", presence_signal(device.device_id)
    )


if BaseScannerEntity is not None:

    class PanelTracker(RoundhouseEntity, BaseScannerEntity):
        """Home while the panel is online, and for the grace period after it goes."""

        _attr_name = None
        _attr_source_type = SourceType.ROUTER

        def __init__(self, entry: ConfigEntry, device: Device) -> None:
            """Initialize the tracker."""
            _init(self, entry, device)

        @property
        def is_connected(self) -> bool | None:
            """Return whether the panel counts as home; None while unknown."""
            state = self._device.presence.state
            return None if state is None else state == "home"

else:  # Home Assistant before 2026.10 only has the tracker with a location name.

    class PanelTracker(RoundhouseEntity, TrackerEntity):  # type: ignore[no-redef]
        """Home while the panel is online, and for the grace period after it goes."""

        _attr_name = None

        def __init__(self, entry: ConfigEntry, device: Device) -> None:
            """Initialize the tracker."""
            _init(self, entry, device)

        @property
        def source_type(self) -> SourceType:
            """Return the router source type: the broker session is the evidence."""
            return SourceType.ROUTER

        @property
        def location_name(self) -> str | None:
            """Return `home` or `not_home`; None keeps the state unknown."""
            return self._device.presence.state
