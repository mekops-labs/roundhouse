"""The rules for a device's views: supported entities, controls, and saves.

Pure functions with no Home Assistant imports.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_TITLE = 32
MAX_NAME = 32

_ENTITY_ID = re.compile(r"^([a-z0-9_]+)\.[a-z0-9_]+$")

# What a tap does, by entity domain.
_TOGGLE = frozenset({"light", "switch", "input_boolean", "fan"})
_ACTIVATE = frozenset({"scene", "script", "button", "input_button"})

# The detail-page domain: input helpers share the page of their base domain.
_PAGE_DOMAIN = {
    "input_boolean": "switch",
    "input_number": "number",
    "input_select": "select",
    "input_button": "button",
}

# Domains the device formats state for or can command.
SUPPORTED_DOMAINS = frozenset(
    {
        "alarm_control_panel",
        "binary_sensor",
        "button",
        "climate",
        "cover",
        "fan",
        "humidifier",
        "input_boolean",
        "input_button",
        "input_number",
        "input_select",
        "light",
        "lock",
        "number",
        "person",
        "scene",
        "script",
        "select",
        "sensor",
        "switch",
        "valve",
        "water_heater",
    }
)


@dataclass(frozen=True)
class Control:
    """One control a detail page can show for a domain.

    `values_attr` is the entity attribute that lists the choices of a mode
    control; the editor offers them and a tile may keep only some.
    """

    type: str
    values_attr: str | None = None


_TARGET_TEMPERATURE = Control("target_temperature")
_TARGET_HUMIDITY = Control("target_humidity")

CONTROLS: dict[str, tuple[Control, ...]] = {
    "climate": (
        Control("hvac_mode", "hvac_modes"),
        Control("preset_mode", "preset_modes"),
        Control("fan_mode", "fan_modes"),
        Control("swing_mode", "swing_modes"),
        _TARGET_TEMPERATURE,
        _TARGET_HUMIDITY,
    ),
    "fan": (Control("fan_speed"), Control("fan_preset_mode", "preset_modes")),
    "water_heater": (
        Control("operation_mode", "operation_list"),
        _TARGET_TEMPERATURE,
    ),
    "humidifier": (
        Control("humidifier_mode", "available_modes"),
        Control("humidifier_toggle"),
        _TARGET_HUMIDITY,
    ),
    "number": (Control("number"),),
    "input_number": (Control("number"),),
    "select": (Control("select", "options"),),
    "input_select": (Control("select", "options"),),
    "cover": (Control("cover_open_close"), Control("cover_position")),
    "valve": (Control("valve_open_close"), Control("valve_position")),
    "light": (Control("light_brightness"), Control("light_color_temp")),
}


@dataclass(frozen=True)
class RuleError:
    """One reason a save is refused, with where it is."""

    code: str
    message: str
    view: int | None = None
    tile: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the shape sent to the editor."""
        return {
            "code": self.code,
            "message": self.message,
            "view": self.view,
            "tile": self.tile,
        }


def domain_of(entity_id: str) -> str | None:
    """Return the domain of a well-formed entity ID, else None."""
    match = _ENTITY_ID.match(entity_id)
    return match.group(1) if match else None


def tile_kind(entity_id: str) -> str:
    """Return what a tap does: `toggle`, `activate`, or `readonly`."""
    domain = entity_id.split(".", 1)[0]
    if domain in _TOGGLE:
        return "toggle"
    if domain in _ACTIVATE:
        return "activate"
    return "readonly"


def page_domain(entity_id: str) -> str:
    """Return the domain of the entity's detail page."""
    domain = entity_id.split(".", 1)[0]
    return _PAGE_DOMAIN.get(domain, domain)


def resolve_tile(
    tile: Mapping[str, Any], friendly_name: Callable[[str], str | None]
) -> dict[str, Any]:
    """Return the contract shape of a stored tile."""
    entity_id: str = tile["entity_id"]
    name = tile.get("name") or friendly_name(entity_id) or entity_id
    out: dict[str, Any] = {
        "entity_id": entity_id,
        "name": name,
        "kind": tile_kind(entity_id),
        "domain": page_domain(entity_id),
    }
    if tile.get("controls"):
        out["controls"] = [dict(c) for c in tile["controls"]]
    return out


