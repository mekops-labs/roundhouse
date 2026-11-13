"""Stored views reach the device as a view definition."""

from __future__ import annotations

from typing import Any

from homeassistant.components import persistent_notification as pn
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from custom_components.roundhouse import codec, issues, layout
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS, store_key
from custom_components.roundhouse.viewsync import NAME_WAIT

from .conftest import make_entry, vector
from .helpers import (
    PREFIX,
    advance,
    config,
    resolve,
    save,
    setup,
    the_device,
    tiles,
    views_publishes,
)


async def test_a_new_entry_starts_with_one_empty_view(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, None)
    (payload,) = views_publishes(mqtt_mock)
    (view,) = payload["views"]
    assert (view["title"], view["tiles"]) == ("Home", [])
    assert view["layout"] == layout.densest(tender_profile)
    assert payload["snapshot_view"] == view["path"]  # Tender sleeps
    assert the_device(hass).views.revision == 1
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_views_and_meta_are_published(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on", {"friendly_name": "Ceiling"})
    await setup(hass, tender_profile, config(("home", tiles(3))))
    (payload,) = views_publishes(mqtt_mock)
    assert codec.decode("views", codec.encode(payload)) == payload
    (view,) = payload["views"]
    assert (view["path"], view["layout"], view["tiles"][0]["name"]) == (
        "home",
        0,
        "Ceiling",
    )
    assert payload["snapshot_view"] == "home"
    assert payload["skipped"] == 0
    meta = codec.decode(
        "meta",
        [
            c.args[1]
            for c in mqtt_mock.async_publish.call_args_list
            if c.args[0] == PREFIX + "meta"
        ][-1],
    )
    assert meta["views_hash"] == layout.definition_hash(payload)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_save_publishes_at_once(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert len(views_publishes(mqtt_mock)) == 1

    result = await save(hass, config(("home", tiles(3))))
    assert result.ok and result.revision == 2
    assert len(views_publishes(mqtt_mock)) == 2
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 3


async def test_unchanged_content_is_not_republished(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    views = config(("home", tiles(2)))
    await setup(hass, tender_profile, views)
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert (await save(hass, views)).ok
    assert len(views_publishes(mqtt_mock)) == 1


async def test_a_save_that_breaks_a_rule_changes_nothing(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    device = the_device(hass)

    bad = config(("home", tiles(2)), ("big", tiles(16)), layout=1)
    bad[0]["tiles"].append({"entity_id": "weather.home"})
    bad[1]["layout"] = 0  # 16 tiles do not fit the 8 slots of layout 0
    result = await save(hass, bad)
    assert not result.ok and not result.conflict
    assert {(e.view, e.code) for e in result.errors} == {
        (0, "unsupported_domain"),
        (1, "too_many_tiles"),
    }
    assert device.views.revision == 1
    assert len(device.views.views) == 1
    assert len(views_publishes(mqtt_mock)) == 1


async def test_a_stale_revision_is_a_conflict(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    device = the_device(hass)
    result = await device.views.async_save(
        0, resolve(tender_profile, config(("home", tiles(3)))), None
    )
    assert result.conflict and result.revision == 1
    assert len(views_publishes(mqtt_mock)) == 1


async def test_a_new_view_gets_a_path_and_everything_survives_a_restart(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    views = config(("home", tiles(1)), ("x", tiles(2, 5)))
    del views[1]["path"]
    result = await save(hass, views, snapshot="home")
    assert result.ok
    new_path = result.views[1]["path"]
    assert new_path and new_path != "home"

    mqtt_mock.async_publish.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    device = the_device(hass)
    assert device.views.revision == 2
    assert [v["path"] for v in device.views.views] == ["home", new_path]
    assert device.views.snapshot == "home"
    assert [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]] == [
        "home",
        new_path,
    ]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_snapshot_view_is_the_chosen_one(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("a", tiles(1)), ("b", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert views_publishes(mqtt_mock)[-1]["snapshot_view"] == "a"
    assert (await save(hass, config(("a", tiles(1)), ("b", tiles(1))), "b")).ok
    assert views_publishes(mqtt_mock)[-1]["snapshot_view"] == "b"


async def test_the_first_store_version_is_dropped(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    old: Store[dict[str, Any]] = Store(hass, 1, store_key("tender01", "views"))
    await old.async_save({"fingerprint": "x", "views": [{"path": "dash", "tiles": []}]})
    await setup(hass, tender_profile, None)
    device = the_device(hass)
    assert [v["title"] for v in device.views.views] == ["Home"]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_wall_panel_gets_its_own_layouts_and_no_snapshot_view(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    wall = vector("announce", "wall-panel")["payload"]
    await setup(hass, wall, config(("home", tiles(7))), entry=make_entry(wall))
    payload = views_publishes(mqtt_mock)[-1]
    assert payload["views"][0]["layout"] == 1  # 7 tiles need the larger layout
    assert payload["snapshot_view"] is None
    assert not (await save(hass, config(("home", tiles(1))), "home")).ok
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_view_the_profile_cannot_show_is_left_out_with_an_issue(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    notified: dict[str, Any] = {}

    def on_notification(kind: Any, items: dict[str, Any]) -> None:
        if kind == pn.UpdateType.REMOVED:
            for key in items:
                notified.pop(key, None)
        else:
            notified.update(items)

    pn.async_register_callback(hass, on_notification)
    entry = await setup(
        hass, tender_profile, config(("small", tiles(2)), ("big", tiles(14)))
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]] == [
        "small",
        "big",
    ]

    # The wall panel's layouts hold 6 and 8: "big" (layout 1, 14 tiles) cannot fit.
    wall = vector("announce", "wall-panel")["payload"]
    hass.config_entries.async_update_entry(entry, data={**entry.data, "profile": wall})
    await hass.async_block_till_done()
    assert [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]] == ["small"]

    issue_id = issues.overflow_issue_id("tender01", "big")
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_key == "view_overflow"
    assert issue.translation_placeholders == {
        "device": "tender01",
        "view": "Big",
        "excess": "6",
        "capacity": "8",
    }
    message = notified[issue_id]["message"]
    assert "remove 6 tile(s)" in message and "does not show this view" in message
    assert [(o.path, o.excess) for o in the_device(hass).views.overflows] == [
        ("big", 6)
    ]

    # Removing tiles in the editor fixes it; the issue and notification go.
    device = the_device(hass)
    fixed = resolve(wall, config(("small", tiles(2)), ("big", tiles(8))))
    result = await device.views.async_save(device.views.revision, fixed, None)
    assert result.ok
    assert [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]] == [
        "small",
        "big",
    ]
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert issue_id not in notified
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_view_whose_layout_is_gone_gets_its_own_issue(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", tiles(2)), layout=1))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    one_layout = {**tender_profile, "layouts": tender_profile["layouts"][:1]}
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "profile": one_layout}
    )
    await hass.async_block_till_done()
    assert views_publishes(mqtt_mock)[-1]["views"] == []
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, issues.overflow_issue_id("tender01", "home")
    )
    assert issue is not None and issue.translation_key == "view_layout_gone"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_renamed_entity_keeps_its_tile(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    registry = er.async_get(hass)
    reg_entry = registry.async_get_or_create(
        "light", "test", "l0", suggested_object_id="l0"
    )
    hass.states.async_set(reg_entry.entity_id, "on")
    await setup(hass, tender_profile, config(("home", [{"entity_id": "light.l0"}])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    device = the_device(hass)
    assert device.views.revision == 1

    registry.async_update_entity(reg_entry.entity_id, new_entity_id="light.porch")
    await hass.async_block_till_done()
    assert [t["entity_id"] for t in device.views.views[0]["tiles"]] == ["light.porch"]
    assert device.views.revision == 2
    assert views_publishes(mqtt_mock)[-1]["views"][0]["tiles"][0]["entity_id"] == (
        "light.porch"
    )
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_new_friendly_name_republishes_after_a_wait(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    registry = er.async_get(hass)
    reg_entry = registry.async_get_or_create(
        "light", "test", "l0", suggested_object_id="l0"
    )
    hass.states.async_set(reg_entry.entity_id, "on", {"friendly_name": "Old"})
    await setup(hass, tender_profile, config(("home", [{"entity_id": "light.l0"}])))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert views_publishes(mqtt_mock)[-1]["views"][0]["tiles"][0]["name"] == "Old"

    hass.states.async_set(reg_entry.entity_id, "on", {"friendly_name": "New"})
    registry.async_update_entity(reg_entry.entity_id, name="New")
    await hass.async_block_till_done()
    await advance(hass, NAME_WAIT + 1)
    assert views_publishes(mqtt_mock)[-1]["views"][0]["tiles"][0]["name"] == "New"
    assert the_device(hass).views.revision == 1  # a name is not a stored change


def test_overflow_issue_ids_never_collide() -> None:
    ids = {
        issues.overflow_issue_id(device, path)
        for device, path in (
            ("a", "b-x"),
            ("a_b", "x"),
            ("a", "b_x"),
            ("a-b", "x"),
        )
    }
    assert len(ids) == 4
