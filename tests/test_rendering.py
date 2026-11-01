"""State messages rendered with Home Assistant's own translations."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.roundhouse import codec, icons, images, rendering

DOMAINS = {
    "light",
    "climate",
    "lock",
    "cover",
    "binary_sensor",
    "person",
    "switch",
    "sensor",
    "alarm_control_panel",
    "fan",
    "humidifier",
    "water_heater",
    "valve",
    "select",
}


async def render(
    hass: HomeAssistant, entity_id: str, card_icon: str | None = None
) -> dict[str, Any]:
    await hass.async_add_executor_job(icons.warm)
    translator = rendering.Translator(hass)
    await translator.async_load(DOMAINS, set())
    msg = rendering.render_state(hass, translator, entity_id, card_icon)
    assert codec.decode("state", codec.encode(msg)) == msg  # always valid contract JSON
    return msg


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (
            "en",
            {
                "light": "On · 80%",
                "lock": "Locked",
                "cover": "Open · 40%",
                "motion": "Detected",
                "person": "Home",
                "alarm": "Armed away",
                "switch": "Off",
                "gone": "Unavailable",
            },
        ),
        (
            "pl",
            {
                "light": "Włączono · 80%",
                "lock": "Zablokowano",
                "cover": "Otwarto · 40%",
                "motion": "Wykryto",
                "person": "W domu",
                "alarm": "Uzbrojony (poza domem)",
                "switch": "Wyłączono",
                "gone": "Niedostępny",
            },
        ),
    ],
)
async def test_state_text_in_two_languages(
    hass: HomeAssistant, language: str, expected: dict[str, str]
) -> None:
    hass.config.language = language
    hass.states.async_set("light.a", "on", {"brightness": 204})
    hass.states.async_set("lock.a", "locked")
    hass.states.async_set("cover.a", "open", {"current_position": 40})
    hass.states.async_set("binary_sensor.a", "on", {"device_class": "motion"})
    hass.states.async_set("person.a", "home")
    hass.states.async_set("alarm_control_panel.a", "armed_away")
    hass.states.async_set("switch.a", "off")
    hass.states.async_set("sensor.gone", "unavailable")
    got = {
        "light": (await render(hass, "light.a"))["text"],
        "lock": (await render(hass, "lock.a"))["text"],
        "cover": (await render(hass, "cover.a"))["text"],
        "motion": (await render(hass, "binary_sensor.a"))["text"],
        "person": (await render(hass, "person.a"))["text"],
        "alarm": (await render(hass, "alarm_control_panel.a"))["text"],
        "switch": (await render(hass, "switch.a"))["text"],
        "gone": (await render(hass, "sensor.gone"))["text"],
    }
    assert got == expected


@pytest.mark.parametrize(
    ("language", "text"),
    [("en", "Heating · 21.5 → 22 °C"), ("pl", "Grzanie · 21,5 → 22 °C")],
)
async def test_climate_text(hass: HomeAssistant, language: str, text: str) -> None:
    hass.config.language = language
    hass.states.async_set(
        "climate.hp",
        "heat",
        {"hvac_action": "heating", "current_temperature": 21.5, "temperature": 22},
    )
    assert (await render(hass, "climate.hp"))["text"] == text


async def test_missing_entity_is_unavailable(hass: HomeAssistant) -> None:
    msg = await render(hass, "light.nowhere")
    assert (msg["text"], msg["available"], msg["on"], msg["color"]) == (
        "Unavailable",
        False,
        False,
        None,
    )
    assert msg["icon"] == "mdi:lightbulb"


async def test_modes_are_value_and_translated_label_pairs(hass: HomeAssistant) -> None:
    hass.config.language = "pl"
    hass.states.async_set(
        "climate.hp",
        "heat",
        {
            "hvac_modes": ["heat", "off"],
            "preset_mode": "eco",
            "preset_modes": ["eco", "comfort"],
            "hvac_action": "heating",
        },
    )
    attrs = (await render(hass, "climate.hp"))["attributes"]
    assert attrs["hvac_modes"] == [
        {"value": "heat", "label": "Grzanie"},
        {"value": "off", "label": "Wyłączono"},
    ]
    assert attrs["preset_mode"] == {"value": "eco", "label": "Eko"}
    assert attrs["hvac_action"] == {"value": "heating", "label": "Grzanie"}
    hass.config.language = "en"
    attrs = (await render(hass, "climate.hp"))["attributes"]
    assert attrs["preset_modes"] == [
        {"value": "eco", "label": "Eco"},
        {"value": "comfort", "label": "Comfort"},
    ]


async def test_sensor_precision_comes_from_the_registry(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "sensor", "test", "t1", suggested_object_id="t1"
    )
    hass.states.async_set(entry.entity_id, "21.456", {"unit_of_measurement": "°C"})
    assert (await render(hass, entry.entity_id))["text"] == "21.46 °C"
    registry.async_update_entity_options(
        entry.entity_id, "sensor", {"display_precision": 1}
    )
    assert (await render(hass, entry.entity_id))["text"] == "21.5 °C"


async def test_timestamps_render_in_local_time(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Warsaw")
    hass.states.async_set(
        "sensor.when", "2026-10-31T10:30:00+00:00", {"device_class": "timestamp"}
    )
    assert (await render(hass, "sensor.when"))["text"] == "2026-10-31 11:30"
    hass.states.async_set("sensor.day", "2026-10-31", {"device_class": "date"})
    assert (await render(hass, "sensor.day"))["text"] == "2026-10-31"


async def test_icon_resolution_chain(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    hass.states.async_set("light.off", "off")
    hass.states.async_set("light.on", "on")
    assert (await render(hass, "light.off"))[
        "icon"
    ] == "mdi:lightbulb-off"  # translated
    assert (await render(hass, "light.on"))["icon"] == "mdi:lightbulb"

    hass.states.async_set("light.attr", "on", {"icon": "mdi:fire"})
    assert (await render(hass, "light.attr"))["icon"] == "mdi:fire"

    entry = registry.async_get_or_create(
        "light", "test", "r1", suggested_object_id="reg"
    )
    hass.states.async_set(entry.entity_id, "on", {"icon": "mdi:fire"})
    registry.async_update_entity(entry.entity_id, icon="mdi:lamp")
    assert (await render(hass, entry.entity_id))["icon"] == "mdi:lamp"
    assert (await render(hass, entry.entity_id, "mdi:ceiling-light"))[
        "icon"
    ] == "mdi:ceiling-light"

    # Anything outside the bundled font falls back.
    assert (await render(hass, "light.on", "custom:thing"))["icon"] == icons.FALLBACK
    assert (await render(hass, "scene.x"))["icon"] == "mdi:palette"  # domain default


async def test_device_class_icons(hass: HomeAssistant) -> None:
    hass.states.async_set("cover.g", "open", {"device_class": "garage"})
    assert (await render(hass, "cover.g"))["icon"] == "mdi:garage-open"


async def test_color_and_flags(hass: HomeAssistant) -> None:
    hass.states.async_set("light.c", "on", {"rgb_color": [255, 0, 0]})
    msg = await render(hass, "light.c")
    assert (msg["on"], msg["color"]) == (True, [255, 0, 0])
    hass.states.async_set("light.c", "off")
    msg = await render(hass, "light.c")
    assert (msg["on"], msg["color"], msg["available"]) == (False, None, True)


async def test_entity_domains_and_platforms(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", "demo", "u1", suggested_object_id="s", translation_key="level"
    )
    domains, platforms = rendering.entity_domains(hass, {"sensor.s", "light.x"})
    assert domains == {"sensor", "light"} and platforms == {"demo"}


async def test_the_guard_catches_work_in_the_event_loop(hass: HomeAssistant) -> None:
    """Rasterizing in the loop fails; the executor is fine."""
    with pytest.raises(AssertionError, match="ran in the event loop"):
        icons.mask("mdi:lightbulb", 16)
    with pytest.raises(AssertionError, match="ran in the event loop"):
        images.encode_image(b"x", "gray4", (2, 2))
    assert await hass.async_add_executor_job(icons.mask, "mdi:lightbulb", 16)
