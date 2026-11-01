"""The preview websocket and the panel registration."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.roundhouse import codec, layout, lovelace_io
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS

from .conftest import make_entry, vector
from .test_views import advance, config, save, setup, tiles


@pytest.fixture
async def lovelace(hass: HomeAssistant) -> None:
    """Lovelace with a real HTTP server and websocket API, for a real client."""
    hass.config.components.update({"auth", "onboarding", "frontend", "api"})
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})


def cards(*entities: str) -> list[dict[str, Any]]:
    return [{"type": "tile", "entity": e} for e in entities]


async def subscribe(client: Any, device_id: str = "tender01") -> int:
    await client.send_json_auto_id(
        {"type": "roundhouse/preview/subscribe", "device_id": device_id}
    )
    reply = await client.receive_json()
    assert reply["success"], reply
    return int(reply["id"])


async def event(client: Any) -> dict[str, Any]:
    async with asyncio.timeout(5):  # fail instead of hanging when nothing is sent
        msg = await client.receive_json()
    assert msg["type"] == "event", msg
    return msg["event"]  # type: ignore[no-any-return]


async def test_the_first_message_is_a_snapshot_of_the_device(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    hass.states.async_set(
        "light.l0", "on", {"friendly_name": "Lamp", "brightness": 204}
    )
    hass.states.async_set("lock.door", "locked")
    await setup(hass, tender_profile, config(("home", cards("light.l0", "lock.door"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    snap = await event(client)
    assert snap["type"] == "snapshot" and snap["device_id"] == "tender01"
    assert snap["profile"] == tender_profile
    assert snap["dashboard"] == "config"
    (view,) = snap["views"]
    assert (view["path"], view["layout"], view["count"], view["capacity"]) == (
        "home",
        0,
        2,
        15,
    )
    assert view["overflow"] is False and view["published"] is True
    assert [t["entity_id"] for t in view["tiles"]] == ["light.l0", "lock.door"]
    # The states are what the device receives, icons included.
    assert snap["states"]["light.l0"]["text"] == "On · 80%"
    assert snap["states"]["lock.door"]["icon"] == "mdi:lock"
    assert set(snap["icons"]) == {"mdi:lightbulb", "mdi:lock"}
    px = tender_profile["icon_px"]
    mask = base64.b64decode(snap["icons"]["mdi:lock"])
    assert codec.decode_bitmap("mask4", px, px, mask)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_save_pushes_a_new_snapshot_within_the_budget(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    assert len((await event(client))["views"][0]["tiles"]) == 1

    started = time.perf_counter()
    await save(hass, config(("home", cards("light.l0", "light.l1", "light.l2"))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    snap = await event(client)
    assert len(snap["views"][0]["tiles"]) == 3
    # The 2 s wait of the digest is fake time here; the rest takes no time at all.
    assert (
        time.perf_counter() - started < 1
    )  # the whole path is far inside its 3 s budget
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_an_overflowing_view_is_included_and_marked(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(3))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    await event(client)

    await save(hass, config(("home", tiles(18)), ("new", tiles(16))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    snap = await event(client)
    home, new = snap["views"]
    # Both overflow; neither is published as digested, but "home" still shows its
    # last good definition on the device.
    assert (home["overflow"], home["count"], home["capacity"], home["layout"]) == (
        True,
        18,
        15,
        None,
    )
    assert home["published"] is True
    assert len(home["tiles"]) == 18  # the preview shows every tile, to mark the excess
    assert (new["overflow"], new["published"], new["count"]) == (True, False, 16)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_state_change_pushes_a_state_message(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    hass.states.async_set("light.l0", "off")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    assert (await event(client))["states"]["light.l0"]["on"] is False
    hass.states.async_set("light.l0", "on", {"brightness": 255})
    await hass.async_block_till_done()
    msg = await event(client)
    assert msg["type"] == "state" and msg["entity_id"] == "light.l0"
    assert (msg["state"]["text"], msg["state"]["on"]) == ("On · 100%", True)
    assert "mdi:lightbulb" in msg["icons"]  # the new icon travels with the change
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_entities_outside_the_views_send_nothing(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    await event(client)
    hass.states.async_set("switch.other", "on")
    await hass.async_block_till_done()
    hass.states.async_set("light.l0", "on")
    await hass.async_block_till_done()
    assert (await event(client))["entity_id"] == "light.l0"  # the first message after
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_an_auto_generated_dashboard_previews_as_empty(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, None)
    client = await hass_ws_client(hass)
    await subscribe(client)
    snap = await event(client)
    assert snap["dashboard"] == "strategy" and snap["views"] == []
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_wall_panel_snapshot_carries_its_own_profile(
    hass: HomeAssistant, hass_ws_client: Any, mqtt_mock: Any, lovelace: None
) -> None:
    wall = vector("announce", "wall-panel")["payload"]
    entry = make_entry(wall, "wall01", "tender-panel")
    await setup(hass, wall, config(("home", tiles(7))), entry=entry)
    client = await hass_ws_client(hass)
    await subscribe(client, "wall01")
    snap = await event(client)
    assert snap["profile"]["display"] == {
        "width": 800,
        "height": 480,
        "format": "rgb565",
    }
    assert snap["views"][0]["layout"] == 1 and snap["views"][0]["capacity"] == 8
    px = wall["icon_px"]
    assert all(
        len(base64.b64decode(m)) == px * ((px + 1) // 2) for m in snap["icons"].values()
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_device_list(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "roundhouse/preview/devices"})
    reply = await client.receive_json()
    assert reply["success"] and reply["result"] == [
        {"device_id": "tender01", "model": "tender", "title": "Tender tender01"}
    ]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_an_unknown_device_is_an_error(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "roundhouse/preview/subscribe", "device_id": "nope"}
    )
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "not_found"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


@pytest.mark.parametrize(
    "command",
    [
        {"type": "roundhouse/preview/devices"},
        {"type": "roundhouse/preview/subscribe", "device_id": "tender01"},
    ],
)
async def test_the_preview_is_admin_only(
    hass: HomeAssistant,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
    command: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(command)
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "unauthorized"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_unsubscribing_stops_the_stream(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from custom_components.roundhouse.const import views_signal

    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    sub_id = await subscribe(client)
    await event(client)
    await client.send_json_auto_id(
        {"type": "unsubscribe_events", "subscription": sub_id}
    )
    assert (await client.receive_json())["success"]
    async_dispatcher_send(hass, views_signal("tender01"))
    hass.states.async_set("light.l0", "on")
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": "ping"})
    assert (await client.receive_json())["type"] == "pong"  # nothing came before it
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_two_panels_follow_the_same_device(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    a, b = await hass_ws_client(hass), await hass_ws_client(hass)
    await subscribe(a)
    await subscribe(b)
    await event(a)
    await event(b)
    hass.states.async_set("light.l0", "on")
    await hass.async_block_till_done()
    assert (await event(a))["entity_id"] == (await event(b))["entity_id"] == "light.l0"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_preview_does_not_publish_anything_to_the_broker(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(
        hass, tender_profile, config(("home", tiles(18)))
    )  # an overflowing view
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    mqtt_mock.async_publish.reset_mock()
    client = await hass_ws_client(hass)
    await subscribe(client)
    await event(client)
    assert mqtt_mock.async_publish.call_count == 0
    assert layout.capacity(tender_profile) == 15


# --- registration ------------------------------------------------------------------


async def test_the_panel_is_registered_as_an_admin_only_custom_panel(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    panel = hass.data["frontend_panels"]["roundhouse"]
    assert panel.require_admin is True
    assert (
        panel.sidebar_title == "Roundhouse"
        and panel.sidebar_icon == "mdi:view-dashboard"
    )
    config_ = panel.config["_panel_custom"]
    assert config_["name"] == "roundhouse-panel"
    assert config_["module_url"].startswith("/roundhouse_panel/panel.js?v=")
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_panel_files_are_served(
    hass: HomeAssistant,
    hass_client: Any,
    mqtt_mock: Any,
    lovelace: None,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_client()
    for name in ("panel.js", "geometry.js", "mask.js", "state.js", "draw.js"):
        response = await client.get(f"/roundhouse_panel/{name}")
        assert response.status == 200, name
        assert "javascript" in response.headers["Content-Type"]
        assert (await response.text()).strip()
    assert (await client.get("/roundhouse_panel/../manifest.json")).status in (403, 404)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_second_setup_does_not_register_the_panel_again(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    from custom_components.roundhouse.panelreg import async_register_panel

    await setup(hass, tender_profile, config(("home", [])))
    assert await async_register_panel(hass) is True  # idempotent, no error
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_without_a_frontend_nothing_is_registered(hass: HomeAssistant) -> None:
    from custom_components.roundhouse.panelreg import async_register_panel

    assert await async_register_panel(hass) is False


def test_the_panel_imports_only_files_it_ships() -> None:
    import re

    from custom_components.roundhouse.panelreg import PANEL_DIR

    names = {p.name for p in PANEL_DIR.glob("*.js")}
    assert {"panel.js", "geometry.js", "mask.js", "state.js", "draw.js"} <= names
    for path in PANEL_DIR.glob("*.js"):
        for target in re.findall(r"from \"\./([\w.-]+)\"", path.read_text()):
            assert target in names, f"{path.name} imports {target}"
    assert DOMAIN == "roundhouse"
    assert (
        json.loads((PANEL_DIR.parent / "manifest.json").read_text())["domain"] == DOMAIN
    )
