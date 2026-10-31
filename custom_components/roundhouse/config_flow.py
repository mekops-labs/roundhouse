"""Config flow for Roundhouse."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class RoundhouseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Roundhouse config flow."""

    VERSION = 1
