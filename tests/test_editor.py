"""The editor's websocket commands and the panel registration."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.roundhouse import codec, editor, layout, viewrules
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS
from custom_components.roundhouse.panelreg import PANEL_DIR

from .conftest import make_entry, vector
from .helpers import advance, cards, config, resolve, save, setup, the_device, tiles


@pytest.fixture
async def frontend(hass: HomeAssistant) -> None:
    """The parts of a real instance the panel registration needs."""
    hass.config.components.update({"auth", "onboarding", "frontend", "api"})
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})


PANEL_FILES = (
    "panel.js",
    "dialogs.js",
    "dom.js",
    "draft.js",
    "draw.js",
    "geometry.js",
    "mask.js",
    "rules.js",
    "state.js",
    "version.js",
)


async def subscribe(client: Any, device_id: str = "tender01") -> int:
    await client.send_json_auto_id(
        {"type": "roundhouse/editor/subscribe", "device_id": device_id}
    )
    reply = await client.receive_json()
    assert reply["success"], reply
    return int(reply["id"])


async def event(client: Any) -> dict[str, Any]:
    async with asyncio.timeout(5):  # fail instead of hanging when nothing is sent
        msg = await client.receive_json()
    assert msg["type"] == "event", msg
    return msg["event"]  # type: ignore[no-any-return]


async def call(client: Any, command: dict[str, Any]) -> dict[str, Any]:
    await client.send_json_auto_id(command)
    reply = await client.receive_json()
    assert reply["success"], reply
    return reply["result"]  # type: ignore[no-any-return]


async def call_with_events(
    client: Any, command: dict[str, Any], events: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Send a command and read its result and the events it caused, in any order."""
    await client.send_json_auto_id(command)
    result: dict[str, Any] | None = None
    seen: list[dict[str, Any]] = []
    for _ in range(events + 1):
        async with asyncio.timeout(5):
            msg = await client.receive_json()
        if msg["type"] == "result":
            assert msg["success"], msg
            result = msg["result"]
        else:
            seen.append(msg["event"])
    assert result is not None
    return result, seen


def save_command(
    revision: int, views: list[dict[str, Any]], snapshot: str | None = None
) -> dict[str, Any]:
    return {
        "type": "roundhouse/editor/save",
        "device_id": "tender01",
        "revision": revision,
        "views": views,
        "snapshot": snapshot,
    }


