"""An unloaded device publishes nothing more, and its work in progress stops."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.roundhouse import lovelace_io
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS
from custom_components.roundhouse.publisher import RETRY_SECONDS
from custom_components.roundhouse.statesync import StateSync

from .test_views import advance, config, save, setup


class Stuck:
    """A coroutine stand-in that never returns and records its cancellation."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def __call__(self, *_args: Any) -> Any:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def test_a_send_that_fails_after_stop_is_not_retried(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    publisher = hass.data[DOMAIN][entry.entry_id].publisher

    def fail(*_args: Any, **_kwargs: Any) -> None:
        publisher.async_stop()  # the entry unloads while the send is in flight
        raise HomeAssistantError("MQTT broker is away")

    mqtt_mock.async_publish.side_effect = fail
    assert await publisher.async_publish("state/a.b", b"1") is False
    assert publisher._retry is None

    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await advance(hass, RETRY_SECONDS + 1)
    assert not mqtt_mock.async_publish.call_args_list


async def test_a_stopped_publisher_sends_nothing(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    publisher = hass.data[DOMAIN][entry.entry_id].publisher
    publisher.async_stop()
    mqtt_mock.async_publish.reset_mock()
    assert await publisher.async_publish("state/a.b", b"1") is False
    await publisher.async_clear("meta")
    await publisher.async_resync()
    assert not mqtt_mock.async_publish.call_args_list


async def test_unloading_cancels_a_dashboard_refresh_in_progress(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", [])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    stuck = Stuck()
    with patch.object(lovelace_io, "async_load_dashboard", stuck):
        await save(hass, config(("home", [{"type": "tile", "entity": "light.l0"}])))
        # Fire the debounce without waiting on the refresh, which never ends.
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=lovelace_io.UPDATE_WAIT + 1)
        )
        async with asyncio.timeout(5):
            await stuck.entered.wait()
        assert await hass.config_entries.async_unload(entry.entry_id)
        async with asyncio.timeout(5):
            await hass.async_block_till_done()
    assert stuck.cancelled.is_set()


async def test_unloading_cancels_a_state_publish_in_progress(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(
        hass, tender_profile, config(("home", [{"type": "tile", "entity": "light.l0"}]))
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    stuck = Stuck()
    with patch.object(StateSync, "_publish", stuck):
        hass.states.async_set("light.l0", "off")
        async with asyncio.timeout(5):
            await stuck.entered.wait()
        assert await hass.config_entries.async_unload(entry.entry_id)
        async with asyncio.timeout(5):
            await hass.async_block_till_done()
    assert stuck.cancelled.is_set()
