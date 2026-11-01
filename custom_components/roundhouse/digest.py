"""Digest a Lovelace dashboard config into tiles.

Pure functions with no Home Assistant imports.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

SKIP_UNSUPPORTED_TYPE = "unsupported type"
SKIP_VISIBILITY = "visibility"
SKIP_NO_ENTITY = "no entity"
SKIP_UNSUPPORTED_FEATURE = "unsupported feature"

_STACKS = frozenset({"vertical-stack", "horizontal-stack", "grid"})
_ENTITY_CARDS = frozenset({"tile", "button", "thermostat", "humidifier"})

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

# Tile feature type -> (control type, config key holding the allowed values).
_FEATURES: dict[str, tuple[str, str | None]] = {
    "climate-hvac-modes": ("hvac_mode", "hvac_modes"),
    "climate-preset-modes": ("preset_mode", "preset_modes"),
    "climate-fan-modes": ("fan_mode", "fan_modes"),
    "climate-swing-modes": ("swing_mode", "swing_modes"),
    "target-temperature": ("target_temperature", None),
    "target-humidity": ("target_humidity", None),
    "fan-speed": ("fan_speed", None),
    "fan-preset-modes": ("fan_preset_mode", "preset_modes"),
    "water-heater-operation-modes": ("operation_mode", "operation_modes"),
    "humidifier-modes": ("humidifier_mode", "modes"),
    "humidifier-toggle": ("humidifier_toggle", None),
    "numeric-input": ("number", None),
    "select-options": ("select", "options"),
    "cover-open-close": ("cover_open_close", None),
    "cover-position": ("cover_position", None),
    "valve-open-close": ("valve_open_close", None),
    "valve-position": ("valve_position", None),
    "light-brightness": ("light_brightness", None),
    "light-color-temp": ("light_color_temp", None),
}


@dataclass(frozen=True)
class Tile:
    """One entity on a view."""

    entity_id: str
    name: str
    kind: str
    domain: str
    controls: tuple[dict[str, Any], ...] = ()
    icon: str | None = None  # the card's icon override; not part of the contract

    def as_dict(self) -> dict[str, Any]:
        """Return the contract shape of a tile."""
        out: dict[str, Any] = {
            "entity_id": self.entity_id,
            "name": self.name,
            "kind": self.kind,
            "domain": self.domain,
        }
        if self.controls:
            out["controls"] = [dict(c) for c in self.controls]
        return out


@dataclass(frozen=True)
class DigestView:
    """One dashboard view and its tiles."""

    path: str
    title: str
    tiles: tuple[Tile, ...]


@dataclass
class DigestResult:
    """The digest of a whole dashboard."""

    views: list[DigestView] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def skipped_total(self) -> int:
        """Return the number of skipped cards and features."""
        return sum(self.skipped.values())


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


def _controls(features: Any, skip: Callable[[str], None]) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    if not isinstance(features, list):
        return ()
    for feature in features:
        spec = (
            _FEATURES.get(feature.get("type", ""))
            if isinstance(feature, dict)
            else None
        )
        if spec is None:
            skip(SKIP_UNSUPPORTED_FEATURE)
            continue
        control: dict[str, Any] = {"type": spec[0]}
        values = feature.get(spec[1]) if spec[1] else None
        if isinstance(values, list) and all(isinstance(v, str) for v in values):
            control["values"] = list(values)
        out.append(control)
    return tuple(out)


def _tile(
    entity: Any,
    name: Any,
    features: Any,
    friendly_name: Callable[[str], str | None],
    skip: Callable[[str], None],
    icon: Any = None,
) -> Tile | None:
    if not isinstance(entity, str) or not _ENTITY_ID.match(entity):
        skip(SKIP_NO_ENTITY)
        return None
    label = name if isinstance(name, str) and name else friendly_name(entity) or entity
    return Tile(
        entity_id=entity,
        name=label,
        kind=tile_kind(entity),
        domain=page_domain(entity),
        controls=_controls(features, skip),
        icon=icon if isinstance(icon, str) and icon else None,
    )


def _walk(
    cards: Any,
    tiles: list[Tile],
    friendly_name: Callable[[str], str | None],
    skip: Callable[[str], None],
) -> None:
    if not isinstance(cards, list):
        return
    for card in cards:
        if not isinstance(card, dict):
            skip(SKIP_UNSUPPORTED_TYPE)
            continue
        if card.get("visibility"):
            skip(SKIP_VISIBILITY)
            continue
        ctype = card.get("type")
        if ctype in _STACKS:
            _walk(card.get("cards"), tiles, friendly_name, skip)
        elif ctype in _ENTITY_CARDS:
            features = card.get("features") if ctype == "tile" else None
            tile = _tile(
                card.get("entity"),
                card.get("name"),
                features,
                friendly_name,
                skip,
                card.get("icon"),
            )
            if tile:
                tiles.append(tile)
        elif ctype == "entities":
            _rows(card.get("entities"), tiles, friendly_name, skip)
        else:
            skip(SKIP_UNSUPPORTED_TYPE)


def _rows(
    rows: Any,
    tiles: list[Tile],
    friendly_name: Callable[[str], str | None],
    skip: Callable[[str], None],
) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, str):
            tile = _tile(row, None, None, friendly_name, skip)
        elif isinstance(row, dict) and "entity" in row:
            tile = _tile(
                row["entity"],
                row.get("name"),
                None,
                friendly_name,
                skip,
                row.get("icon"),
            )
        elif isinstance(row, dict):
            skip(SKIP_UNSUPPORTED_TYPE)
            continue
        else:
            skip(SKIP_NO_ENTITY)
            continue
        if tile:
            tiles.append(tile)


def digest(
    config: Mapping[str, Any], friendly_name: Callable[[str], str | None]
) -> DigestResult:
    """Digest a dashboard config.

    Views keep their order. Masonry, panel, and sidebar views hold their cards
    under `cards`; sections views under `sections[].cards`. A view's path is its
    `path`, else its index.
    """
    result = DigestResult()

    def skip(reason: str) -> None:
        result.skipped[reason] = result.skipped.get(reason, 0) + 1

    views = config.get("views")
    for index, view in enumerate(views if isinstance(views, list) else []):
        if not isinstance(view, dict):
            continue
        tiles: list[Tile] = []
        _walk(view.get("cards"), tiles, friendly_name, skip)
        sections = view.get("sections")
        for section in sections if isinstance(sections, list) else []:
            if isinstance(section, dict):
                _walk(section.get("cards"), tiles, friendly_name, skip)
        path = view.get("path")
        path = path if isinstance(path, str) and path else str(index)
        title = view.get("title")
        result.views.append(
            DigestView(
                path, title if isinstance(title, str) and title else path, tuple(tiles)
            )
        )
    return result


def is_strategy(config: Mapping[str, Any]) -> bool:
    """Return whether a dashboard is generated by a strategy, with no cards."""
    return "strategy" in config and not config.get("views")