async def test_the_first_message_is_a_snapshot_of_the_device(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
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
    assert snap["revision"] == 1 and snap["snapshot"] is None
    (view,) = snap["views"]
    assert (view["path"], view["title"], view["layout"]) == ("home", "Home", 0)
    assert view["overflow"] is None
    assert [t["entity_id"] for t in view["tiles"]] == ["light.l0", "lock.door"]
    # The states are what the device receives, icons included.
    assert snap["states"]["light.l0"]["text"] == "On · 80%"
    assert snap["states"]["lock.door"]["icon"] == "mdi:lock"
    assert set(snap["icons"]) == {"mdi:lightbulb", "mdi:lock"}
    px = tender_profile["icon_px"]
    mask = base64.b64decode(snap["icons"]["mdi:lock"])
    assert codec.decode_bitmap("mask4", px, px, mask)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_snapshot_carries_the_rules_of_the_editor(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, None)
    client = await hass_ws_client(hass)
    await subscribe(client)
    rules = (await event(client))["rules"]
    assert set(rules["domains"]) == viewrules.SUPPORTED_DOMAINS
    assert {"type": "hvac_mode", "values_attr": "hvac_modes"} in rules["controls"][
        "climate"
    ]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_save_pushes_a_new_snapshot_within_the_budget(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    assert len((await event(client))["views"][0]["tiles"]) == 1

    started = time.perf_counter()
    views = resolve(tender_profile, config(("home", cards("light.l0", "light.l1"))))
    result, [snap] = await call_with_events(client, save_command(1, views), 1)
    assert result["ok"] is True and result["revision"] == 2
    assert len(snap["views"][0]["tiles"]) == 2 and snap["revision"] == 2
    assert time.perf_counter() - started < 1  # Done to publish and page update
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_save_that_breaks_a_rule_returns_every_error(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    views = resolve(tender_profile, config(("home", [{"entity_id": "weather.x"}])))
    views[0]["title"] = ""
    result = await call(client, save_command(1, views))
    assert result["ok"] is False and result["error"] == "invalid"
    assert {(e["view"], e["tile"], e["code"]) for e in result["errors"]} == {
        (0, None, "bad_title"),
        (0, 0, "unsupported_domain"),
    }
    assert the_device(hass).views.revision == 1
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_stale_save_is_a_conflict_that_names_the_revision(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    views = resolve(tender_profile, config(("home", cards("light.l1"))))
    assert (await call(client, save_command(1, views)))["ok"] is True
    again = await call(client, save_command(1, views))
    assert again == {"ok": False, "error": "conflict", "revision": 2}
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_new_view_comes_back_with_its_path(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    views = resolve(tender_profile, config(("home", []), ("x", [])))
    del views[1]["path"]
    result = await call(client, save_command(1, views, "home"))
    assert result["ok"] is True
    assert result["views"][0]["path"] == "home"
    assert result["views"][1]["path"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_view_the_profile_cannot_show_is_marked_in_the_snapshot(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    entry = await setup(hass, tender_profile, config(("home", tiles(14))))
    wall = vector("announce", "wall-panel")["payload"]
    hass.config_entries.async_update_entry(entry, data={**entry.data, "profile": wall})
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await subscribe(client)
    (view,) = (await event(client))["views"]
    assert view["overflow"] == {
        "tiles": 14,
        "capacity": 8,
        "excess": 6,
        "layout_gone": False,
    }
    assert len(view["tiles"]) == 14  # the editor shows every tile, to mark the excess
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_render_command_renders_entities_not_saved_yet(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    hass.states.async_set("lock.door", "locked")
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    result = await call(
        client,
        {
            "type": "roundhouse/editor/render",
            "device_id": "tender01",
            "entities": {"lock.door": None, "light.l9": "mdi:ceiling-light"},
        },
    )
    assert result["states"]["lock.door"]["icon"] == "mdi:lock"
    assert result["states"]["light.l9"]["icon"] == "mdi:ceiling-light"
    assert set(result["icons"]) == {"mdi:lock", "mdi:ceiling-light"}
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_render_command_refuses_a_big_batch(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    entities = {f"light.l{i}": None for i in range(editor.MAX_RENDER + 1)}
    await client.send_json_auto_id(
        {
            "type": "roundhouse/editor/render",
            "device_id": "tender01",
            "entities": entities,
        }
    )
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "invalid_format"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_state_change_pushes_a_state_message(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
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


async def test_the_wall_panel_snapshot_carries_its_own_profile(
    hass: HomeAssistant, hass_ws_client: Any, mqtt_mock: Any
) -> None:
    wall = vector("announce", "wall-panel")["payload"]
    entry = make_entry(wall, "wall01")
    await setup(hass, wall, config(("home", tiles(7))), entry=entry)
    client = await hass_ws_client(hass)
    await subscribe(client, "wall01")
    snap = await event(client)
    assert snap["profile"]["display"] == {
        "width": 800,
        "height": 480,
        "format": "rgb565",
    }
    assert snap["views"][0]["layout"] == 1
    px = wall["icon_px"]
    assert all(
        len(base64.b64decode(m)) == px * ((px + 1) // 2) for m in snap["icons"].values()
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_device_list(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    assert await call(client, {"type": "roundhouse/devices"}) == [
        {"device_id": "tender01", "model": "tender", "title": "Tender tender01"}
    ]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


@pytest.mark.parametrize(
    "command",
    [
        {"type": "roundhouse/editor/subscribe", "device_id": "nope"},
        {"type": "roundhouse/editor/render", "device_id": "nope", "entities": {}},
        {
            "type": "roundhouse/editor/save",
            "device_id": "nope",
            "revision": 1,
            "views": [],
            "snapshot": None,
        },
    ],
)
async def test_an_unknown_device_is_an_error(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    command: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(command)
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "not_found"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


@pytest.mark.parametrize(
    "command",
    [
        {"type": "roundhouse/devices"},
        {"type": "roundhouse/editor/subscribe", "device_id": "tender01"},
        {"type": "roundhouse/editor/render", "device_id": "tender01", "entities": {}},
        {
            "type": "roundhouse/editor/save",
            "device_id": "tender01",
            "revision": 1,
            "views": [],
            "snapshot": None,
        },
    ],
)
async def test_the_editor_is_admin_only(
    hass: HomeAssistant,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
    command: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(command)
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "unauthorized"
    assert the_device(hass).views.revision == 1
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_unsubscribing_stops_the_stream(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
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


async def test_two_editors_follow_the_same_device(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    a, b = await hass_ws_client(hass), await hass_ws_client(hass)
    await subscribe(a)
    await subscribe(b)
    await event(a)
    await event(b)
    views = resolve(tender_profile, config(("home", cards("light.l0", "light.l1"))))
    result, _ = await call_with_events(a, save_command(1, views), 1)
    assert result["ok"] is True
    # Editor b learns of the save made in a, with the new revision.
    assert (await event(b))["revision"] == 2
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_subscribing_publishes_nothing_to_the_broker(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(3))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    mqtt_mock.async_publish.reset_mock()
    client = await hass_ws_client(hass)
    await subscribe(client)
    await event(client)
    assert mqtt_mock.async_publish.call_count == 0
    assert layout.capacity(tender_profile) == 15


async def test_the_editor_follows_the_device_through_a_reload(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    client = await hass_ws_client(hass)
    await subscribe(client)
    assert len((await event(client))["views"][0]["tiles"]) == 1

    # An options change reloads the entry and builds a new device runtime.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await save(hass, config(("home", cards("light.l0", "light.l1", "light.l2"))))
    counts = []
    while 3 not in counts:  # `event` fails after 5 s without a message
        snap = await event(client)
        if snap["type"] == "snapshot":
            counts.append(len(snap["views"][0]["tiles"]))
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_snapshot_that_finishes_late_is_not_sent(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    from unittest.mock import patch

    await setup(hass, tender_profile, config(("home", [])))
    gate, entered = asyncio.Event(), asyncio.Event()
    calls = 0

    async def build(_hass: HomeAssistant, _device: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        n = calls
        if n == 1:  # the older snapshot renders slowly
            entered.set()
            await gate.wait()
        return {"type": "snapshot", "views": [], "n": n}

    sent: list[dict[str, Any]] = []
    sub = editor.Subscription(hass, "tender01", sent.append)
    with patch.object(editor, "build_snapshot", build):
        older = hass.async_create_task(sub._push_snapshot())
        async with asyncio.timeout(5):
            await entered.wait()
        await sub._push_snapshot()
        gate.set()
        await older
    assert [m["n"] for m in sent] == [2]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


# --- registration -------------------------------------------------------------


async def test_the_panel_is_registered_as_an_admin_only_custom_panel(
    hass: HomeAssistant,
    frontend: None,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
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
    manifest = json.loads((PANEL_DIR.parent / "manifest.json").read_text())
    assert panel.config["version"] == manifest["version"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_panel_files_are_served(
    hass: HomeAssistant,
    frontend: None,
    hass_client: Any,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
) -> None:
    await setup(hass, tender_profile, config(("home", [])))
    client = await hass_client()
    for name in PANEL_FILES:
        response = await client.get(f"/roundhouse_panel/{name}")
        assert response.status == 200, name
        assert "javascript" in response.headers["Content-Type"]
        assert (await response.text()).strip()
    assert (await client.get("/roundhouse_panel/../manifest.json")).status in (403, 404)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_second_setup_does_not_register_the_panel_again(
    hass: HomeAssistant,
    frontend: None,
    mqtt_mock: Any,
    tender_profile: dict[str, Any],
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
    assert set(PANEL_FILES) <= names
    for path in PANEL_DIR.glob("*.js"):
        for target in re.findall(r"from \"\./([\w.-]+)\"", path.read_text()):
            assert target in names, f"{path.name} imports {target}"
    assert DOMAIN == "roundhouse"
    assert (
        json.loads((PANEL_DIR.parent / "manifest.json").read_text())["domain"] == DOMAIN
    )
