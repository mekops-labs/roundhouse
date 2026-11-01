"""What a device may ask Home Assistant to do, and the checks on it.

Pure functions with no Home Assistant imports. `build` turns a command into a
service call, or raises `Denied` or `Invalid`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Actions that need `confirmed: true`.
CONFIRM = frozenset(
    {("lock", "unlock"), ("lock", "open"), ("alarm_control_panel", "alarm_disarm")}
)


class Denied(Exception):
    """The command is not allowed at all."""


class Invalid(Exception):
    """The command is allowed, but a value is not."""


@dataclass(frozen=True)
class Call:
    """A service call to make."""

    domain: str
    service: str
    data: dict[str, Any]


def needs_confirmation(domain: str, action: str) -> bool:
    """Return whether the action needs `confirmed: true`."""
    return (domain, action) in CONFIRM


# --- value checks -----------------------------------------------------------


def _number(
    value: Any, name: str, lo: float | None = None, hi: float | None = None
) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
    ):
        raise Invalid(f"{name} must be a number")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise Invalid(f"{name} {value} is outside {lo}..{hi}")
    return value


def _integer(value: Any, name: str, lo: int, hi: int) -> int:
    number = _number(value, name, lo, hi)
    if int(number) != number:
        raise Invalid(f"{name} must be a whole number")
    return int(number)


def _member(
    value: Any,
    name: str,
    allowed: Any,
    control: str | None,
    controls: Sequence[Mapping[str, Any]],
) -> str:
    """Check a mode or option against the entity's list and the tile's controls."""
    if not isinstance(value, str):
        raise Invalid(f"{name} must be a string")
    if not isinstance(allowed, list) or value not in allowed:
        raise Invalid(f"{name} {value!r} is not offered by the entity")
    for c in controls:
        if c.get("type") == control and "values" in c and value not in c["values"]:
            raise Invalid(f"{name} {value!r} is not enabled on the tile")
    return value


def _only(data: Mapping[str, Any], *keys: str) -> None:
    extra = set(data) - set(keys)
    if extra:
        raise Invalid(f"unexpected data {sorted(extra)}")


def _none(data: Mapping[str, Any]) -> dict[str, Any]:
    _only(data)
    return {}


# --- per-action builders ----------------------------------------------------

Builder = Callable[
    [Mapping[str, Any], Mapping[str, Any], Sequence[Mapping[str, Any]]], dict[str, Any]
]


def _light_turn_on(
    data: Mapping[str, Any], attrs: Mapping[str, Any], _c: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _only(data, "brightness", "color_temp_kelvin")
    out: dict[str, Any] = {}
    if "brightness" in data:
        out["brightness"] = _integer(data["brightness"], "brightness", 0, 255)
    if "color_temp_kelvin" in data:
        lo = attrs.get("min_color_temp_kelvin", 1000)
        hi = attrs.get("max_color_temp_kelvin", 40000)
        out["color_temp_kelvin"] = _integer(
            data["color_temp_kelvin"], "color_temp_kelvin", lo, hi
        )
    return out


def _temperature(
    data: Mapping[str, Any], attrs: Mapping[str, Any], _c: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _only(data, "temperature", "target_temp_low", "target_temp_high")
    lo, hi = attrs.get("min_temp"), attrs.get("max_temp")
    if "temperature" in data:
        if "target_temp_low" in data or "target_temp_high" in data:
            raise Invalid("give one target or a low and a high")
        return {"temperature": _number(data["temperature"], "temperature", lo, hi)}
    if "target_temp_low" in data and "target_temp_high" in data:
        low = _number(data["target_temp_low"], "target_temp_low", lo, hi)
        high = _number(data["target_temp_high"], "target_temp_high", lo, hi)
        if low > high:
            raise Invalid("target_temp_low is above target_temp_high")
        return {"target_temp_low": low, "target_temp_high": high}
    raise Invalid("a target temperature is required")


def _single(key: str, builder: Callable[..., Any]) -> Builder:
    def build(
        data: Mapping[str, Any],
        attrs: Mapping[str, Any],
        controls: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        _only(data, key)
        if key not in data:
            raise Invalid(f"{key} is required")
        return {key: builder(data[key], attrs, controls)}

    return build


def _percent(key: str) -> Builder:
    return _single(key, lambda v, a, c: _integer(v, key, 0, 100))


def _humidity(
    v: Any, attrs: Mapping[str, Any], _c: Sequence[Mapping[str, Any]]
) -> float | int:
    return _number(
        v, "humidity", attrs.get("min_humidity", 0), attrs.get("max_humidity", 100)
    )


def _mode(key: str, source: str, control: str) -> Builder:
    return _single(key, lambda v, a, c: _member(v, key, a.get(source), control, c))


def _set_value(
    data: Mapping[str, Any], attrs: Mapping[str, Any], _c: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _only(data, "value")
    if "value" not in data:
        raise Invalid("value is required")
    return {
        "value": _number(
            data["value"], "value", attrs.get("min", 0), attrs.get("max", 100)
        )
    }


def _no_data(
    data: Mapping[str, Any], attrs: Mapping[str, Any], _c: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return _none(data)


def _temp_only(
    data: Mapping[str, Any], attrs: Mapping[str, Any], c: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _only(data, "temperature")
    if "temperature" not in data:
        raise Invalid("temperature is required")
    return {
        "temperature": _number(
            data["temperature"],
            "temperature",
            attrs.get("min_temp"),
            attrs.get("max_temp"),
        )
    }


_TOGGLE: dict[str, Builder] = {"toggle": _no_data}
_TURN: dict[str, Builder] = {"turn_on": _no_data, "turn_off": _no_data}

# Entity domain -> action -> builder.
TABLE: dict[str, dict[str, Builder]] = {
    "light": {"toggle": _no_data, "turn_on": _light_turn_on, "turn_off": _no_data},
    "switch": _TOGGLE,
    "input_boolean": _TOGGLE,
    "fan": {
        "toggle": _no_data,
        "set_percentage": _percent("percentage"),
        "set_preset_mode": _mode("preset_mode", "preset_modes", "fan_preset_mode"),
    },
    "cover": {
        "open_cover": _no_data,
        "close_cover": _no_data,
        "stop_cover": _no_data,
        "set_cover_position": _percent("position"),
    },
    "climate": {
        "set_temperature": _temperature,
        "set_hvac_mode": _mode("hvac_mode", "hvac_modes", "hvac_mode"),
        "set_fan_mode": _mode("fan_mode", "fan_modes", "fan_mode"),
        "set_preset_mode": _mode("preset_mode", "preset_modes", "preset_mode"),
        "set_swing_mode": _mode("swing_mode", "swing_modes", "swing_mode"),
        "set_humidity": _single("humidity", _humidity),
        **_TURN,
    },
    "water_heater": {
        "set_temperature": _temp_only,
        "set_operation_mode": _mode(
            "operation_mode", "operation_list", "operation_mode"
        ),
        **_TURN,
    },
    "humidifier": {
        **_TURN,
        "set_humidity": _single("humidity", _humidity),
        "set_mode": _mode("mode", "available_modes", "humidifier_mode"),
    },
    "number": {"set_value": _set_value},
    "input_number": {"set_value": _set_value},
    "select": {"select_option": _mode("option", "options", "select")},
    "input_select": {"select_option": _mode("option", "options", "select")},
    "valve": {
        "open_valve": _no_data,
        "close_valve": _no_data,
        "stop_valve": _no_data,
        "set_valve_position": _percent("position"),
    },
    "lock": {"lock": _no_data, "unlock": _no_data, "open": _no_data},
    "alarm_control_panel": {
        "alarm_arm_home": _no_data,
        "alarm_arm_away": _no_data,
        "alarm_disarm": _no_data,
    },
    "scene": {"turn_on": _no_data},
    "script": {"turn_on": _no_data},
    "button": {"press": _no_data},
    "input_button": {"press": _no_data},
}


def allowed(domain: str, action: str) -> bool:
    """Return whether the action exists for the entity domain."""
    return action in TABLE.get(domain, {})


def build(
    entity_id: str,
    action: str,
    data: Mapping[str, Any],
    attrs: Mapping[str, Any],
    controls: Sequence[Mapping[str, Any]],
) -> Call:
    """Check one entity command and return the service call.

    Raises `Denied` for an action the domain does not have, `Invalid` for a
    value that fails its check. Only validated keys reach the call.
    """
    domain = entity_id.split(".", 1)[0]
    builder = TABLE.get(domain, {}).get(action)
    if builder is None:
        raise Denied(f"{action} is not allowed on {domain}")
    return Call(
        domain, action, {"entity_id": entity_id, **builder(data, attrs, controls)}
    )
