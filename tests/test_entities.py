"""The device's entities and its presence."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS
from custom_components.roundhouse.deviceinfo import find_device

from .conftest import announce, make_entry, vector
from .helpers import PREFIX, advance, config, setup

HOUR = 3600


def entity_id(
    hass: HomeAssistant, domain: str, key: str, device: str = "tender01"
) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{device}_{key}")


def state(hass: HomeAssistant, domain: str, key: str) -> Any:
    eid = entity_id(hass, domain, key)
    assert eid is not None, f"no {domain} {key}"
    found = hass.states.get(eid)
    assert found is not None
    return found


def fire(hass: HomeAssistant, topic: str, payload: Any, retain: bool = False) -> None:
    body = payload if isinstance(payload, bytes | str) else json.dumps(payload)
    async_fire_mqtt_message(hass, PREFIX + topic, body, retain=retain)


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture
async def tender(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> Any:
    entry = await setup(hass, tender_profile, config(("home", [])))
    return entry


# --- entities -----------------------------------------------------------------


async def test_a_battery_device_gets_every_entity(
    hass: HomeAssistant, tender: Any
) -> None:
    fire(hass, "status", {"battery": 82, "charging": False, "power_mode": "sleep"})
    await hass.async_block_till_done()
    assert state(hass, "sensor", "battery").state == "82"
    assert state(hass, "sensor", "battery").attributes["device_class"] == "battery"
    assert state(hass, "binary_sensor", "charging").state == "off"
    assert state(hass, "sensor", "power_mode").state == "sleep"
    assert state(hass, "sensor", "contract_version").state == "1.0"
    assert state(hass, "sensor", "unread_alerts").state == "0"
    assert entity_id(hass, "notify", "notify") is not None
    assert entity_id(hass, "device_tracker", "presence") is not None
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_status_changes_update_the_entities(
    hass: HomeAssistant, tender: Any
) -> None:
    fire(hass, "status", {"battery": 82, "charging": False, "power_mode": "sleep"})
    await hass.async_block_till_done()
    fire(hass, "status", {"battery": 80, "charging": True, "power_mode": "active"})
    await hass.async_block_till_done()
    assert state(hass, "sensor", "battery").state == "80"
    assert state(hass, "binary_sensor", "charging").state == "on"
    assert state(hass, "sensor", "power_mode").state == "active"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_battery_entities_appear_only_when_the_device_reports_a_battery(
    hass: HomeAssistant, tender: Any
) -> None:
    assert entity_id(hass, "sensor", "battery") is None
    assert entity_id(hass, "binary_sensor", "charging") is None
    fire(hass, "status", {"power_mode": "sleep"})  # no battery in the report
    await hass.async_block_till_done()
    assert entity_id(hass, "sensor", "battery") is None
    fire(
        hass, "status", {"battery": 55, "power_mode": "sleep"}
    )  # a level, no charging state
    await hass.async_block_till_done()
    assert state(hass, "sensor", "battery").state == "55"
    assert entity_id(hass, "binary_sensor", "charging") is None
    fire(hass, "status", {"battery": 54, "charging": True, "power_mode": "sleep"})
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor", "charging").state == "on"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_mains_device_without_sleep_omits_what_does_not_apply(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    wall = vector("announce", "wall-panel")["payload"]
    await setup(
        hass,
        wall,
        config(("home", [])),
        entry=make_entry(wall, "wall01"),
    )
    async_fire_mqtt_message(
        hass, "roundhouse/wall01/status", json.dumps({"power_mode": "active"})
    )
    await hass.async_block_till_done()
    for domain, key in (
        ("sensor", "battery"),
        ("binary_sensor", "charging"),
        ("sensor", "power_mode"),
    ):
        assert entity_id(hass, domain, key, "wall01") is None, key
    for domain, key in (
        ("sensor", "contract_version"),
        ("sensor", "unread_alerts"),
        ("notify", "notify"),
        ("device_tracker", "presence"),
    ):
        assert entity_id(hass, domain, key, "wall01") is not None, key
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_bad_status_is_ignored(hass: HomeAssistant, tender: Any) -> None:
    fire(hass, "status", {"battery": 70, "power_mode": "sleep"})
    await hass.async_block_till_done()
    for junk in (b"{not json", b'{"battery": 500, "power_mode": "x"}', b"[]", b""):
        fire(hass, "status", junk)
        await hass.async_block_till_done()
    assert state(hass, "sensor", "battery").state == "70"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_skipped_cards_sensor_of_an_earlier_version_is_removed(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    registry = er.async_get(hass)
    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, "tender01_skipped_cards", config_entry=entry
    )
    await setup(hass, tender_profile, config(("home", [])), entry=entry)
    assert registry.async_get(old.entity_id) is None
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_unread_sensor_follows_alerts(
    hass: HomeAssistant, tender: Any
) -> None:
    device = hass.data[DOMAIN][tender.entry_id]
    first = await device.alerts.async_add(title="a", message="m")
    await device.alerts.async_add(title="b", message="m")
    await hass.async_block_till_done()
    assert state(hass, "sensor", "unread_alerts").state == "2"
    await device.alerts.async_acknowledge(alert_id=first)
    await hass.async_block_till_done()
    assert state(hass, "sensor", "unread_alerts").state == "1"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_device_carries_the_model_and_versions(
    hass: HomeAssistant, tender: Any
) -> None:
    found = find_device(hass, tender)
    assert found is not None
    assert (found.model, found.name, found.sw_version) == (
        "tender",
        "Tender tender01",
        "0.4.0 (wapp 0.2.0)",
    )
    # A firmware update changes the announce, and the device follows.
    newer = json.loads(json.dumps(vector("announce", "tender")["payload"]))
    newer.update(fw="0.5.0", wapp="0.3.0")
    announce(hass, "tender01", newer)
    await hass.async_block_till_done()
    found = find_device(hass, tender)
    assert found is not None and found.sw_version == "0.5.0 (wapp 0.3.0)"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_all_entities_belong_to_the_one_device(
    hass: HomeAssistant, tender: Any
) -> None:
    fire(hass, "status", {"battery": 1, "charging": False, "power_mode": "sleep"})
    await hass.async_block_till_done()
    device = find_device(hass, tender)
    assert device is not None
    registry = er.async_get(hass)
    mine = [e for e in registry.entities.values() if e.platform == DOMAIN]
    assert len(mine) == 7 and {e.device_id for e in mine} == {device.id}
    await advance(hass, STALE_SETTLE_SECONDS + 1)


# --- presence -----------------------------------------------------------------


def tracker(hass: HomeAssistant) -> Any:
    return state(hass, "device_tracker", "presence")


async def test_the_tracker_uses_no_deprecated_home_assistant_api(
    hass: HomeAssistant, tender: Any, caplog: pytest.LogCaptureFixture
) -> None:
    assert tracker(hass).state == "unknown"
    assert "deprecated" not in caplog.text
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_tracker_is_unknown_before_the_first_availability_message(
    hass: HomeAssistant, tender: Any
) -> None:
    assert tracker(hass).state == "unknown"
    assert tracker(hass).attributes["source_type"] == "router"
    fire(hass, "availability", "online")
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_offline_reads_not_home_only_after_the_grace(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    fire(hass, "availability", "online")
    await hass.async_block_till_done()
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 2 * HOUR - 60)
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 61)
    assert tracker(hass).state == "not_home"
    fire(hass, "availability", "online")
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_coming_back_inside_the_grace_never_leaves_home(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    await tick(hass, freezer, HOUR)
    fire(hass, "availability", "online")
    await hass.async_block_till_done()
    await tick(hass, freezer, 5 * HOUR)  # the old timer must not fire
    assert tracker(hass).state == "home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_grace_is_an_option(
    hass: HomeAssistant,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"presence_grace_hours": 1})
    await setup(hass, tender_profile, config(("home", [])), entry=entry)
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    await tick(hass, freezer, HOUR - 60)
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 61)
    assert tracker(hass).state == "not_home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_restart_does_not_reset_the_countdown(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    await tick(hass, freezer, HOUR + 1800)  # 1.5 h into the 2 h grace
    assert tracker(hass).state == "home"

    assert await hass.config_entries.async_reload(tender.entry_id)
    await hass.async_block_till_done()
    assert tracker(hass).state == "unknown"  # nothing said yet
    # The broker hands over the retained last will.
    fire(hass, "availability", "offline", retain=True)
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 1700)  # 1.5 h + 1700 s: still inside
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 200)  # past 2 h in total, not 2 h after the restart
    assert tracker(hass).state == "not_home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_grace_that_ran_out_during_the_downtime_reads_not_home_at_once(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(tender.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=5))  # Home Assistant was down for five hours
    assert await hass.config_entries.async_setup(tender.entry_id)
    await hass.async_block_till_done()
    fire(hass, "availability", "offline", retain=True)
    await hass.async_block_till_done()
    assert tracker(hass).state == "not_home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_online_after_a_restart_clears_the_stored_time(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    fire(hass, "availability", "offline")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(tender.entry_id)
    await hass.async_block_till_done()
    fire(hass, "availability", "online", retain=True)
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    assert hass.data[DOMAIN][tender.entry_id].presence.offline_since is None
    await tick(hass, freezer, 10 * HOUR)
    assert tracker(hass).state == "home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_grace_follows_a_device_that_was_never_seen_online(
    hass: HomeAssistant, tender: Any, freezer: FrozenDateTimeFactory
) -> None:
    """A last will with no earlier record starts the grace when it arrives."""
    fire(hass, "availability", "offline", retain=True)
    await hass.async_block_till_done()
    assert tracker(hass).state == "home"
    await tick(hass, freezer, 2 * HOUR + 1)
    assert tracker(hass).state == "not_home"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_junk_availability_is_ignored(hass: HomeAssistant, tender: Any) -> None:
    for junk in ("maybe", "ONLINE", "", "online\n"):
        fire(hass, "availability", junk)
        await hass.async_block_till_done()
    assert tracker(hass).state == "unknown"
    await advance(hass, STALE_SETTLE_SECONDS + 1)