def _controls_error(domain: str, controls: Any) -> str | None:
    """Return why `controls` is not valid for the domain, or None."""
    if not isinstance(controls, list):
        return "controls must be a list"
    allowed = {c.type: c for c in CONTROLS.get(domain, ())}
    seen: set[str] = set()
    for control in controls:
        if not isinstance(control, Mapping) or not isinstance(control.get("type"), str):
            return "a control must be an object with a type"
        kind = control["type"]
        if kind not in allowed:
            return f"{kind} is not a control of {domain}"
        if kind in seen:
            return f"{kind} is listed twice"
        seen.add(kind)
        if "values" in control:
            values = control["values"]
            if allowed[kind].values_attr is None:
                return f"{kind} takes no values"
            if not isinstance(values, list) or not all(
                isinstance(v, str) for v in values
            ):
                return f"the values of {kind} must be a list of strings"
    return None


def _tile_errors(
    index: int,
    at: int,
    tile: Any,
    icon_known: Callable[[str], bool],
) -> list[RuleError]:
    if not isinstance(tile, Mapping) or not isinstance(tile.get("entity_id"), str):
        return [RuleError("bad_tile", "A tile needs an entity", index, at)]
    domain = domain_of(tile["entity_id"])
    out: list[RuleError] = []
    if domain is None or domain not in SUPPORTED_DOMAINS:
        out.append(
            RuleError(
                "unsupported_domain",
                f"{tile['entity_id']} cannot be shown on a device",
                index,
                at,
            )
        )
    name = tile.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > MAX_NAME):
        out.append(
            RuleError(
                "bad_name", f"A name has at most {MAX_NAME} characters", index, at
            )
        )
    icon = tile.get("icon")
    if icon is not None and not (
        isinstance(icon, str) and icon.startswith("mdi:") and icon_known(icon)
    ):
        out.append(RuleError("bad_icon", "The icon is not a known mdi icon", index, at))
    if "controls" in tile and domain is not None:
        reason = _controls_error(domain, tile["controls"])
        if reason:
            out.append(RuleError("bad_controls", reason, index, at))
    return out


def _view_errors(
    index: int,
    view: Mapping[str, Any],
    profile: Mapping[str, Any],
    icon_known: Callable[[str], bool],
) -> list[RuleError]:
    out: list[RuleError] = []
    title = view.get("title")
    if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
        out.append(
            RuleError(
                "bad_title",
                f"A title has 1 to {MAX_TITLE} characters",
                index,
            )
        )
    layouts = profile["layouts"]
    layout = view.get("layout")
    tiles = view.get("tiles")
    if not isinstance(tiles, list):
        return [*out, RuleError("bad_tile", "A view needs a list of tiles", index)]
    if (
        not isinstance(layout, int)
        or isinstance(layout, bool)
        or not 0 <= layout < len(layouts)
    ):
        out.append(RuleError("unknown_layout", "The device has no such layout", index))
    elif len(tiles) > len(layouts[layout]["slots"]):
        slots = len(layouts[layout]["slots"])
        out.append(
            RuleError(
                "too_many_tiles",
                f"The layout holds {slots} tiles; remove {len(tiles) - slots}",
                index,
            )
        )
    for at, tile in enumerate(tiles):
        out.extend(_tile_errors(index, at, tile, icon_known))
    return out


def validate(
    views: Sequence[Mapping[str, Any]],
    snapshot: str | None,
    profile: Mapping[str, Any],
    *,
    icon_known: Callable[[str], bool],
) -> list[RuleError]:
    """Return every rule the views break against the device's profile."""
    errors: list[RuleError] = []
    paths: set[str] = set()
    for index, view in enumerate(views):
        path = view.get("path")
        if not isinstance(path, str) or not path:
            errors.append(RuleError("bad_path", "A view needs a path", index))
        elif path in paths:
            errors.append(RuleError("duplicate_path", "A path is used twice", index))
        else:
            paths.add(path)
        errors.extend(_view_errors(index, view, profile, icon_known))
    if snapshot is not None and (
        "sleep" not in profile.get("features", []) or snapshot not in paths
    ):
        errors.append(
            RuleError(
                "bad_snapshot",
                "The snapshot view must be a view of a device that sleeps",
            )
        )
    return errors
