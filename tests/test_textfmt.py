"""State text rules, with fake translations."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import textfmt as tf


def ctx(
    language: str = "en",
    unit: str | None = None,
    precision: int | None = None,
    **kw: Any,
) -> tf.Ctx:
    return tf.Ctx(
        language=language,
        tr=lambda s: s,
        tra=lambda name, v: f"{v}",
        local=lambda v, dc: f"[{dc}] {v}",
        precision=precision,
        unit=unit,
        **kw,
    )


@pytest.mark.parametrize(
    ("domain", "state", "attrs", "expected"),
    [
        ("light", "on", {"brightness": 204}, "On · 80%"),
        ("light", "on", {}, "On"),
        ("light", "off", {"brightness": 204}, "Off"),
        ("switch", "on", {}, "On"),
        ("input_boolean", "off", {}, "Off"),
        ("fan", "on", {"percentage": 50}, "On · 50%"),
        ("fan", "off", {"percentage": 50}, "Off"),
        ("cover", "open", {"current_position": 40}, "Open · 40%"),
        ("cover", "closed", {"current_position": 0}, "Closed"),
        ("cover", "closing", {"current_position": 30}, "Closing · 30%"),
        ("valve", "open", {"current_position": 100}, "Open · 100%"),
        ("lock", "locked", {}, "Locked"),
        ("alarm_control_panel", "armed_away", {}, "Armed_away"),
        ("binary_sensor", "on", {}, "On"),
        ("person", "home", {}, "Home"),
        ("select", "eco", {}, "Eco"),
        ("humidifier", "on", {"humidity": 55}, "On · 55%"),
        ("humidifier", "on", {"humidity": 55, "current_humidity": 48}, "On · 48 → 55%"),
        (
            "water_heater",
            "eco",
            {"current_temperature": 48, "temperature": 55},
            "Eco · 48 → 55 °C",
        ),
    ],
)
def test_domain_rules(
    domain: str, state: str, attrs: dict[str, Any], expected: str
) -> None:
    assert tf.format_state(domain, state, attrs, ctx()) == expected


@pytest.mark.parametrize(
    ("attrs", "state", "expected"),
    [
        (
            {"hvac_action": "heating", "current_temperature": 21.5, "temperature": 22},
            "heat",
            "Heating · 21.5 → 22 °C",
        ),
        (
            {"current_temperature": 21.5, "temperature": 22},
            "heat",
            "Heat · 21.5 → 22 °C",
        ),
        ({"temperature": 22}, "heat", "Heat · → 22 °C"),
        ({"current_temperature": 21.5}, "off", "Off · 21.5 °C"),
        (
            {"current_temperature": 24, "target_temp_low": 20, "target_temp_high": 25},
            "heat_cool",
            "Heat_cool · 24 → 20-25 °C",
        ),
        ({}, "off", "Off"),
    ],
)
def test_climate(attrs: dict[str, Any], state: str, expected: str) -> None:
    assert tf.format_state("climate", state, attrs, ctx()) == expected


def test_climate_action_is_translated_as_an_attribute() -> None:
    c = tf.Ctx(
        language="pl",
        tr=lambda s: "grzanie-stan",
        tra=lambda name, v: f"{name}:{v}-pl",
        local=lambda v, dc: v,
    )
    text = tf.format_state("climate", "heat", {"hvac_action": "heating"}, c)
    assert text == "Hvac_action:heating-pl"


def test_climate_uses_the_configured_temperature_unit() -> None:
    c = ctx(temperature_unit="°F")
    assert (
        tf.format_state("climate", "heat", {"temperature": 70}, c) == "Heat · → 70 °F"
    )


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
def test_unavailable_and_unknown_are_translated(state: str) -> None:
    assert tf.format_state("light", state, {}, ctx()) == state.capitalize()
    assert tf.format_state("light", state, {}, ctx("pl")) in ("Niedostępny", "Nieznany")


def test_common_words_fall_back_to_english() -> None:
    assert tf.common_word("xx", "unavailable") == "Unavailable"
    assert tf.common_word("pl-PL", "unavailable") == "Niedostępny"


def test_numbers_use_precision_unit_and_locale() -> None:
    assert (
        tf.format_state("sensor", "21.456", {}, ctx(unit="°C", precision=1))
        == "21.5 °C"
    )
    assert tf.format_state("sensor", "21", {}, ctx(unit="°C", precision=1)) == "21.0 °C"
    assert tf.format_state("sensor", "21.50", {}, ctx(unit="%")) == "21.5 %"
    assert tf.format_state("sensor", "21.0", {}, ctx(unit="W")) == "21 W"
    assert tf.format_state("sensor", "21.5", {}, ctx("pl", unit="°C")) == "21,5 °C"
    assert tf.format_state("number", "3.14159", {}, ctx(precision=2)) == "3.14"
    assert (
        tf.format_state("input_number", "5", {"unit_of_measurement": "min"}, ctx())
        == "5 min"
    )


def test_sensor_variants() -> None:
    assert tf.format_state("sensor", "abc", {}, ctx()) == "Abc"
    assert (
        tf.format_state(
            "sensor", "2026-10-31T10:00:00+00:00", {}, ctx(device_class="timestamp")
        )
        == "[timestamp] 2026-10-31T10:00:00+00:00"
    )
    assert (
        tf.format_state("sensor", "2026-10-31", {"device_class": "date"}, ctx())
        == "[date] 2026-10-31"
    )
    assert tf.format_state("sensor", "high", {}, ctx(device_class="enum")) == "High"


def test_other_domains_show_the_raw_state() -> None:
    assert tf.format_state("vacuum", "cleaning", {}, ctx()) == "cleaning"
    assert tf.format_state("scene", "2026-01-01", {}, ctx()) == "2026-01-01"


def test_format_number_edges() -> None:
    assert tf.format_number(-0.0, "en") == "0"
    assert tf.format_number(1234.5678, "en") == "1234.57"
    assert tf.format_number(2.0, "de") == "2"
    assert tf.format_number(1.5, "de", 2) == "1,50"
