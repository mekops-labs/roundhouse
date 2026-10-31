"""Repair issues raised by Roundhouse."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_MQTT_BIRTH

# Birth topic that devices watch to learn that Home Assistant is up.
BIRTH_TOPIC = "homeassistant/status"


def profile_issue_id(device_id: str) -> str:
    """Return the issue ID for a device's profile problem."""
    return f"profile_{device_id}"


def raise_profile_issue(
    hass: HomeAssistant, device_id: str, code: str, detail: str
) -> None:
    """Raise a repair issue for a bad profile or a contract mismatch."""
    key = "contract_mismatch" if code == "major_mismatch" else "profile_invalid"
    ir.async_create_issue(
        hass,
        DOMAIN,
        profile_issue_id(device_id),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=key,
        translation_placeholders={"device": device_id, "detail": detail},
    )


def clear_profile_issue(hass: HomeAssistant, device_id: str) -> None:
    """Remove a device's profile issue."""
    ir.async_delete_issue(hass, DOMAIN, profile_issue_id(device_id))


def check_mqtt_birth(hass: HomeAssistant) -> None:
    """Raise a repair issue when the MQTT birth message is disabled."""
    enabled = False
    for entry in hass.config_entries.async_entries("mqtt"):
        birth = {**entry.data, **entry.options}.get("birth_message", {})
        # An absent key means the default, which is enabled.
        if "birth_message" not in {**entry.data, **entry.options}:
            enabled = True
        elif birth and birth.get("topic") == BIRTH_TOPIC:
            enabled = True
    if enabled:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_MQTT_BIRTH)
    else:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_MQTT_BIRTH,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MQTT_BIRTH,
        )
