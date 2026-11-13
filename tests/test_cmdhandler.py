"""Commands from a device: allowlist, checks, repeats, results."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_mock_service,
)

from custom_components.roundhouse import cmdhandler
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS

from .conftest import announce, vector
from .helpers import PREFIX, advance, config, setup

CLIMATE_ATTRS = {
    "hvac_modes": ["heat", "off", "cool"],
    "min_temp": 7,
    "max_temp": 30,
    "preset_modes": ["eco", "comfort"],
}


def home_cards() -> list[dict[str, Any]]:
    return [
        {"entity_id": "light.l0"},
        {"entity_id": "lock.door"},
        {"entity_id": "scene.s"},
        {"entity_id": "sensor.temp"},
        {"entity_id": "number.n"},
        {
            "entity_id": "climate.hp",
            "controls": [
                {"type": "hvac_mode", "values": ["heat", "off"]},
                {"type": "target_temperature"},
            ],
        },
    ]


@pytest.fixture
async def ready(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> Any:
    """A set-up device whose views hold a few entities."""
    hass.states.async_set("light.l0", "off")
    hass.states.async_set("lock.door", "locked")
    hass.states.async_set("scene.s", "unknown")
    hass.states.async_set("sensor.temp", "21")
    hass.states.async_set("number.n", "3", {"min": 0, "max": 10})
    hass.states.async_set("climate.hp", "heat", CLIMATE_ATTRS)
    hass.states.async_set("switch.hidden", "off")  # not on any view
    entry = await setup(hass, tender_profile, config(("home", home_cards())))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    mqtt_mock.async_publish.reset_mock()
    return hass.data[DOMAIN][entry.entry_id]


def send(hass: HomeAssistant, cmd: dict[str, Any] | bytes) -> None:
    body = cmd if isinstance(cmd, bytes) else json.dumps(cmd)
    async_fire_mqtt_message(hass, PREFIX + "cmd", body, qos=1)


async def ask(hass: HomeAssistant, mqtt_mock: Any, cmd: dict[str, Any]) -> str | None:
    """Send a command and return the result published for its request ID."""
    send(hass, cmd)
    await hass.async_block_till_done()
    got = [
        json.loads(c.args[1])["result"]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result" and json.loads(c.args[1])["req"] == cmd["req"]
    ]
    return got[-1] if got else None


def entity_cmd(req: str, entity: str, action: str, **extra: Any) -> dict[str, Any]:
    return {"req": req, "entity_id": entity, "action": action, **extra}


async def test_an_allowed_command_calls_the_service_and_answers_ok(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "light", "toggle")
    assert await ask(hass, mqtt_mock, entity_cmd("r1", "light.l0", "toggle")) == "ok"
    assert [c.data for c in calls] == [{"entity_id": "light.l0"}]
    reply = [
        c
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
    ][-1]
    assert tuple(reply.args[1:4]) == (b'{"req":"r1","result":"ok"}', 1, False)


async def test_service_data_is_only_what_was_validated(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "climate", "set_temperature")
    cmd = entity_cmd("r1", "climate.hp", "set_temperature", data={"temperature": 22.5})
    assert await ask(hass, mqtt_mock, cmd) == "ok"
    assert calls[0].data == {"entity_id": "climate.hp", "temperature": 22.5}


@pytest.mark.parametrize(
    "cmd",
    [
        entity_cmd("d1", "switch.hidden", "toggle"),  # in HA, not on the device
        entity_cmd("d2", "light.nowhere", "toggle"),
        entity_cmd("d3", "sensor.temp", "toggle"),  # no actions on a sensor
        entity_cmd("d4", "light.l0", "set_percentage", data={"percentage": 5}),
        entity_cmd("d5", "light.l0", "reload"),
        {"req": "d6", "ack": "a1b2"},
        {"req": "d7", "alert": "a1b2", "action_id": "open"},
    ],
)
async def test_everything_else_is_denied(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, cmd: dict[str, Any]
) -> None:
    calls = async_mock_service(hass, "light", "toggle") + async_mock_service(
        hass, "switch", "toggle"
    )
    assert await ask(hass, mqtt_mock, cmd) == "denied"
    assert calls == []


@pytest.mark.parametrize(
    ("cmd", "reason"),
    [
        (
            entity_cmd("i1", "climate.hp", "set_hvac_mode", data={"hvac_mode": "dry"}),
            "entity list",
        ),
        # "cool" is in the entity's list but not enabled on the tile.
        (
            entity_cmd("i2", "climate.hp", "set_hvac_mode", data={"hvac_mode": "cool"}),
            "tile",
        ),
        (entity_cmd("i3", "number.n", "set_value", data={"value": 11}), "range"),
        (entity_cmd("i4", "number.n", "set_value", data={"value": "5"}), "type"),
        (
            entity_cmd("i5", "climate.hp", "set_temperature", data={"temperature": 99}),
            "range",
        ),
        (
            entity_cmd("i6", "light.l0", "toggle", data={"entity_id": "light.other"}),
            "smuggled",
        ),
    ],
)
async def test_bad_values_are_invalid_and_make_no_call(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, cmd: dict[str, Any], reason: str
) -> None:
    calls = [
        *async_mock_service(hass, "climate", "set_hvac_mode"),
        *async_mock_service(hass, "climate", "set_temperature"),
        *async_mock_service(hass, "number", "set_value"),
        *async_mock_service(hass, "light", "toggle"),
    ]
    assert await ask(hass, mqtt_mock, cmd) == "invalid", reason
    assert calls == []


async def test_a_valid_mode_inside_the_tile_controls_passes(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "climate", "set_hvac_mode")
    cmd = entity_cmd("m1", "climate.hp", "set_hvac_mode", data={"hvac_mode": "off"})
    assert await ask(hass, mqtt_mock, cmd) == "ok"
    assert calls[0].data["hvac_mode"] == "off"


async def test_a_repeated_request_id_is_answered_without_a_second_call(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "light", "toggle")
    cmd = entity_cmd("r1", "light.l0", "toggle")
    assert await ask(hass, mqtt_mock, cmd) == "ok"
    assert await ask(hass, mqtt_mock, cmd) == "ok"
    assert len(calls) == 1
    results = [
        c
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
    ]
    assert len(results) == 2  # the device still gets an answer each time


async def test_a_repeated_failure_repeats_the_failure(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    attempts = 0

    async def fail(call: ServiceCall) -> None:
        nonlocal attempts
        attempts += 1
        raise HomeAssistantError("lamp is broken")

    hass.services.async_register("light", "toggle", fail)
    cmd = entity_cmd("f1", "light.l0", "toggle")
    assert await ask(hass, mqtt_mock, cmd) == "lamp is broken"
    assert await ask(hass, mqtt_mock, cmd) == "lamp is broken"
    assert attempts == 1


async def test_a_duplicate_while_the_first_runs_shares_its_result(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    release = asyncio.Event()
    attempts = 0

    async def slow(call: ServiceCall) -> None:
        nonlocal attempts
        attempts += 1
        await release.wait()

    hass.services.async_register("light", "toggle", slow)
    cmd = entity_cmd("s1", "light.l0", "toggle")
    send(hass, cmd)
    await asyncio.sleep(0)
    send(hass, cmd)
    await asyncio.sleep(0)
    release.set()
    await hass.async_block_till_done()
    assert attempts == 1
    replies = [
        json.loads(c.args[1])
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
    ]
    assert replies == [{"req": "s1", "result": "ok"}] * 2


async def test_only_the_last_32_request_ids_are_remembered(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "light", "toggle")
    for i in range(33):
        assert (
            await ask(hass, mqtt_mock, entity_cmd(f"q{i}", "light.l0", "toggle"))
            == "ok"
        )
    assert len(calls) == 33
    await ask(
        hass, mqtt_mock, entity_cmd("q32", "light.l0", "toggle")
    )  # still remembered
    assert len(calls) == 33
    await ask(
        hass, mqtt_mock, entity_cmd("q1", "light.l0", "toggle")
    )  # still within 32
    assert len(calls) == 33
    await ask(hass, mqtt_mock, entity_cmd("q0", "light.l0", "toggle"))  # fell out
    assert len(calls) == 34


@pytest.mark.parametrize("confirmed", [None, False])
async def test_a_sensitive_action_needs_confirmation(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, confirmed: bool | None
) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    extra = {} if confirmed is None else {"confirmed": confirmed}
    assert await ask(
        hass, mqtt_mock, entity_cmd("u1", "lock.door", "unlock", **extra)
    ) == ("needs_confirmation")
    assert calls == []
    assert (
        await ask(
            hass, mqtt_mock, entity_cmd("u2", "lock.door", "unlock", confirmed=True)
        )
        == "ok"
    )
    assert len(calls) == 1


async def test_locking_needs_no_confirmation(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    assert await ask(hass, mqtt_mock, entity_cmd("l1", "lock.door", "lock")) == "ok"
    assert len(calls) == 1


async def test_an_invalid_value_is_reported_before_a_confirmation_is_asked(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    cmd = entity_cmd("x1", "lock.door", "unlock", data={"code": "1234"})
    assert await ask(hass, mqtt_mock, cmd) == "invalid"


async def test_a_slow_service_times_out(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    cancelled = False

    async def hang(call: ServiceCall) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled = True
            raise

    hass.services.async_register("light", "toggle", hang)
    with patch.object(cmdhandler, "COMMAND_TIMEOUT", 0.05):
        assert (
            await ask(hass, mqtt_mock, entity_cmd("t1", "light.l0", "toggle"))
            == "timeout"
        )
    assert cancelled
    assert cmdhandler.COMMAND_TIMEOUT == 10.0  # the real cap


async def test_a_missing_service_reports_an_error_text(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    result = await ask(hass, mqtt_mock, entity_cmd("e1", "light.l0", "toggle"))
    assert result is not None and "light.toggle" in result and len(result) <= 200


async def test_a_service_error_is_shortened(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    async def boom(call: ServiceCall) -> None:
        raise HomeAssistantError("x" * 1000)

    hass.services.async_register("light", "toggle", boom)
    result = await ask(hass, mqtt_mock, entity_cmd("e2", "light.l0", "toggle"))
    assert result == "x" * cmdhandler.MAX_ERROR_LENGTH


async def test_an_unexpected_exception_is_reported_not_raised(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    async def bug(call: ServiceCall) -> None:
        raise ValueError("bad value")

    hass.services.async_register("light", "toggle", bug)
    result = await ask(hass, mqtt_mock, entity_cmd("e3", "light.l0", "toggle"))
    assert result == "ValueError: bad value"


async def test_a_malformed_command_with_a_request_id_is_invalid(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    send(hass, {"req": "bad1", "entity_id": "light.l0"})  # no action
    await hass.async_block_till_done()
    replies = [
        json.loads(c.args[1])
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
    ]
    assert replies == [{"req": "bad1", "result": "invalid"}]


@pytest.mark.parametrize(
    "junk", [b"{not json", b"[]", b'{"entity_id":"light.l0"}', b"\xff\xfe"]
)
async def test_garbage_without_a_request_id_gets_no_answer(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, junk: bytes
) -> None:
    send(hass, junk)
    await hass.async_block_till_done()
    assert not [
        c
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
    ]


async def test_every_command_is_logged_at_debug_level(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, caplog: pytest.LogCaptureFixture
) -> None:
    async_mock_service(hass, "light", "toggle")
    caplog.set_level(logging.DEBUG, "custom_components.roundhouse.cmdhandler")
    await ask(hass, mqtt_mock, entity_cmd("log1", "light.l0", "toggle"))
    text = caplog.text
    assert "Command from tender01" in text and "log1" in text
    assert "Result of log1 on tender01: ok" in text


async def test_denied_commands_log_at_a_limited_rate(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, "custom_components.roundhouse.cmdhandler")
    for i in range(5):
        await ask(hass, mqtt_mock, entity_cmd(f"n{i}", "switch.hidden", "toggle"))
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "Refused" in r.message
    ]
    assert len(warnings) == 1
    assert "switch.hidden is not on the device" in warnings[0].message


async def test_commands_are_denied_while_the_device_is_in_meta_only_mode(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    calls = async_mock_service(hass, "light", "toggle")
    announce(hass, "tender01", vector("announce", "major-mismatch")["payload"])
    await hass.async_block_till_done()
    assert (
        await ask(hass, mqtt_mock, entity_cmd("mo1", "light.l0", "toggle")) == "denied"
    )
    assert calls == []


async def test_an_entity_on_two_tiles_passes_if_any_tile_allows_the_value(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("climate.hp", "heat", CLIMATE_ATTRS)
    narrow = {
        "entity_id": "climate.hp",
        "controls": [{"type": "hvac_mode", "values": ["off"]}],
    }
    wide = {
        "entity_id": "climate.hp",
        "controls": [{"type": "hvac_mode", "values": ["heat", "cool"]}],
    }
    entry = await setup(hass, tender_profile, config(("home", [narrow, wide])))
    assert entry.entry_id in hass.data[DOMAIN]
    calls = async_mock_service(hass, "climate", "set_hvac_mode")
    cmd = entity_cmd("two1", "climate.hp", "set_hvac_mode", data={"hvac_mode": "cool"})
    assert await ask(hass, mqtt_mock, cmd) == "ok"
    assert len(calls) == 1
    cmd = entity_cmd("two2", "climate.hp", "set_hvac_mode", data={"hvac_mode": "dry"})
    assert await ask(hass, mqtt_mock, cmd) == "invalid"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_command_is_answered_within_the_latency_budget(
    hass: HomeAssistant, mqtt_mock: Any, ready: Any
) -> None:
    """cmd to result is the service time plus at most 100 ms (instant here)."""
    async_mock_service(hass, "light", "toggle")
    started = time.perf_counter()
    assert await ask(hass, mqtt_mock, entity_cmd("lat1", "light.l0", "toggle")) == "ok"
    assert time.perf_counter() - started < 0.1


def test_the_rate_limiter_counts_what_it_suppresses() -> None:
    now = [0.0]
    limiter = cmdhandler.RateLimiter(60, lambda: now[0])
    assert limiter.allow("a") == 0
    assert limiter.allow("a") is None
    assert limiter.allow("a") is None
    assert limiter.allow("b") == 0  # another key has its own budget
    now[0] = 61
    assert limiter.allow("a") == 2
    assert limiter.allow("a") is None
