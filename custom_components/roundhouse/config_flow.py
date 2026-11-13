"""Config and options flows for Roundhouse."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from . import codec, issues
from .compat import vol
from .const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_PROFILE,
    DEFAULT_ALERT_MAX_AGE_DAYS,
    DEFAULT_ALERT_MAX_COUNT,
    DEFAULT_PRESENCE_GRACE_HOURS,
    DOMAIN,
    OPT_ALERT_MAX_AGE_DAYS,
    OPT_ALERT_MAX_COUNT,
    OPT_PRESENCE_GRACE_HOURS,
)


class RoundhouseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Roundhouse config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._device_id = ""
        self._profile: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RoundhouseOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Devices are found over MQTT; there is no manual setup."""
        return self.async_abort(reason="discovery_only")

    async def async_step_mqtt(
        self, discovery_info: MqttServiceInfo
    ) -> ConfigFlowResult:
        """Handle a device announce."""
        parsed = codec.parse_topic(discovery_info.topic)
        if parsed is None or parsed[1] != "announce":
            return self.async_abort(reason="not_roundhouse")
        self._device_id = parsed[0]
        await self.async_set_unique_id(self._device_id)
        # A configured device updates itself from its own subscription.
        self._abort_if_unique_id_configured()
        payload = discovery_info.payload
        if isinstance(payload, str):
            payload = payload.encode()
        if not payload:
            return self.async_abort(reason="no_announce")
        try:
            self._profile = codec.decode("announce", bytes(payload))
        except codec.ContractError as err:
            issues.raise_profile_issue(self.hass, self._device_id, err.code, err.detail)
            return self.async_abort(
                reason="invalid_profile",
                description_placeholders={"detail": err.detail},
            )
        self.context["title_placeholders"] = {
            "model": self._profile["model"],
            "device_id": self._device_id,
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm the device and create the entry."""
        model = self._profile["model"]
        if user_input is not None:
            return self.async_create_entry(
                title=f"{model.capitalize()} {self._device_id}",
                data={
                    CONF_DEVICE_ID: self._device_id,
                    CONF_MODEL: model,
                    CONF_PROFILE: self._profile,
                },
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"model": model, "device_id": self._device_id},
        )


class RoundhouseOptionsFlow(OptionsFlow):
    """Handle the Roundhouse options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        """Edit the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        fields: dict[Any, Any] = {}
        fields[
            vol.Required(
                OPT_PRESENCE_GRACE_HOURS,
                default=opts.get(
                    OPT_PRESENCE_GRACE_HOURS, DEFAULT_PRESENCE_GRACE_HOURS
                ),
            )
        ] = vol.All(int, vol.Range(min=1, max=168))
        fields[
            vol.Required(
                OPT_ALERT_MAX_COUNT,
                default=opts.get(OPT_ALERT_MAX_COUNT, DEFAULT_ALERT_MAX_COUNT),
            )
        ] = vol.All(int, vol.Range(min=1, max=200))
        fields[
            vol.Required(
                OPT_ALERT_MAX_AGE_DAYS,
                default=opts.get(OPT_ALERT_MAX_AGE_DAYS, DEFAULT_ALERT_MAX_AGE_DAYS),
            )
        ] = vol.All(int, vol.Range(min=1, max=365))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
