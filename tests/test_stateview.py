"""Attributes, color, and flags of a state message."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import codec
from custom_components.roundhouse import stateview as sv


def label(name: str, value: str) -> str:
    return f"{value}@{name}"


def pair(name: str, value: str) -> dict[str, str]:
    return {"value": value, "label": f"{value}@{name}"}


def test_climate_attributes_carry_value_and_label_pairs() -> None:
    attrs = {
        "current_temperature": 21.5,
        "temperature": 22,
        "min_temp": 7,
        "max_temp": 30,
        "target_temp_step": 0.5,
        "hvac_action": "heating",
        "hvac_modes": ["heat", "off"],
        "preset_mode": "eco",
        "preset_modes": ["eco", "comfort"],
        "fan_mode": "auto",
        "fan_modes": ["auto", "low"],
        "swing_mode": "off",
        "swing_modes": ["off", "on"],
        "current_humidity": 40,
        "humidity": 50,
        "ignored": "x",
    }
    out = sv.attributes("climate", "heat", attrs, 0, label)
    assert out["current_temperature"] == 21.5
    assert out["hvac_action"] == pair("hvac_action", "heating")
    assert out["hvac_mode"] == pair("hvac_mode", "heat")
    assert out["hvac_modes"] == [pair("hvac_mode", "heat"), pair("hvac_mode", "off")]
    assert out["preset_modes"] == [
        pair("preset_mode", "eco"),
        pair("preset_mode", "comfort"),
    ]
    assert out["fan_modes"] == [pair("fan_mode", "auto"), pair("fan_mode", "low")]
    assert out["swing_mode"] == pair("swing_mode", "off")
    assert out["humidity"] == 50
    assert "ignored" not in out


def test_climate_low_and_high_targets() -> None:
    attrs = {"target_temp_low": 20, "target_temp_high": 25}
    out = sv.attributes("climate", "heat_cool", attrs, 0, label)
    assert (out["target_temp_low"], out["target_temp_high"]) == (20, 25)
    assert "temperature" not in out


def test_water_heater_humidifier_and_fan() -> None:
    wh = sv.attributes(
        "water_heater",
        "eco",
        {
            "current_temperature": 48,
            "temperature": 55,
            "min_temp": 30,
            "max_temp": 70,
            "operation_mode": "eco",
            "operation_list": ["eco", "off"],
        },
        0,
        label,
    )
    assert wh["operation_modes"] == [
        pair("operation_mode", "eco"),
        pair("operation_mode", "off"),
    ]
    hu = sv.attributes(
        "humidifier",
        "on",
        {
            "current_humidity": 40,
            "humidity": 50,
            "min_humidity": 30,
            "max_humidity": 80,
            "mode": "auto",
            "available_modes": ["auto", "sleep"],
        },
        0,
        label,
    )
    assert hu["mode"] == pair("mode", "auto")
    assert hu["modes"] == [pair("mode", "auto"), pair("mode", "sleep")]
    fan = sv.attributes(
        "fan",
        "on",
        {
            "percentage": 50,
            "percentage_step": 25,
            "preset_mode": "eco",
            "preset_modes": ["eco"],
        },
        0,
        label,
    )
    assert fan["percentage_step"] == 25
    assert fan["preset_modes"] == [pair("preset_mode", "eco")]


def test_number_and_select() -> None:
    num = sv.attributes(
        "number",
        "3.5",
        {
            "min": 0,
            "max": 10,
            "step": 0.5,
            "unit_of_measurement": "min",
            "mode": "slider",
        },
        0,
        label,
    )
    assert num == {
        "value": 3.5,
        "min": 0,
        "max": 10,
        "step": 0.5,
        "unit": "min",
        "mode": "slider",
    }
    assert sv.attributes("input_number", "x", {}, 0, label)["value"] is None
    sel = sv.attributes("select", "a", {"options": ["a", "b"]}, 0, label)
    assert sel == {
        "option": pair("option", "a"),
        "options": [pair("option", "a"), pair("option", "b")],
    }


def test_cover_valve_position_support_comes_from_the_feature_bit() -> None:
    with_pos = sv.attributes("cover", "open", {"current_position": 40}, 4 | 1, label)
    assert with_pos == {"position": 40, "supports_position": True}
    without = sv.attributes("valve", "open", {}, 1 | 2, label)
    assert without == {"supports_position": False}


def test_light_attributes() -> None:
    out = sv.attributes(
        "light",
        "on",
        {
            "brightness": 204,
            "color_temp_kelvin": 3000,
            "min_color_temp_kelvin": 2000,
            "max_color_temp_kelvin": 6500,
        },
        0,
        label,
    )
    assert out == {
        "brightness": 204,
        "color_temp_kelvin": 3000,
        "min_color_temp_kelvin": 2000,
        "max_color_temp_kelvin": 6500,
    }


def test_other_domains_have_no_attributes() -> None:
    assert sv.attributes("sensor", "1", {"unit_of_measurement": "W"}, 0, label) == {}


@pytest.mark.parametrize(
    ("domain", "state", "attrs", "on"),
    [
        ("light", "on", {}, True),
        ("light", "off", {}, False),
        ("switch", "unavailable", {}, False),
        ("cover", "open", {}, True),
        ("cover", "closed", {}, False),
        ("lock", "unlocked", {}, True),
        ("lock", "locked", {}, False),
        ("person", "home", {}, True),
        ("person", "not_home", {}, False),
        ("climate", "heat", {"hvac_action": "heating"}, True),
        ("climate", "heat", {"hvac_action": "idle"}, False),
        ("climate", "heat", {}, True),
        ("climate", "off", {}, False),
        ("alarm_control_panel", "armed_away", {}, True),
        ("alarm_control_panel", "disarmed", {}, False),
        ("light", None, {}, False),
    ],
)
def test_on_state(
    domain: str, state: str | None, attrs: dict[str, Any], on: bool
) -> None:
    assert sv.is_on(domain, state, attrs) is on


def test_available_means_not_unavailable_and_present() -> None:
    assert sv.available("on") and sv.available("unknown")
    assert not sv.available("unavailable") and not sv.available(None)


def test_colors() -> None:
    assert sv.color("light", "on", {"rgb_color": [255, 0, 10]}) == [255, 0, 10]
    assert sv.color("light", "on", {}) == list(sv.AMBER)
    assert sv.color("light", "off", {"rgb_color": [1, 2, 3]}) is None
    assert sv.color("climate", "heat", {"hvac_action": "heating"}) == list(sv.HEAT)
    assert sv.color("climate", "cool", {"hvac_action": "cooling"}) == list(sv.COOL)
    assert sv.color("alarm_control_panel", "armed_home", {}) == list(sv.ALARM)
    assert sv.color("switch", "on", {}) == list(sv.ACTIVE_BLUE)
    assert sv.color("switch", "unavailable", {}) is None


def test_message_satisfies_the_contract() -> None:
    msg = sv.message(
        "climate",
        "heat",
        {"hvac_action": "heating", "hvac_modes": ["heat", "off"], "temperature": 22},
        0,
        "Heating · → 22 °C",
        "mdi:thermostat",
        label,
    )
    assert codec.decode("state", codec.encode(msg)) == msg
    assert msg["on"] is True and msg["available"] is True
