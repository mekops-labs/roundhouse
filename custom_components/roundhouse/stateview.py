"""The state message of an entity: attributes, color, and flags.

Pure functions with no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .textfmt import STATE_UNAVAILABLE

# Feature bit of `set_position` on covers and valves.
SUPPORT_SET_POSITION = 4

_OFF_STATES = frozenset(
    {
        "off",
        "closed",
        "closing",
        "locked",
        "unavailable",
        "unknown",
        "not_home",
        "idle",
        "standby",
        "disarmed",
        "paused",
        "none",
        "stopped",
    }
)

AMBER = (255, 193, 7)
ACTIVE_BLUE = (3, 169, 244)
HEAT = (255, 87, 34)
COOL = (33, 150, 243)
ALARM = (244, 67, 54)

Label = Callable[[str, str], str]


def available(state: str | None) -> bool:
    """Return whether the entity has a usable state."""
    return state is not None and state != STATE_UNAVAILABLE


def is_on(domain: str, state: str | None, attrs: Mapping[str, Any]) -> bool:
    """Return whether the tile is in its active state (drawn inverted)."""
    if state is None:
        return False
    if domain == "climate":
        action = attrs.get("hvac_action")
        if action:
            return str(action) not in ("off", "idle")
        return state not in _OFF_STATES
    if domain == "alarm_control_panel":
        return state.startswith("armed") or state in ("triggered", "pending", "arming")
    if domain == "lock":
        return state == "unlocked"
    return state not in _OFF_STATES


def color(domain: str, state: str | None, attrs: Mapping[str, Any]) -> list[int] | None:
    """Return the state color: a light's own color, else the domain's active color."""
    if not is_on(domain, state, attrs):
        return None
    rgb = attrs.get("rgb_color")
    if domain == "light":
        if isinstance(rgb, list | tuple) and len(rgb) == 3:
            return [int(c) for c in rgb]
        return list(AMBER)
    if domain == "climate":
        action = str(attrs.get("hvac_action") or state)
        if action in ("heating", "heat"):
            return list(HEAT)
        if action in ("cooling", "cool"):
            return list(COOL)
    if domain == "alarm_control_panel":
        return list(ALARM)
    return list(ACTIVE_BLUE)


def _pair(name: str, value: Any, label: Label) -> dict[str, str]:
    return {"value": str(value), "label": label(name, str(value))}


def _pairs(name: str, values: Any, label: Label) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    return [_pair(name, v, label) for v in values]


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        out[key] = value


def attributes(
    domain: str,
    state: str | None,
    attrs: Mapping[str, Any],
    features: int,
    label: Label,
) -> dict[str, Any]:
    """Return what the detail page of the entity's domain needs.

    Every mode and option is a `{value, label}` pair; `label(attribute, value)`
    translates it.
    """
    out: dict[str, Any] = {}
    get = attrs.get
    if domain == "climate":
        for key in (
            "current_temperature",
            "current_humidity",
            "temperature",
            "target_temp_low",
            "target_temp_high",
            "humidity",
            "min_temp",
            "max_temp",
            "target_temp_step",
        ):
            _put(out, key, get(key))
        for single, plural, source in (
            ("hvac_action", None, None),
            ("fan_mode", "fan_modes", "fan_modes"),
            ("preset_mode", "preset_modes", "preset_modes"),
            ("swing_mode", "swing_modes", "swing_modes"),
        ):
            if get(single) is not None:
                out[single] = _pair(single, get(single), label)
            if plural and source and get(source) is not None:
                out[plural] = _pairs(single, get(source), label)
        if state is not None and state != STATE_UNAVAILABLE:
            out["hvac_mode"] = _pair("hvac_mode", state, label)
        if get("hvac_modes") is not None:
            out["hvac_modes"] = _pairs("hvac_mode", get("hvac_modes"), label)
    elif domain == "water_heater":
        for key in ("current_temperature", "temperature", "min_temp", "max_temp"):
            _put(out, key, get(key))
        if get("operation_mode") is not None:
            out["operation_mode"] = _pair(
                "operation_mode", get("operation_mode"), label
            )
        if get("operation_list") is not None:
            out["operation_modes"] = _pairs(
                "operation_mode", get("operation_list"), label
            )
    elif domain == "humidifier":
        for key in ("current_humidity", "humidity", "min_humidity", "max_humidity"):
            _put(out, key, get(key))
        if get("mode") is not None:
            out["mode"] = _pair("mode", get("mode"), label)
        if get("available_modes") is not None:
            out["modes"] = _pairs("mode", get("available_modes"), label)
    elif domain == "fan":
        for key in ("percentage", "percentage_step"):
            _put(out, key, get(key))
        if get("preset_mode") is not None:
            out["preset_mode"] = _pair("preset_mode", get("preset_mode"), label)
        if get("preset_modes") is not None:
            out["preset_modes"] = _pairs("preset_mode", get("preset_modes"), label)
    elif domain in ("number", "input_number"):
        try:
            out["value"] = float(state) if state is not None else None
        except (TypeError, ValueError):
            out["value"] = None
        for key, src in (
            ("min", "min"),
            ("max", "max"),
            ("step", "step"),
            ("unit", "unit_of_measurement"),
            ("mode", "mode"),
        ):
            _put(out, key, get(src))
    elif domain in ("select", "input_select"):
        if state is not None and state != STATE_UNAVAILABLE:
            out["option"] = _pair("option", state, label)
        if get("options") is not None:
            out["options"] = _pairs("option", get("options"), label)
    elif domain in ("valve", "cover"):
        _put(out, "position", get("current_position"))
        out["supports_position"] = bool(features & SUPPORT_SET_POSITION)
    elif domain == "light":
        _put(out, "brightness", get("brightness"))
        for key, src in (
            ("color_temp_kelvin", "color_temp_kelvin"),
            ("min_color_temp_kelvin", "min_color_temp_kelvin"),
            ("max_color_temp_kelvin", "max_color_temp_kelvin"),
        ):
            _put(out, key, get(src))
    return out


def message(
    domain: str,
    state: str | None,
    attrs: Mapping[str, Any],
    features: int,
    text: str,
    icon: str,
    label: Label,
) -> dict[str, Any]:
    """Assemble the `state/<entity_id>` payload."""
    return {
        "text": text,
        "on": is_on(domain, state, attrs),
        "available": available(state),
        "icon": icon,
        "color": color(domain, state, attrs),
        "attributes": attributes(domain, state, attrs, features, label),
    }
