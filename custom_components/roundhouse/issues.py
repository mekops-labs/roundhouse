"""Repair issues raised by Roundhouse."""

from __future__ import annotations

import re

from homeassistant.components import persistent_notification
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "view"


def overflow_issue_id(device_id: str, path: str) -> str:
    """Return the issue and notification ID of an overflowing view."""
    return f"overflow_{device_id}_{_slug(path)}"


def raise_dashboard_issue(hass: HomeAssistant, device_id: str, kind: str) -> None:
    """Raise a repair issue for a `strategy` or `deleted` dashboard."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{kind}_{device_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=f"dashboard_{kind}",
        translation_placeholders={"device": device_id},
    )


def clear_dashboard_issues(hass: HomeAssistant, device_id: str) -> None:
    """Remove the strategy and deleted-dashboard issues of a device."""
    for kind in ("strategy", "deleted"):
        ir.async_delete_issue(hass, DOMAIN, f"{kind}_{device_id}")


def raise_overflow(
    hass: HomeAssistant,
    device_id: str,
    path: str,
    title: str,
    excess: int,
    capacity: int,
) -> None:
    """Raise a repair issue and a notification for a view that does not fit."""
    issue_id = overflow_issue_id(device_id, path)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="view_overflow",
        translation_placeholders={
            "device": device_id,
            "view": title,
            "excess": str(excess),
            "capacity": str(capacity),
        },
    )
    persistent_notification.async_create(
        hass,
        f"View '{title}' does not fit on {device_id}: remove {excess} tile(s), "
        f"the densest layout holds {capacity}. The device keeps the last "
        "version that fitted.",
        title="Roundhouse: view too large",
        notification_id=issue_id,
    )


def clear_overflow(hass: HomeAssistant, device_id: str, path: str) -> None:
    """Remove the issue and the notification of a view."""
    issue_id = overflow_issue_id(device_id, path)
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    persistent_notification.async_dismiss(hass, issue_id)
