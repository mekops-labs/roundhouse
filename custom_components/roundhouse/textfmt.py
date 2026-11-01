"""State text: what a tile shows under its name.

Pure functions with no Home Assistant imports. The caller supplies the
translation and number-format callbacks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

STATE_UNAVAILABLE = "unavailable"
STATE_UNKNOWN = "unknown"
SEP = " · "
ARROW = " → "

# Languages that write the decimal separator as a comma.
_COMMA_LANGUAGES = frozenset(
    (
        "bg cs da de el es et fi fr hr hu id it lt lv nb nl no pl pt ro ru sk sl sr sv"
        " tr uk vi"
    ).split()
)

# Words Home Assistant core does not translate; the frontend does.
_COMMON: dict[str, dict[str, str]] = {
    "en": {STATE_UNAVAILABLE: "Unavailable", STATE_UNKNOWN: "Unknown"},
    "pl": {STATE_UNAVAILABLE: "Niedostępny", STATE_UNKNOWN: "Nieznany"},
    "de": {STATE_UNAVAILABLE: "Nicht verfügbar", STATE_UNKNOWN: "Unbekannt"},
    "fr": {STATE_UNAVAILABLE: "Indisponible", STATE_UNKNOWN: "Inconnu"},
    "es": {STATE_UNAVAILABLE: "No disponible", STATE_UNKNOWN: "Desconocido"},
    "it": {STATE_UNAVAILABLE: "Non disponibile", STATE_UNKNOWN: "Sconosciuto"},
    "nl": {STATE_UNAVAILABLE: "Niet beschikbaar", STATE_UNKNOWN: "Onbekend"},
}


def common_word(language: str, word: str) -> str:
    """Return `unavailable` or `unknown` in the language, else in English."""
    table = _COMMON.get(language.split("-")[0].lower(), _COMMON["en"])
    return table.get(word, word)


def format_number(value: float, language: str, precision: int | None = None) -> str:
    """Format a number: fixed decimals with a precision, else the shortest form."""
    if precision is not None:
        text = f"{value:.{max(precision, 0)}f}"
    else:
        text = f"{round(value, 2):.2f}".rstrip("0").rstrip(".")
    if language.split("-")[0].lower() in _COMMA_LANGUAGES:
        text = text.replace(".", ",")
    return "0" if text in ("-0", "") else text


@dataclass(frozen=True)
class Ctx:
    """What the formatter needs from the outside.

    `tr` translates this entity's state, `tra` translates the value of one of
    its attributes. `local` formats an ISO timestamp or date in local time.
    """

    language: str
    tr: Callable[[str], str]
    tra: Callable[[str, str], str]
    local: Callable[[str, str], str]
    temperature_unit: str = "°C"
    precision: int | None = None
    unit: str | None = None
    device_class: str | None = None

    def num(self, value: Any, precision: int | None = None) -> str | None:
        """Format a numeric value, or None when it is not a number."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return format_number(number, self.language, precision)

    def common(self, word: str) -> str:
        """Translate `unavailable` or `unknown`."""
        return common_word(self.language, word)


def _join(*parts: str | None) -> str:
    return SEP.join(p for p in parts if p)


def _percent(value: Any, ctx: Ctx) -> str | None:
    text = ctx.num(value, 0)
    return f"{text}%" if text is not None else None


def _temps(attrs: Mapping[str, Any], ctx: Ctx) -> str | None:
    """Return `current → target unit` for a temperature entity."""
    unit = ctx.temperature_unit
    current = ctx.num(attrs.get("current_temperature"))
    low, high = (
        ctx.num(attrs.get("target_temp_low")),
        ctx.num(attrs.get("target_temp_high")),
    )
    target = ctx.num(attrs.get("temperature"))
    if low is not None and high is not None:
        target = f"{low}-{high}"
    if current is not None and target is not None:
        return f"{current}{ARROW}{target} {unit}"
    if target is not None:
        return f"{ARROW.lstrip()}{target} {unit}"
    if current is not None:
        return f"{current} {unit}"
    return None


def _brightness_percent(attrs: Mapping[str, Any]) -> int | None:
    value = attrs.get("brightness")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(value * 100 / 255)
    return None


_HANDLED = frozenset(
    {
        "light",
        "fan",
        "cover",
        "valve",
        "climate",
        "water_heater",
        "humidifier",
        "number",
        "input_number",
        "sensor",
        "select",
        "input_select",
        "switch",
        "input_boolean",
        "lock",
        "alarm_control_panel",
        "binary_sensor",
        "person",
    }
)


def format_state(domain: str, state: str, attrs: Mapping[str, Any], ctx: Ctx) -> str:
    """Return the state text of an entity.

    The text starts with a capital letter, because Home Assistant's translations
    are lower case in some languages and the frontend capitalizes them. Other
    domains show the raw state.
    """
    text = _format(domain, state, attrs, ctx)
    if domain in _HANDLED and state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return text[:1].upper() + text[1:]
    return text


def _format(domain: str, state: str, attrs: Mapping[str, Any], ctx: Ctx) -> str:
    if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return ctx.common(state)
    translated = ctx.tr(state)

    if domain == "light":
        pct = _brightness_percent(attrs)
        return _join(
            translated, f"{pct}%" if state == "on" and pct is not None else None
        )
    if domain == "fan":
        return _join(
            translated,
            _percent(attrs.get("percentage"), ctx) if state == "on" else None,
        )
    if domain in ("cover", "valve"):
        pos = attrs.get("current_position")
        moving_or_open = state in ("open", "opening", "closing")
        return _join(translated, _percent(pos, ctx) if moving_or_open else None)
    if domain == "climate":
        action = attrs.get("hvac_action")
        head = ctx.tra("hvac_action", str(action)) if action else translated
        return _join(head, _temps(attrs, ctx))
    if domain == "water_heater":
        return _join(translated, _temps(attrs, ctx))
    if domain == "humidifier":
        current, target = (
            ctx.num(attrs.get("current_humidity"), 0),
            ctx.num(attrs.get("humidity"), 0),
        )
        if current is not None and target is not None:
            hum = f"{current}{ARROW}{target}%"
        elif target is not None:
            hum = f"{target}%"
        else:
            hum = None
        return _join(translated, hum)
    if domain in ("number", "input_number"):
        text = ctx.num(state, ctx.precision)
        return _join_unit(
            text if text is not None else state,
            ctx.unit or attrs.get("unit_of_measurement"),
        )
    if domain == "sensor":
        return _sensor(state, translated, attrs, ctx)
    if domain in ("select", "input_select"):
        return translated
    if domain in (
        "switch",
        "input_boolean",
        "lock",
        "alarm_control_panel",
        "binary_sensor",
    ):
        return translated
    if domain == "person":
        return translated
    return state


def _join_unit(text: str, unit: Any) -> str:
    return f"{text} {unit}" if unit else text


def _sensor(state: str, translated: str, attrs: Mapping[str, Any], ctx: Ctx) -> str:
    device_class = ctx.device_class or attrs.get("device_class")
    if device_class in ("timestamp", "date"):
        return ctx.local(state, str(device_class))
    if device_class == "enum":
        return translated
    text = ctx.num(state, ctx.precision)
    if text is None:
        return _join_unit(state, None)
    return _join_unit(text, ctx.unit or attrs.get("unit_of_measurement"))
