"""The command table and the value checks."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import commands as cm

CLIMATE = {
    "min_temp": 7,
    "max_temp": 30,
    "hvac_modes": ["heat", "off", "cool"],
    "preset_modes": ["eco", "comfort"],
    "fan_modes": ["auto", "low"],
    "swing_modes": ["off", "on"],
    "min_humidity": 30,
    "max_humidity": 70,
}


def build(
    entity: str,
    action: str,
    data: dict[str, Any] | None = None,
    attrs: dict[str, Any] | None = None,
    controls: list[dict[str, Any]] | None = None,
) -> cm.Call:
    return cm.build(entity, action, data or {}, attrs or {}, controls or [])


@pytest.mark.parametrize(
    ("entity", "action", "data", "attrs", "expected"),
    [
        ("light.a", "toggle", {}, {}, {}),
        ("light.a", "turn_off", {}, {}, {}),
        ("light.a", "turn_on", {}, {}, {}),
        ("light.a", "turn_on", {"brightness": 128}, {}, {"brightness": 128}),
        ("light.a", "turn_on", {"brightness": 0}, {}, {"brightness": 0}),
        (
            "light.a",
            "turn_on",
            {"color_temp_kelvin": 3000},
            {"min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500},
            {"color_temp_kelvin": 3000},
        ),
        ("switch.a", "toggle", {}, {}, {}),
        ("input_boolean.a", "toggle", {}, {}, {}),
        ("fan.a", "toggle", {}, {}, {}),
        ("fan.a", "set_percentage", {"percentage": 40}, {}, {"percentage": 40}),
        (
            "fan.a",
            "set_preset_mode",
            {"preset_mode": "eco"},
            {"preset_modes": ["eco"]},
            {"preset_mode": "eco"},
        ),
        ("cover.a", "open_cover", {}, {}, {}),
        ("cover.a", "stop_cover", {}, {}, {}),
        ("cover.a", "set_cover_position", {"position": 25}, {}, {"position": 25}),
        (
            "climate.a",
            "set_temperature",
            {"temperature": 22.5},
            CLIMATE,
            {"temperature": 22.5},
        ),
        (
            "climate.a",
            "set_temperature",
            {"target_temp_low": 19, "target_temp_high": 24},
            CLIMATE,
            {"target_temp_low": 19, "target_temp_high": 24},
        ),
        (
            "climate.a",
            "set_hvac_mode",
            {"hvac_mode": "heat"},
            CLIMATE,
            {"hvac_mode": "heat"},
        ),
        (
            "climate.a",
            "set_fan_mode",
            {"fan_mode": "low"},
            CLIMATE,
            {"fan_mode": "low"},
        ),
        (
            "climate.a",
            "set_preset_mode",
            {"preset_mode": "eco"},
            CLIMATE,
            {"preset_mode": "eco"},
        ),
        (
            "climate.a",
            "set_swing_mode",
            {"swing_mode": "on"},
            CLIMATE,
            {"swing_mode": "on"},
        ),
        ("climate.a", "set_humidity", {"humidity": 55}, CLIMATE, {"humidity": 55}),
        ("climate.a", "turn_on", {}, CLIMATE, {}),
        (
            "water_heater.a",
            "set_temperature",
            {"temperature": 55},
            {"min_temp": 30, "max_temp": 70},
            {"temperature": 55},
        ),
        (
            "water_heater.a",
            "set_operation_mode",
            {"operation_mode": "eco"},
            {"operation_list": ["eco"]},
            {"operation_mode": "eco"},
        ),
        (
            "humidifier.a",
            "set_humidity",
            {"humidity": 50},
            {"min_humidity": 30, "max_humidity": 80},
            {"humidity": 50},
        ),
        (
            "humidifier.a",
            "set_mode",
            {"mode": "auto"},
            {"available_modes": ["auto"]},
            {"mode": "auto"},
        ),
        ("number.a", "set_value", {"value": 5}, {"min": 0, "max": 10}, {"value": 5}),
        (
            "input_number.a",
            "set_value",
            {"value": 2.5},
            {"min": 0, "max": 10},
            {"value": 2.5},
        ),
        (
            "select.a",
            "select_option",
            {"option": "b"},
            {"options": ["a", "b"]},
            {"option": "b"},
        ),
        (
            "input_select.a",
            "select_option",
            {"option": "a"},
            {"options": ["a"]},
            {"option": "a"},
        ),
        ("valve.a", "set_valve_position", {"position": 60}, {}, {"position": 60}),
        ("valve.a", "stop_valve", {}, {}, {}),
        ("lock.a", "lock", {}, {}, {}),
        ("lock.a", "unlock", {}, {}, {}),
        ("lock.a", "open", {}, {}, {}),
        ("alarm_control_panel.a", "alarm_arm_away", {}, {}, {}),
        ("alarm_control_panel.a", "alarm_disarm", {}, {}, {}),
        ("scene.a", "turn_on", {}, {}, {}),
        ("script.a", "turn_on", {}, {}, {}),
        ("button.a", "press", {}, {}, {}),
        ("input_button.a", "press", {}, {}, {}),
    ],
)
def test_allowed_actions_become_service_calls(
    entity: str,
    action: str,
    data: dict[str, Any],
    attrs: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    call = build(entity, action, data, attrs)
    assert (call.domain, call.service) == (entity.split(".")[0], action)
    assert call.data == {"entity_id": entity, **expected}


@pytest.mark.parametrize(
    ("entity", "action"),
    [
        ("sensor.a", "anything"),
        ("sensor.a", "toggle"),
        ("binary_sensor.a", "turn_on"),
        ("person.a", "toggle"),
        ("light.a", "set_percentage"),
        ("light.a", "reload"),
        ("switch.a", "turn_on"),
        ("cover.a", "toggle"),
        ("lock.a", "toggle"),
        ("climate.a", "set_fan_speed"),
        ("script.a", "toggle"),
        ("scene.a", "press"),
        ("button.a", "turn_on"),
        ("homeassistant.x", "restart"),
        ("automation.a", "trigger"),
        ("alarm_control_panel.a", "alarm_trigger"),
        ("number.a", "increment"),
    ],
)
def test_other_actions_are_denied(entity: str, action: str) -> None:
    with pytest.raises(cm.Denied):
        build(entity, action)


@pytest.mark.parametrize(
    ("entity", "action", "data", "attrs"),
    [
        (
            "climate.a",
            "set_hvac_mode",
            {"hvac_mode": "dry"},
            CLIMATE,
        ),  # not in the entity list
        ("climate.a", "set_hvac_mode", {"hvac_mode": 1}, CLIMATE),
        ("climate.a", "set_hvac_mode", {}, CLIMATE),
        (
            "climate.a",
            "set_hvac_mode",
            {"hvac_mode": "heat"},
            {},
        ),  # entity offers no list
        ("climate.a", "set_preset_mode", {"preset_mode": "away"}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": 31}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": 6.9}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": True}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": "22"}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": float("nan")}, CLIMATE),
        ("climate.a", "set_temperature", {"temperature": float("inf")}, CLIMATE),
        ("climate.a", "set_temperature", {}, CLIMATE),
        (
            "climate.a",
            "set_temperature",
            {"temperature": 20, "target_temp_low": 18},
            CLIMATE,
        ),
        ("climate.a", "set_temperature", {"target_temp_low": 18}, CLIMATE),
        (
            "climate.a",
            "set_temperature",
            {"target_temp_low": 25, "target_temp_high": 20},
            CLIMATE,
        ),
        (
            "climate.a",
            "set_temperature",
            {"target_temp_low": 5, "target_temp_high": 20},
            CLIMATE,
        ),
        ("climate.a", "set_humidity", {"humidity": 80}, CLIMATE),
        ("climate.a", "set_humidity", {"humidity": 20}, CLIMATE),
        ("light.a", "turn_on", {"brightness": 256}, {}),
        ("light.a", "turn_on", {"brightness": -1}, {}),
        ("light.a", "turn_on", {"brightness": 1.5}, {}),
        (
            "light.a",
            "turn_on",
            {"color_temp_kelvin": 1500},
            {"min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500},
        ),
        (
            "light.a",
            "turn_on",
            {"rgb_color": [1, 2, 3]},
            {},
        ),  # a key the contract does not know
        ("light.a", "toggle", {"brightness": 5}, {}),
        ("fan.a", "set_percentage", {"percentage": 101}, {}),
        ("fan.a", "set_percentage", {"percentage": 50.5}, {}),
        (
            "fan.a",
            "set_preset_mode",
            {"preset_mode": "turbo"},
            {"preset_modes": ["eco"]},
        ),
        ("cover.a", "set_cover_position", {"position": 150}, {}),
        (
            "cover.a",
            "open_cover",
            {"entity_id": "cover.other"},
            {},
        ),  # no smuggled targets
        ("number.a", "set_value", {"value": 11}, {"min": 0, "max": 10}),
        ("number.a", "set_value", {"value": -1}, {"min": 0, "max": 10}),
        ("number.a", "set_value", {"value": 101}, {}),  # HA's default range
        ("number.a", "set_value", {"value": "5"}, {"min": 0, "max": 10}),
        ("select.a", "select_option", {"option": "z"}, {"options": ["a"]}),
        (
            "water_heater.a",
            "set_temperature",
            {"temperature": 90},
            {"min_temp": 30, "max_temp": 70},
        ),
        (
            "water_heater.a",
            "set_operation_mode",
            {"operation_mode": "x"},
            {"operation_list": ["eco"]},
        ),
        ("humidifier.a", "set_mode", {"mode": "x"}, {"available_modes": ["auto"]}),
        ("valve.a", "set_valve_position", {"position": -5}, {}),
        ("lock.a", "unlock", {"code": "1234"}, {}),  # no credentials over MQTT
        ("alarm_control_panel.a", "alarm_disarm", {"code": "1234"}, {}),
        ("scene.a", "turn_on", {"transition": 5}, {}),
    ],
)
def test_bad_values_are_invalid(
    entity: str, action: str, data: dict[str, Any], attrs: dict[str, Any]
) -> None:
    with pytest.raises(cm.Invalid):
        build(entity, action, data, attrs)


def test_a_mode_must_also_be_enabled_on_the_tile() -> None:
    controls = [{"type": "hvac_mode", "values": ["heat", "off"]}]
    assert build("climate.a", "set_hvac_mode", {"hvac_mode": "heat"}, CLIMATE, controls)
    with pytest.raises(cm.Invalid, match="not enabled on the tile"):
        build(
            "climate.a", "set_hvac_mode", {"hvac_mode": "cool"}, CLIMATE, controls
        )  # in the entity list


def test_tile_controls_restrict_only_the_modes_they_name() -> None:
    controls = [
        {"type": "hvac_mode", "values": ["heat"]},
        {"type": "target_temperature"},
    ]
    assert build(
        "climate.a", "set_preset_mode", {"preset_mode": "eco"}, CLIMATE, controls
    )
    assert build("climate.a", "set_temperature", {"temperature": 20}, CLIMATE, controls)
    # A control without a value list restricts nothing.
    assert build(
        "climate.a",
        "set_hvac_mode",
        {"hvac_mode": "cool"},
        CLIMATE,
        [{"type": "hvac_mode"}],
    )


@pytest.mark.parametrize(
    ("action", "control", "attrs", "data"),
    [
        ("set_preset_mode", "preset_mode", CLIMATE, {"preset_mode": "comfort"}),
        ("set_fan_mode", "fan_mode", CLIMATE, {"fan_mode": "low"}),
        ("set_swing_mode", "swing_mode", CLIMATE, {"swing_mode": "on"}),
    ],
)
def test_every_climate_mode_checks_its_control(
    action: str, control: str, attrs: dict[str, Any], data: dict[str, Any]
) -> None:
    with pytest.raises(cm.Invalid, match="tile"):
        build("climate.a", action, data, attrs, [{"type": control, "values": []}])


def test_other_domains_check_their_controls() -> None:
    with pytest.raises(cm.Invalid, match="tile"):
        build(
            "select.a",
            "select_option",
            {"option": "b"},
            {"options": ["a", "b"]},
            [{"type": "select", "values": ["a"]}],
        )
    with pytest.raises(cm.Invalid, match="tile"):
        build(
            "fan.a",
            "set_preset_mode",
            {"preset_mode": "eco"},
            {"preset_modes": ["eco"]},
            [{"type": "fan_preset_mode", "values": []}],
        )
    with pytest.raises(cm.Invalid, match="tile"):
        build(
            "humidifier.a",
            "set_mode",
            {"mode": "auto"},
            {"available_modes": ["auto"]},
            [{"type": "humidifier_mode", "values": []}],
        )
    with pytest.raises(cm.Invalid, match="tile"):
        build(
            "water_heater.a",
            "set_operation_mode",
            {"operation_mode": "eco"},
            {"operation_list": ["eco"]},
            [{"type": "operation_mode", "values": []}],
        )


def test_confirmation_set() -> None:
    assert cm.needs_confirmation("lock", "unlock")
    assert cm.needs_confirmation("lock", "open")
    assert cm.needs_confirmation("alarm_control_panel", "alarm_disarm")
    assert not cm.needs_confirmation("lock", "lock")
    assert not cm.needs_confirmation("alarm_control_panel", "alarm_arm_away")
    assert not cm.needs_confirmation("light", "toggle")


def test_the_table_matches_the_spec_domains() -> None:
    assert set(cm.TABLE) == {
        "light",
        "switch",
        "input_boolean",
        "fan",
        "cover",
        "climate",
        "water_heater",
        "humidifier",
        "number",
        "input_number",
        "select",
        "input_select",
        "valve",
        "lock",
        "alarm_control_panel",
        "scene",
        "script",
        "button",
        "input_button",
    }
    assert cm.allowed("lock", "open") and not cm.allowed("sensor", "x")
