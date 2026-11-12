"""The alert lifecycle: raise, publish, act, acknowledge, age, restart."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import types
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
from PIL import Image
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.roundhouse import alertmanager, codec
from custom_components.roundhouse.compat import vol
from custom_components.roundhouse.const import (
    DOMAIN,
    EVENT_ALERT_ACKNOWLEDGED,
    STALE_SETTLE_SECONDS,
    alerts_signal,
)
from custom_components.roundhouse.deviceinfo import find_device

from .conftest import announce, vector
from .test_views import PREFIX, advance, config, setup

DAY = 86400
GATE = {
    "id": "open",
    "label": "Open gate",
    "action": "cover.open_cover",
    "target": {"entity_id": "cover.gate"},
    "confirm": True,
}
LIGHTS = {
    "id": "lights",
    "label": "Lights on",
    "action": "light.turn_on",
    "target": {"entity_id": "light.porch"},
    "data": {"brightness": 200},
}


def png(color: str = "red", size: tuple[int, int] = (640, 360)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class Camera:
    """A stand-in for `homeassistant.components.camera`."""

    def __init__(
        self, content: bytes = b"", delay: float = 0, fail: bool = False
    ) -> None:
        self.content, self.delay, self.fail = content or png(), delay, fail
        self.calls = 0

    def module(self) -> types.ModuleType:
        async def get_image(_hass: Any, entity_id: str) -> Any:
            self.calls += 1
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("camera offline")
            return types.SimpleNamespace(content=self.content)

        mod = types.ModuleType("homeassistant.components.camera")
        mod.async_get_image = get_image  # type: ignore[attr-defined]
        return mod

    def patched(self) -> Any:
        return patch.dict(
            sys.modules, {"homeassistant.components.camera": self.module()}
        )


@pytest.fixture
async def device(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> Any:
    entry = await setup(hass, tender_profile, config(("home", [])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    mqtt_mock.async_publish.reset_mock()
    return hass.data[DOMAIN][entry.entry_id]


def registry_id(hass: HomeAssistant, device_id: str = "tender01") -> str:
    entry = next(
        e for e in hass.config_entries.async_entries(DOMAIN) if e.unique_id == device_id
    )
    found = find_device(hass, entry)
    assert found is not None
    return found.id


async def send(hass: HomeAssistant, **data: Any) -> dict[str, str]:
    data.setdefault("device_id", [registry_id(hass)])
    data.setdefault("title", "Title")
    data.setdefault("message", "Message")
    response = await hass.services.async_call(
        DOMAIN, "send_alert", data, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return response["alert_ids"]  # type: ignore[index,no-any-return]


def topic_publishes(mqtt_mock: Any, topic: str) -> list[bytes]:
    return [
        c.args[1]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + topic
    ]


def last_alert(mqtt_mock: Any, alert_id: str) -> dict[str, Any]:
    return json.loads(topic_publishes(mqtt_mock, f"alert/{alert_id}")[-1])  # type: ignore[no-any-return]


async def cmd(hass: HomeAssistant, mqtt_mock: Any, body: dict[str, Any]) -> str | None:
    async_fire_mqtt_message(hass, PREFIX + "cmd", json.dumps(body), qos=1)
    await hass.async_block_till_done()
    got = [
        json.loads(c.args[1])["result"]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "result"
        and json.loads(c.args[1])["req"] == body["req"]
    ]
    return got[-1] if got else None


# --- raise an alert from an automation -----------------------------------


async def test_an_alert_is_published_retained_without_its_service_calls(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    (alert_id,) = (
        await send(hass, severity="critical", actions=[GATE, LIGHTS], tag="gate")
    ).values()
    payload = last_alert(mqtt_mock, alert_id)
    assert codec.decode("alert", json.dumps(payload).encode()) == payload
    assert (payload["title"], payload["severity"], payload["read"]) == (
        "Title",
        "critical",
        False,
    )
    assert payload["actions"] == [
        {"id": "open", "label": "Open gate", "confirm": True},
        {"id": "lights", "label": "Lights on", "confirm": False},
    ]
    assert "cover" not in json.dumps(payload)
    published = [
        c
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + f"alert/{alert_id}"
    ]
    assert tuple(published[-1].args[2:4]) == (1, True)
    assert f"alert/{alert_id}" in device.publisher.owned


async def test_a_camera_snapshot_is_attached_within_the_budget(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, tender_profile: dict[str, Any]
) -> None:
    started = time.perf_counter()
    with Camera().patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    assert time.perf_counter() - started < 3  # the budget for a snapshot alert
    payload = last_alert(mqtt_mock, alert_id)
    box, thumb_box = tender_profile["image_box"], tender_profile["thumb_box"]
    assert (payload["image"]["width"], payload["image"]["height"]) == (480, 270)
    assert payload["thumb"]["width"] <= thumb_box["width"]
    (image,) = topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
    (thumb,) = topic_publishes(mqtt_mock, f"alert/{alert_id}/thumb")
    assert (
        len(image) == 270 * 240 and payload["image"]["width"] <= box["width"]
    )  # gray4, 2 px a byte
    assert codec.decode_bitmap(
        "gray4", payload["thumb"]["width"], payload["thumb"]["height"], thumb
    )
    # The images are published before the alert that names them.
    order = [c.args[0] for c in mqtt_mock.async_publish.call_args_list]
    assert order.index(PREFIX + f"alert/{alert_id}/image") < order.index(
        PREFIX + f"alert/{alert_id}"
    )


async def test_the_wall_panel_gets_rgb565_images(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None
) -> None:
    from .conftest import make_entry

    wall = vector("announce", "wall-panel")["payload"]
    entry = make_entry(wall, "tender01", "tender-panel")
    await setup(hass, wall, config(("home", [])), entry=entry)
    mqtt_mock.async_publish.reset_mock()
    with Camera().patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    payload = last_alert(mqtt_mock, alert_id)
    (image,) = topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
    assert len(image) == payload["image"]["width"] * payload["image"]["height"] * 2
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_an_image_url_is_fetched(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, aioclient_mock: Any
) -> None:
    aioclient_mock.get("http://cam.local/s.png", content=png("blue", (120, 90)))
    (alert_id,) = (await send(hass, image_url="http://cam.local/s.png")).values()
    assert last_alert(mqtt_mock, alert_id)["image"] == {"width": 120, "height": 90}


async def test_a_failed_snapshot_sends_the_alert_without_an_image(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with Camera(fail=True).patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    payload = last_alert(mqtt_mock, alert_id)
    assert payload["image"] is None and payload["thumb"] is None
    assert not topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
    assert "camera offline" in caplog.text


async def test_a_slow_snapshot_does_not_hold_the_alert_back(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    with patch.object(alertmanager, "IMAGE_WAIT", 0.02), Camera(delay=0.2).patched():
        response = await hass.services.async_call(
            DOMAIN,
            "send_alert",
            {
                "device_id": [registry_id(hass)],
                "title": "t",
                "message": "m",
                "camera_entity": "camera.gate",
            },
            blocking=True,
            return_response=True,
        )
        (alert_id,) = response["alert_ids"].values()
        # The service returned and the alert is out, still without the image.
        assert last_alert(mqtt_mock, alert_id)["image"] is None
        assert not topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
        await asyncio.sleep(0.4)
        await hass.async_block_till_done()
    late = last_alert(mqtt_mock, alert_id)
    assert late["image"] is not None  # the image followed, and the alert names it
    assert topic_publishes(mqtt_mock, f"alert/{alert_id}/image")


async def test_an_image_that_cannot_fit_the_payload_limit_shrinks(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    profile = json.loads(json.dumps(tender_profile))
    profile["limits"]["max_payload"] = 20000
    await setup(hass, profile, config(("home", [])))
    mqtt_mock.async_publish.reset_mock()
    with Camera().patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    payload = last_alert(mqtt_mock, alert_id)
    (image,) = topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
    assert len(image) <= 20000
    assert payload["image"]["width"] < 480
    assert len(image) == codec_len(payload["image"], 4)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


def codec_len(size: dict[str, int], bits: int) -> int:
    return size["height"] * ((size["width"] * bits + 7) // 8)


async def test_the_action_button_runs_the_declared_call(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    opened = async_mock_service(hass, "cover", "open_cover")
    lit = async_mock_service(hass, "light", "turn_on")
    (alert_id,) = (await send(hass, actions=[GATE, LIGHTS])).values()
    # The device sends only the action ID.
    result = await cmd(
        hass, mqtt_mock, {"req": "a1", "alert": alert_id, "action_id": "lights"}
    )
    assert result == "ok"
    assert lit[0].data == {"brightness": 200, "entity_id": "light.porch"}
    # A flagged action needs confirmation first.
    assert await cmd(
        hass, mqtt_mock, {"req": "a2", "alert": alert_id, "action_id": "open"}
    ) == ("needs_confirmation")
    assert opened == []
    done = await cmd(
        hass,
        mqtt_mock,
        {"req": "a3", "alert": alert_id, "action_id": "open", "confirmed": True},
    )
    assert done == "ok" and opened[0].data == {"entity_id": "cover.gate"}


async def test_an_alert_action_is_deduplicated_like_a_command(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    (alert_id,) = (await send(hass, actions=[LIGHTS])).values()
    body = {"req": "dup", "alert": alert_id, "action_id": "lights"}
    assert await cmd(hass, mqtt_mock, body) == "ok"
    assert await cmd(hass, mqtt_mock, body) == "ok"
    assert len(calls) == 1


async def test_an_alert_action_reports_a_failing_service(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    (alert_id,) = (await send(hass, actions=[LIGHTS])).values()
    result = await cmd(
        hass, mqtt_mock, {"req": "x1", "alert": alert_id, "action_id": "lights"}
    )
    assert result is not None and "light.turn_on" in result  # service not found


@pytest.mark.parametrize(
    "body",
    [
        {"req": "u1", "alert": "deadbeef", "action_id": "open"},
        {"req": "u2", "ack": "deadbeef"},
    ],
)
async def test_unknown_alerts_are_denied(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, body: dict[str, Any]
) -> None:
    assert await cmd(hass, mqtt_mock, body) == "denied"


async def test_an_unknown_action_id_is_denied(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    (alert_id,) = (await send(hass, actions=[LIGHTS])).values()
    assert (
        await cmd(
            hass, mqtt_mock, {"req": "n1", "alert": alert_id, "action_id": "nope"}
        )
        == "denied"
    )
    assert calls == []


# --- acknowledge everywhere ----------------------------------------------


async def test_a_device_acknowledgment_marks_the_alert_read_and_fires_the_event(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    events: list[Event] = []
    hass.bus.async_listen(EVENT_ALERT_ACKNOWLEDGED, events.append)
    signals: list[None] = []
    async_dispatcher_connect(
        hass, alerts_signal("tender01"), lambda: signals.append(None)
    )
    (alert_id,) = (await send(hass, tag="gate")).values()
    assert device.alerts.unread == 1
    signals.clear()

    assert await cmd(hass, mqtt_mock, {"req": "k1", "ack": alert_id}) == "ok"
    assert last_alert(mqtt_mock, alert_id)["read"] is True
    assert [e.data for e in events] == [
        {"alert_id": alert_id, "tag": "gate", "device_id": "tender01"}
    ]
    assert device.alerts.unread == 0 and signals

    # A second acknowledgment is answered ok but raises nothing again.
    assert await cmd(hass, mqtt_mock, {"req": "k2", "ack": alert_id}) == "ok"
    assert len(events) == 1


@pytest.mark.parametrize("by", ["alert_id", "tag"])
async def test_the_service_acknowledges_by_id_or_by_tag(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, by: str
) -> None:
    events: list[Event] = []
    hass.bus.async_listen(EVENT_ALERT_ACKNOWLEDGED, events.append)
    (alert_id,) = (await send(hass, tag="gate")).values()
    (other,) = (await send(hass, tag="door")).values()
    value = alert_id if by == "alert_id" else "gate"
    await hass.services.async_call(
        DOMAIN, "acknowledge_alert", {by: value}, blocking=True
    )
    await hass.async_block_till_done()
    assert last_alert(mqtt_mock, alert_id)["read"] is True
    assert last_alert(mqtt_mock, other)["read"] is False
    assert [e.data["alert_id"] for e in events] == [alert_id]


async def test_acknowledging_needs_an_id_or_a_tag(
    hass: HomeAssistant, device: Any
) -> None:
    with pytest.raises(ServiceValidationError, match="alert_id or a tag"):
        await hass.services.async_call(DOMAIN, "acknowledge_alert", {}, blocking=True)


# --- the service --------------------------------------------------------------


async def test_a_tag_replaces_the_old_alert(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    with Camera().patched():
        (first,) = (await send(hass, tag="gate", camera_entity="camera.gate")).values()
    (second,) = (await send(hass, tag="gate")).values()
    assert first != second
    assert (
        not {f"alert/{first}", f"alert/{first}/image", f"alert/{first}/thumb"}
        & device.publisher.owned
    )
    assert f"alert/{second}" in device.publisher.owned
    for sub in ("", "/image", "/thumb"):
        assert (PREFIX + f"alert/{first}{sub}", b"", 1, True) in [
            tuple(c.args[:4]) for c in mqtt_mock.async_publish.call_args_list
        ]
    assert [a["id"] for a in device.alerts.alerts] == [second]


@pytest.mark.parametrize(
    "bad",
    [
        {"actions": [{"id": "x"}]},
        {"actions": [GATE, GATE]},
        {"actions": "open"},
        {"actions": [{**GATE, "action": "nodot"}]},
        {"actions": [{**GATE, "confirm": "yes"}]},
    ],
)
async def test_bad_actions_are_refused_and_nothing_is_published(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, bad: dict[str, Any]
) -> None:
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await send(hass, **bad)
    assert device.alerts.alerts == []
    assert not [
        c for c in mqtt_mock.async_publish.call_args_list if "/alert/" in c.args[0]
    ]


async def test_the_severity_must_be_known(hass: HomeAssistant, device: Any) -> None:
    with pytest.raises(Exception, match=r"severity|panic"):
        await send(hass, severity="panic")


async def test_the_default_severity_is_event(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    (alert_id,) = (await send(hass)).values()
    assert last_alert(mqtt_mock, alert_id)["severity"] == "event"


async def test_a_target_is_required_and_must_be_a_roundhouse_device(
    hass: HomeAssistant, device: Any
) -> None:
    with pytest.raises(ServiceValidationError, match="at least one Roundhouse device"):
        await hass.services.async_call(
            DOMAIN, "send_alert", {"title": "t", "message": "m"}, blocking=True
        )
    with pytest.raises(ServiceValidationError, match="not a Roundhouse device"):
        await hass.services.async_call(
            DOMAIN,
            "send_alert",
            {"title": "t", "message": "m", "device_id": ["nope"]},
            blocking=True,
        )


async def test_two_devices_each_get_the_alert(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    from .conftest import make_entry

    await setup(hass, tender_profile, config(("home", [])))
    second = make_entry(tender_profile, "tender02", "tender-panel-2")
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    ids = await send(hass, device_id=[registry_id(hass), registry_id(hass, "tender02")])
    assert set(ids) == {"tender01", "tender02"}
    topics = {c.args[0] for c in mqtt_mock.async_publish.call_args_list}
    assert PREFIX + f"alert/{ids['tender01']}" in topics
    assert f"roundhouse/tender02/alert/{ids['tender02']}" in topics
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_two_devices_share_one_snapshot_fetch(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    from .conftest import make_entry

    await setup(hass, tender_profile, config(("home", [])))
    second = make_entry(tender_profile, "tender02", "tender-panel-2")
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    camera = Camera()
    with camera.patched():
        ids = await send(
            hass,
            device_id=[registry_id(hass), registry_id(hass, "tender02")],
            camera_entity="camera.gate",
        )
    assert camera.calls == 1
    assert last_alert(mqtt_mock, ids["tender01"])["image"] is not None
    assert topic_publishes(mqtt_mock, f"alert/{ids['tender01']}/image")
    late = [
        c.args[1]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == f"roundhouse/tender02/alert/{ids['tender02']}/image"
    ]
    assert late
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_slow_snapshots_on_two_devices_wait_once(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    from .conftest import make_entry

    await setup(hass, tender_profile, config(("home", [])))
    second = make_entry(tender_profile, "tender02", "tender-panel-2")
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    with patch.object(alertmanager, "IMAGE_WAIT", 0.2), Camera(delay=1).patched():
        started = time.perf_counter()
        await hass.services.async_call(
            DOMAIN,
            "send_alert",
            {
                "device_id": [registry_id(hass), registry_id(hass, "tender02")],
                "title": "t",
                "message": "m",
                "camera_entity": "camera.gate",
            },
            blocking=True,
            return_response=True,
        )
        # The devices wait side by side, not one after the other.
        assert time.perf_counter() - started < 0.35
        await hass.async_block_till_done()
    await advance(hass, STALE_SETTLE_SECONDS + 1)


# --- notify -------------------------------------------------------------------


async def test_notify_send_message_becomes_an_event_alert(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    entry = er.async_get(hass).async_get_entity_id("notify", DOMAIN, "tender01_notify")
    assert entry is not None
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": entry, "message": "Washer done", "title": "Laundry"},
        blocking=True,
    )
    await hass.async_block_till_done()
    (alert,) = device.alerts.alerts
    assert (alert["title"], alert["message"], alert["severity"]) == (
        "Laundry",
        "Washer done",
        "event",
    )
    assert alert["actions"] == [] and alert["tag"] is None
    assert last_alert(mqtt_mock, alert["id"])["message"] == "Washer done"


async def test_notify_without_a_title_uses_the_device_name(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    entity_id = er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "tender01_notify"
    )
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": entity_id, "message": "Hi"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert device.alerts.alerts[0]["title"] == "Tender tender01"
    assert registry_id(hass)


# --- aging --------------------------------------------------------------------


@pytest.fixture
def clock() -> Any:
    state = {"now": 1_800_000_000.0}
    with patch.object(alertmanager, "now", lambda: state["now"]):
        yield state


async def test_alerts_age_out_by_count_and_lose_their_topics(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    clock: Any,
) -> None:
    from .conftest import make_entry

    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"alert_max_count": 2})
    await setup(hass, tender_profile, config(("home", [])), entry=entry)
    dev = hass.data[DOMAIN][entry.entry_id]
    ids = []
    with Camera().patched():
        for i in range(3):
            clock["now"] += 10
            (alert_id,) = (
                await send(hass, title=f"a{i}", camera_entity="camera.gate")
            ).values()
            ids.append(alert_id)
    assert [a["id"] for a in dev.alerts.alerts] == ids[1:]
    assert (
        not {f"alert/{ids[0]}", f"alert/{ids[0]}/image", f"alert/{ids[0]}/thumb"}
        & dev.publisher.owned
    )
    assert {f"alert/{ids[2]}", f"alert/{ids[2]}/image"} <= dev.publisher.owned
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_newest_alert_is_kept_when_alerts_share_a_second(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    clock: Any,
) -> None:
    from .conftest import make_entry

    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"alert_max_count": 1})
    await setup(hass, tender_profile, config(("home", [])), entry=entry)
    dev = hass.data[DOMAIN][entry.entry_id]
    for i in range(5):  # the clock stands still: every alert has the same time
        (alert_id,) = (await send(hass, title=f"a{i}")).values()
        assert [a["id"] for a in dev.alerts.alerts] == [alert_id]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_alerts_age_out_by_time_and_an_expired_action_is_denied(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, clock: Any
) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    (alert_id,) = (await send(hass, actions=[LIGHTS])).values()
    clock["now"] += 6.9 * DAY
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done()
    assert device.alerts.get(alert_id) is not None  # still inside 7 days

    clock["now"] += 0.2 * DAY
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=22))
    await hass.async_block_till_done()
    assert device.alerts.get(alert_id) is None
    assert f"alert/{alert_id}" not in device.publisher.owned
    # An action on an expired alert is denied, and the service is not called.
    assert (
        await cmd(
            hass, mqtt_mock, {"req": "late", "alert": alert_id, "action_id": "lights"}
        )
        == "denied"
    )
    assert await cmd(hass, mqtt_mock, {"req": "late2", "ack": alert_id}) == "denied"
    assert calls == []


# --- restart and recovery -----------------------------------------------------


async def test_alerts_survive_a_restart_with_their_images_and_flags(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    with Camera().patched():
        (alert_id,) = (
            await send(hass, camera_entity="camera.gate", actions=[LIGHTS], tag="t")
        ).values()
    await hass.async_block_till_done()
    await cmd(hass, mqtt_mock, {"req": "ack", "ack": alert_id})
    before = {
        t: topic_publishes(mqtt_mock, t)[-1]
        for t in (
            f"alert/{alert_id}",
            f"alert/{alert_id}/image",
            f"alert/{alert_id}/thumb",
        )
    }
    await advance(hass, STALE_SETTLE_SECONDS + 1)

    mqtt_mock.async_publish.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = {t: topic_publishes(mqtt_mock, t)[-1] for t in before}
    assert after == before  # identical bytes, read flag included
    # The images are republished before the alert that names them.
    order = [c.args[0] for c in mqtt_mock.async_publish.call_args_list]
    assert order.index(PREFIX + f"alert/{alert_id}/image") < order.index(
        PREFIX + f"alert/{alert_id}"
    )
    assert json.loads(after[f"alert/{alert_id}"])["read"] is True

    # The stale-topic cleanup keeps what was republished.
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert not [
        c
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[1] == b"" and "alert" in c.args[0]
    ]

    # The declared action still works after the restart.
    calls = async_mock_service(hass, "light", "turn_on")
    assert (
        await cmd(
            hass, mqtt_mock, {"req": "go", "alert": alert_id, "action_id": "lights"}
        )
        == "ok"
    )
    assert len(calls) == 1


async def test_an_alert_that_expired_while_offline_is_dropped_at_startup(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    clock: Any,
) -> None:
    entry = await setup(hass, tender_profile, config(("home", [])))
    (alert_id,) = (await send(hass)).values()
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    clock["now"] += 8 * DAY
    mqtt_mock.async_publish.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id].alerts.alerts == []
    assert (PREFIX + f"alert/{alert_id}", b"", 1, True) in [
        tuple(c.args[:4]) for c in mqtt_mock.async_publish.call_args_list
    ] or not topic_publishes(mqtt_mock, f"alert/{alert_id}")
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_meta_only_mode_clears_alerts_from_the_broker_and_recovery_restores_them(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, tender_profile: dict[str, Any]
) -> None:
    (alert_id,) = (await send(hass)).values()
    announce(hass, "tender01", vector("announce", "major-mismatch")["payload"])
    await hass.async_block_till_done()
    assert device.publisher.owned == {"meta"}
    assert device.alerts.get(alert_id) is not None  # kept, not published

    announce(hass, "tender01", tender_profile)
    await hass.async_block_till_done()
    assert f"alert/{alert_id}" in device.publisher.owned


async def test_a_meta_only_device_gets_no_alert_images(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    announce(hass, "tender01", vector("announce", "major-mismatch")["payload"])
    await hass.async_block_till_done()
    mqtt_mock.async_publish.reset_mock()
    with Camera().patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    assert not [
        c for c in mqtt_mock.async_publish.call_args_list if "/alert/" in c.args[0]
    ]
    assert device.publisher.owned == {"meta"}
    assert device.alerts.get(alert_id)["image"] is not None  # kept for recovery


@pytest.mark.parametrize(
    ("change", "dropped", "kept"),
    [
        ({"limits": {"max_payload": 20000}}, "image", "thumb"),
        ({"display": {"format": "rgb565"}}, "image", None),
    ],
)
async def test_stored_images_the_new_profile_cannot_take_are_dropped(
    hass: HomeAssistant,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    change: dict[str, Any],
    dropped: str,
    kept: str | None,
) -> None:
    from homeassistant.config_entries import ConfigEntryState

    entry = await setup(hass, tender_profile, config(("home", [])))
    with Camera().patched():
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    profile = json.loads(json.dumps(tender_profile))
    for section, values in change.items():
        profile[section] = {**profile[section], **values}

    mqtt_mock.async_publish.reset_mock()
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "profile": profile}
    )
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    alert = hass.data[DOMAIN][entry.entry_id].alerts.get(alert_id)
    assert alert[dropped] is None
    assert last_alert(mqtt_mock, alert_id)[dropped] is None
    assert not topic_publishes(mqtt_mock, f"alert/{alert_id}/{dropped}")
    if kept:
        assert alert[kept] is not None
        assert topic_publishes(mqtt_mock, f"alert/{alert_id}/{kept}")
    # The startup cleanup clears the old bitmap the broker still holds.
    async_fire_mqtt_message(
        hass, PREFIX + f"alert/{alert_id}/{dropped}", b"old", retain=True
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert (PREFIX + f"alert/{alert_id}/{dropped}", b"", 1, True) in [
        tuple(c.args[:4]) for c in mqtt_mock.async_publish.call_args_list
    ]


async def test_a_snapshot_done_just_after_the_wait_is_not_overwritten(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    from .conftest import make_entry

    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    # One alert held: each new one ages the old one out, so the records are copies.
    hass.config_entries.async_update_entry(entry, options={"alert_max_count": 1})
    await setup(hass, tender_profile, config(("home", [])), entry=entry)
    await send(hass)
    real_wait = asyncio.wait

    # Stands in for asyncio.wait, so it keeps its signature.
    async def late(fs: Any, timeout: float | None = None, **kw: Any) -> Any:  # noqa: ASYNC109
        if timeout != alertmanager.IMAGE_WAIT:
            return await real_wait(fs, timeout=timeout, **kw)
        await real_wait(fs)  # the image lands, then the wait reports a timeout
        return set(), set(fs)

    with Camera().patched(), patch.object(alertmanager.asyncio, "wait", late):
        (alert_id,) = (await send(hass, camera_entity="camera.gate")).values()
    assert last_alert(mqtt_mock, alert_id)["image"] is not None
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_reconnect_republishes_alerts(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    (alert_id,) = (await send(hass)).values()
    mqtt_mock.async_publish.reset_mock()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await hass.async_block_till_done()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert topic_publishes(mqtt_mock, f"alert/{alert_id}")


async def test_an_oversized_alert_is_not_published(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    profile = json.loads(json.dumps(tender_profile))
    profile["limits"]["max_payload"] = 300
    await setup(hass, profile, config(("home", [])))
    mqtt_mock.async_publish.reset_mock()
    (alert_id,) = (await send(hass, message="x" * 1000)).values()
    assert not topic_publishes(mqtt_mock, f"alert/{alert_id}")
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_unread_count_follows_adds_and_acknowledgments(
    hass: HomeAssistant, mqtt_mock: Any, device: Any
) -> None:
    ids = []
    for i in range(3):
        ids += (await send(hass, tag=f"t{i}")).values()
    assert device.alerts.unread == 3
    await hass.services.async_call(
        DOMAIN, "acknowledge_alert", {"alert_id": ids[0]}, blocking=True
    )
    await cmd(hass, mqtt_mock, {"req": "r", "ack": ids[1]})
    assert device.alerts.unread == 1


async def test_a_refresh_does_not_reload_bitmaps_already_published(
    hass: HomeAssistant, mqtt_mock: Any, device: Any, aioclient_mock: Any
) -> None:
    from homeassistant.helpers.storage import Store

    aioclient_mock.get("http://cam.local/s.png", content=png("blue", (120, 90)))
    (alert_id,) = (await send(hass, image_url="http://cam.local/s.png")).values()
    assert topic_publishes(mqtt_mock, f"alert/{alert_id}/image")
    load = Store.async_load
    keys: list[str] = []

    async def watched(self: Store[Any]) -> Any:
        keys.append(self.key)
        return await load(self)

    with patch.object(Store, "async_load", watched):
        await device.alerts.async_publish_all()
    assert not [k for k in keys if k.endswith(f"alert_{alert_id}")]
