"""Repair issues raised by Roundhouse."""

from __future__ import annotations

import hashlib
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


def _overflow_prefix(device_id: str) -> str:
    return f"overflow.{device_id}."  # a device ID never holds a dot


def overflow_issue_id(device_id: str, path: str) -> str:
    """Return the issue and notification ID of an overflowing view.

    The hash keeps apart paths with the same slug, such as `a-b` and `a_b`.
    """
    digest = hashlib.sha256(path.encode()).hexdigest()[:8]
    return f"{_overflow_prefix(device_id)}{_slug(path)}.{digest}"


def raise_overflow(
    hass: HomeAssistant,
    device_id: str,
    path: str,
    title: str,
    excess: int,
    capacity: int,
    *,
    layout_gone: bool,
) -> None:
    """Raise a repair issue and a notification for a view the device cannot show.

    `layout_gone` tells that the view's layout is no longer in the profile.
    """
    issue_id = overflow_issue_id(device_id, path)
    if layout_gone:
        key = "view_layout_gone"
        heading = "Roundhouse: view layout gone"
        text = (
            f"View '{title}' cannot be shown on {device_id}: its layout is no "
            "longer offered. Open the Roundhouse page and choose another layout. "
            "The device does not show this view."
        )
    else:
        key = "view_overflow"
        heading = "Roundhouse: view too large"
        text = (
            f"View '{title}' does not fit on {device_id}: remove {excess} "
            f"tile(s), its layout holds {capacity}. The device does not show "
            "this view."
        )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=key,
        translation_placeholders={
            "device": device_id,
            "view": title,
            "excess": str(excess),
            "capacity": str(capacity),
        },
    )
    persistent_notification.async_create(
        hass, text, title=heading, notification_id=issue_id
    )


def clear_device_issues(hass: HomeAssistant, device_id: str) -> None:
    """Remove every issue and notification of a removed device."""
    clear_profile_issue(hass, device_id)
    prefix = _overflow_prefix(device_id)
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            persistent_notification.async_dismiss(hass, issue_id)


def clear_overflow(hass: HomeAssistant, device_id: str, path: str) -> None:
    """Remove the issue and the notification of a view."""
    issue_id = overflow_issue_id(device_id, path)
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    persistent_notification.async_dismiss(hass, issue_id)
