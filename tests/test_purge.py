"""A removed device's retained topics are cleared, even after a broker outage."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.roundhouse import purge
from custom_components.roundhouse.publisher import Publisher

from .conftest import make_entry
from .test_device import PREFIX, _settle, _setup, published


@pytest.fixture
def runs() -> Iterator[asyncio.Queue[None]]:
    """Signal each start of a retained-topic collection."""
    queue: asyncio.Queue[None] = asyncio.Queue()
    clear_stale = Publisher.async_clear_stale

    async def watched(self: Publisher, settle: float) -> list[str]:
        queue.put_nowait(None)
        return await clear_stale(self, settle)

    with patch.object(Publisher, "async_clear_stale", watched):
        yield queue


async def _added(
    hass: HomeAssistant, profile: dict[str, Any], runs: asyncio.Queue[None]
) -> MockConfigEntry:
    entry = make_entry(profile)
    await _setup(hass, entry)
    await _settle(hass)
    while not runs.empty():  # the device's own startup cleanup
        runs.get_nowait()
    return entry


async def _collect(hass: HomeAssistant, runs: asyncio.Queue[None], *subs: str) -> None:
    """Wait for a collection to start, then hand it retained topics."""
    async with asyncio.timeout(5):
        await runs.get()
    for _ in range(5):
        await asyncio.sleep(0)  # let the collection subscribe
    for sub in subs:
        async_fire_mqtt_message(hass, PREFIX + sub, "x", retain=True)
    await _settle(hass)


def _cleared(mqtt_mock: Any) -> set[str]:
    return {t for t, p, _, r in published(mqtt_mock) if p == b"" and r}


def _retry(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=purge.RETRY_SECONDS + 1)
    )


async def test_a_failed_clear_on_removal_is_retried(
    hass: HomeAssistant,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    runs: asyncio.Queue[None],
) -> None:
    entry = await _added(hass, tender_profile, runs)
    mqtt_mock.async_publish.side_effect = HomeAssistantError("MQTT broker is away")
    removal = hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
    await _collect(hass, runs, "meta", "views")
    await removal

    mqtt_mock.async_publish.side_effect = None
    mqtt_mock.async_publish.reset_mock()
    _retry(hass)
    await _collect(hass, runs, "meta", "views")
    assert {PREFIX + "meta", PREFIX + "views"} <= _cleared(mqtt_mock)

    mqtt_mock.async_publish.reset_mock()
    _retry(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert runs.empty()  # done: no further run
    assert not mqtt_mock.async_publish.call_args_list


async def test_a_removal_while_the_broker_is_away_is_retried(
    hass: HomeAssistant,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    runs: asyncio.Queue[None],
) -> None:
    entry = await _added(hass, tender_profile, runs)
    with patch("homeassistant.components.mqtt.is_connected", return_value=False):
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        assert runs.empty()  # nothing to collect from a broker that is away
        _retry(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert runs.empty()  # still away: tried again later

    mqtt_mock.async_publish.reset_mock()
    _retry(hass)
    await _collect(hass, runs, "meta", "alert/a1")
    assert {PREFIX + "meta", PREFIX + "alert/a1"} <= _cleared(mqtt_mock)


async def test_adding_the_device_again_stops_the_retry(
    hass: HomeAssistant,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    runs: asyncio.Queue[None],
) -> None:
    entry = await _added(hass, tender_profile, runs)
    with patch("homeassistant.components.mqtt.is_connected", return_value=False):
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    await _added(hass, tender_profile, runs)
    mqtt_mock.async_publish.reset_mock()
    _retry(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert runs.empty()
    assert PREFIX + "meta" not in _cleared(mqtt_mock)
