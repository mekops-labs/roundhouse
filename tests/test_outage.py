"""A broker outage never loses an update or leaves a stale value behind."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.roundhouse import lovelace_io
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS
from custom_components.roundhouse.publisher import RETRY_SECONDS

from .test_views import PREFIX, advance, config, save, setup


def cards(*entities: str) -> list[dict[str, Any]]:
    return [{"type": "tile", "entity": e} for e in entities]


def texts(mqtt_mock: Any, topic: str) -> list[str]:
    return [
        json.loads(c.args[1])["text"]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + topic and c.args[1]
    ]


async def go_down(mqtt_mock: Any, error: Exception | None = None) -> None:
    mqtt_mock.async_publish.side_effect = error or HomeAssistantError(
        "MQTT broker is away"
    )


async def come_back(hass: HomeAssistant, mqtt_mock: Any) -> None:
    mqtt_mock.async_publish.side_effect = None
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_an_update_during_an_outage_is_sent_when_the_broker_returns(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    assert texts(mqtt_mock, "state/light.l0") == ["On"]

    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await go_down(mqtt_mock)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    mqtt_mock.async_publish.reset_mock()  # forget the failed attempts

    await come_back(hass, mqtt_mock)
    # The reconnect sends the new value, not the one published before the outage.
    assert texts(mqtt_mock, "state/light.l0") == ["Off"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_reconnect_while_the_broker_still_fails_keeps_the_update(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A flapping connection: the resync fails too, and nothing is lost or raised."""
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await go_down(mqtt_mock)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)  # up, but sends still fail
    await hass.async_block_till_done(wait_background_tasks=True)
    assert "state/light.l0" in publisher._unsent and publisher._retry is not None
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RETRY_SECONDS + 1)
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert texts(mqtt_mock, "state/light.l0") == ["Off"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_failed_send_does_not_raise_or_log_an_error(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    await go_down(mqtt_mock)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    assert "state/light.l0" in hass.data[DOMAIN][entry.entry_id].publisher.owned
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert "Not sent, will retry" in caplog.text
    await advance(hass, STALE_SETTLE_SECONDS + 1)


@pytest.mark.parametrize("error", [HomeAssistantError("down"), TimeoutError()])
async def test_a_timer_retries_without_a_reconnect_event(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    error: Exception,
) -> None:
    hass.states.async_set("light.l0", "on")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    await go_down(mqtt_mock, error)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RETRY_SECONDS + 1)
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert texts(mqtt_mock, "state/light.l0") == ["Off"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_retry_keeps_trying_while_the_broker_is_away(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await go_down(mqtt_mock)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    for _ in range(3):  # three retries, all failing
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=RETRY_SECONDS + 1)
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert publisher._unsent  # still waiting, and a timer is armed again
        assert publisher._retry is not None
    mqtt_mock.async_publish.side_effect = None
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RETRY_SECONDS + 10)
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not publisher._unsent
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_same_payload_is_sent_again_after_a_failure(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await go_down(mqtt_mock)
    assert (
        await publisher.async_publish("state/a.b", b"1") is False
    )  # failed, but wanted
    assert "state/a.b" in publisher.owned
    mqtt_mock.async_publish.side_effect = None
    # Unchanged is skipped only once the broker has it.
    assert await publisher.async_publish("state/a.b", b"1") is True
    assert await publisher.async_publish("state/a.b", b"1") is False
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_failed_clear_is_retried(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    hass.states.async_set("light.l1", "on")
    entry = await setup(
        hass, tender_profile, config(("home", cards("light.l0", "light.l1")))
    )
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await go_down(mqtt_mock)
    await save(hass, config(("home", cards("light.l0"))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert "state/light.l1" not in publisher.owned  # no longer ours
    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RETRY_SECONDS + 30)
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    cleared = [
        c.args[0] for c in mqtt_mock.async_publish.call_args_list if c.args[1] == b""
    ]
    assert PREFIX + "state/light.l1" in cleared
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_topic_published_again_cancels_its_pending_clear(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await publisher.async_publish("state/a.b", b"1")
    await go_down(mqtt_mock)
    await publisher.async_clear("state/a.b")
    assert "state/a.b" in publisher._unsent_clear
    await publisher.async_publish("state/a.b", b"2")
    assert "state/a.b" not in publisher._unsent_clear
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_an_alert_raised_during_an_outage_reaches_the_device(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    device = hass.data[DOMAIN][entry.entry_id]
    await go_down(mqtt_mock)
    alert_id = await device.alerts.async_add(title="t", message="m")
    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert PREFIX + f"alert/{alert_id}" in {
        c.args[0] for c in mqtt_mock.async_publish.call_args_list
    }
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_command_result_that_cannot_be_sent_is_dropped_quietly(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass.states.async_set("light.l0", "on")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await go_down(mqtt_mock)
    async_fire_mqtt_message(
        hass,
        PREFIX + "cmd",
        json.dumps({"req": "x1", "entity_id": "light.l0", "action": "toggle"}),
        qos=1,
    )
    await hass.async_block_till_done()
    assert "Result of x1 not sent" in caplog.text
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_unloading_cancels_the_retry_timer(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    await go_down(mqtt_mock)
    hass.states.async_set("light.l0", "off")
    await hass.async_block_till_done()
    assert publisher._retry is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert publisher._retry is None
