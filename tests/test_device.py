"""Publishing, profile handling, repairs, and resync."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.roundhouse import layout
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS
from custom_components.roundhouse.device import Device
from custom_components.roundhouse.publisher import PayloadTooLargeError

from .conftest import announce, make_entry, vector

PREFIX = "roundhouse/tender01/"


def published(mqtt_mock: Any) -> list[tuple[str, Any, int, bool]]:
    """Every publish so far: topic, payload, qos, retain."""
    return [tuple(c.args[:4]) for c in mqtt_mock.async_publish.call_args_list]  # type: ignore[misc]


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> Device:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device: Device = hass.data[DOMAIN][entry.entry_id]
    return device


async def _settle(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=STALE_SETTLE_SECONDS + 1)
    )
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_publishes_meta_retained(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    device = await _setup(hass, make_entry(tender_profile))
    meta = [p for p in published(mqtt_mock) if p[0] == PREFIX + "meta"]
    assert len(meta) == 1
    _, payload, qos, retain = meta[0]
    assert (qos, retain) == (1, True)
    assert json.loads(payload) == {
        "contract": "1.0",
        "language": hass.config.language,
        "views_hash": layout.definition_hash(layout.EMPTY_VIEWS),
    }
    # No dashboard exists yet, so the device holds an empty view definition.
    assert device.publisher.owned == {"meta", "views"}
    await _settle(hass)


async def test_stale_retained_topics_are_cleared_at_startup(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(0)  # let the cleanup task subscribe
    for sub in ("state/light.gone", "icon/mdi_old", "alert/dead", "views"):
        async_fire_mqtt_message(hass, PREFIX + sub, "x", retain=True)
    # Device-owned topics and our own meta stay.
    for sub in ("status", "availability", "announce", "meta"):
        async_fire_mqtt_message(hass, PREFIX + sub, "x", retain=True)
    await _settle(hass)
    cleared = {t for t, p, _, r in published(mqtt_mock) if p == b"" and r}
    assert cleared == {
        PREFIX + "state/light.gone",
        PREFIX + "icon/mdi_old",
        PREFIX + "alert/dead",
        PREFIX + "views",
    }


async def test_live_messages_are_not_stale_topics(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    """Only retained messages count; a live one is traffic, not leftovers."""
    await _setup(hass, make_entry(tender_profile))
    await asyncio.sleep(0)
    async_fire_mqtt_message(hass, PREFIX + "state/light.live", "x", retain=False)
    await _settle(hass)
    assert not [t for t, p, _, _ in published(mqtt_mock) if p == b""]


async def test_changed_profile_updates_the_entry(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile)
    device = await _setup(hass, entry)
    newer = vector("announce", "newer-minor-unknown-fields")
    announce(hass, "tender01", newer["payload"])
    await hass.async_block_till_done()
    assert entry.data["profile"] == newer["decoded"]
    assert hass.data[DOMAIN][entry.entry_id] is not device  # reloaded
    await _settle(hass)


async def test_same_profile_does_not_reload(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile)
    device = await _setup(hass, entry)
    announce(hass, "tender01", tender_profile)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id] is device
    await _settle(hass)


async def test_major_mismatch_raises_an_issue_and_clears_it(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile)
    device = await _setup(hass, entry)
    await device.publisher.async_publish("state/light.x", b"{}")

    announce(hass, "tender01", vector("announce", "major-mismatch")["payload"])
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01")
    assert issue is not None
    assert issue.translation_key == "contract_mismatch"
    assert "2.0" in issue.translation_placeholders["detail"]
    # Only meta stays held.
    assert device.publisher.owned == {"meta"}
    assert (PREFIX + "state/light.x", b"", 1, True) in published(mqtt_mock)

    announce(hass, "tender01", tender_profile)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01") is None
    # Recovery publishes the view definition again, not only meta.
    assert device.publisher.owned == {"meta", "views"}
    await _settle(hass)


async def test_unknown_format_raises_an_issue(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await _setup(hass, make_entry(tender_profile))
    announce(hass, "tender01", vector("announce", "unknown-format")["payload"])
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01")
    assert issue is not None
    assert issue.translation_key == "profile_invalid"
    await _settle(hass)


async def test_unparsable_announce_raises_an_issue(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await _setup(hass, make_entry(tender_profile))
    announce(hass, "tender01", b"{not json")
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01") is not None
    await _settle(hass)


async def test_empty_announce_is_ignored(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await _setup(hass, make_entry(tender_profile))
    announce(hass, "tender01", b"")
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01") is None
    await _settle(hass)


async def test_reconnect_republishes_everything(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    device = await _setup(hass, make_entry(tender_profile))
    await device.publisher.async_publish("state/light.x", b'{"a":1}')
    mqtt_mock.async_publish.reset_mock()

    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await hass.async_block_till_done()
    assert published(mqtt_mock) == []  # nothing while disconnected
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    topics = {t for t, *_ in published(mqtt_mock)}
    assert topics == {PREFIX + "meta", PREFIX + "views", PREFIX + "state/light.x"}
    await _settle(hass)


async def test_publisher_skips_unchanged_and_respects_max_payload(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    device = await _setup(hass, make_entry(tender_profile))
    pub = device.publisher
    assert await pub.async_publish("state/a.b", b"1") is True
    assert await pub.async_publish("state/a.b", b"1") is False
    assert await pub.async_publish("state/a.b", b"2") is True
    with pytest.raises(PayloadTooLargeError):
        await pub.async_publish("state/a.c", b"x" * (pub.max_payload + 1))
    assert "state/a.c" not in pub.owned
    await pub.async_clear("state/a.b")
    assert "state/a.b" not in pub.owned
    await _settle(hass)


@pytest.mark.parametrize(
    ("mqtt_config_entry_options", "issue"),
    [
        ({}, False),
        ({"birth_message": {}}, True),
        (
            {
                "birth_message": {
                    "topic": "homeassistant/status",
                    "payload": "online",
                    "qos": 0,
                    "retain": False,
                }
            },
            False,
        ),
        (
            {
                "birth_message": {
                    "topic": "elsewhere/status",
                    "payload": "online",
                    "qos": 0,
                    "retain": False,
                }
            },
            True,
        ),
    ],
    ids=["default", "disabled", "explicit", "wrong-topic"],
)
async def test_mqtt_birth_message_issue(
    hass: HomeAssistant,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    mqtt_config_entry_options: dict[str, Any],
    issue: bool,
) -> None:
    await _setup(hass, make_entry(tender_profile))
    found = ir.async_get(hass).async_get_issue(DOMAIN, "mqtt_birth_disabled")
    assert (found is not None) is issue
    await _settle(hass)


async def test_removing_a_device_clears_its_topics_stores_and_issues(
    hass: HomeAssistant,
    mqtt_mock: Any,
    hass_storage: dict[str, Any],
    tender_profile: dict[str, Any],
) -> None:
    from homeassistant.helpers.storage import Store

    from custom_components.roundhouse import issues
    from custom_components.roundhouse.publisher import Publisher

    entry = make_entry(tender_profile)
    device = await _setup(hass, entry)
    await _settle(hass)
    alert_id = await device.alerts.async_add(title="t", message="m")
    image: Store[dict[str, Any]] = Store(
        hass, 1, f"roundhouse.tender01.alert_{alert_id}"
    )
    await image.async_save({"format": "gray4"})
    issues.raise_dashboard_issue(hass, "tender01", "deleted")
    # The removed device's view `x-home` and another device `tender01_x`'s view
    # `home` once shared one issue ID; the other device keeps its issue.
    mine = issues.overflow_issue_id("tender01", "x-home")
    theirs = issues.overflow_issue_id("tender01_x", "home")
    assert mine != theirs
    make_entry(tender_profile, "tender01_x", "x").add_to_hass(hass)
    for issue_id in (mine, theirs):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="view_overflow",
        )
    await hass.async_block_till_done()
    assert {k for k in hass_storage if k.startswith("roundhouse.tender01.")}

    started = asyncio.Event()
    clear_stale = Publisher.async_clear_stale

    async def watched(self: Publisher, settle: float) -> list[str]:
        started.set()
        return await clear_stale(self, settle)

    with patch.object(Publisher, "async_clear_stale", watched):
        removal = hass.async_create_task(
            hass.config_entries.async_remove(entry.entry_id)
        )
        async with asyncio.timeout(5):
            await started.wait()
        for _ in range(5):
            await asyncio.sleep(0)  # let the cleanup subscribe
        for sub in ("meta", "views", f"alert/{alert_id}", "status"):
            async_fire_mqtt_message(hass, PREFIX + sub, "x", retain=True)
        await _settle(hass)
        await removal

    cleared = {t for t, p, _, r in published(mqtt_mock) if p == b"" and r}
    assert {PREFIX + "meta", PREFIX + "views", PREFIX + f"alert/{alert_id}"} <= cleared
    assert PREFIX + "status" not in cleared  # the device's own topic
    assert not {k for k in hass_storage if k.startswith("roundhouse.tender01.")}
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "deleted_tender01") is None
    assert registry.async_get_issue(DOMAIN, mine) is None
    assert registry.async_get_issue(DOMAIN, theirs) is not None
