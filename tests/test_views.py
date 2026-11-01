"""Dashboard saves reach the device as a view definition."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.components import persistent_notification as pn
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.roundhouse import codec, layout, lovelace_io
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS

from .conftest import make_entry, vector

PREFIX = "roundhouse/tender01/"


def tiles(n: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"type": "tile", "entity": f"light.l{i}"} for i in range(start, start + n)]


def config(*views: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"views": [{"path": p, "title": p.title(), "cards": c} for p, c in views]}


async def advance(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


async def save(
    hass: HomeAssistant, cfg: dict[str, Any], slug: str = "tender-panel"
) -> None:
    await hass.data[LOVELACE_DATA].dashboards[slug].async_save(cfg)
    await hass.async_block_till_done()


def views_publishes(mqtt_mock: Any) -> list[dict[str, Any]]:
    return [
        json.loads(c.args[1])
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "views" and c.args[1]
    ]


async def setup(
    hass: HomeAssistant,
    profile: dict[str, Any],
    cfg: dict[str, Any] | None,
    *,
    entry: MockConfigEntry | None = None,
) -> MockConfigEntry:
    """Create the dashboard (with `cfg`), then set the entry up."""
    if cfg is None:  # a dashboard nobody has saved: auto-generated
        await lovelace_io._collection(hass).async_create_item(
            {
                "url_path": "tender-panel",
                "title": "Tender",
                "show_in_sidebar": True,
                "require_admin": False,
            }
        )
    else:
        await lovelace_io.async_ensure_dashboard(hass, "tender-panel", "Tender")
        await save(hass, cfg)
    entry = entry or make_entry(profile)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_views_and_meta_are_published(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
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
    assert payload["snapshot_view"] == "home"  # Tender sleeps
    assert payload["skipped"] == 0
    meta = [
        json.loads(c.args[1])
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "meta"
    ][-1]
    assert meta["views_hash"] == layout.definition_hash(payload)
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_save_republishes_after_the_wait(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert len(views_publishes(mqtt_mock)) == 1

    await save(hass, config(("home", tiles(3))))
    # the helper adds up to 0.5 s of slack
    await advance(hass, lovelace_io.UPDATE_WAIT - 1.0)
    assert len(views_publishes(mqtt_mock)) == 1  # still waiting
    await advance(hass, lovelace_io.UPDATE_WAIT + 0.5)
    assert len(views_publishes(mqtt_mock)) == 2
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 3


async def test_saves_inside_the_wait_digest_once(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    base = len(views_publishes(mqtt_mock))
    for n in (2, 3, 4):
        await save(hass, config(("home", tiles(n))))
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert len(views_publishes(mqtt_mock)) == base + 1
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 4


async def test_unchanged_content_is_not_republished(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    cfg = config(("home", tiles(2)))
    await setup(hass, tender_profile, cfg)
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await save(hass, cfg)
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert len(views_publishes(mqtt_mock)) == 1


async def test_other_dashboards_are_ignored(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await lovelace_io.async_ensure_dashboard(hass, "other-panel", "Other")
    real = lovelace_io.async_load_dashboard
    with patch.object(lovelace_io, "async_load_dashboard", wraps=real) as loader:
        await save(hass, config(("x", tiles(5))), "other-panel")
        await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    loader.assert_not_called()


async def test_overflow_keeps_the_last_good_definition(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    notified: dict[str, Any] = {}

    def on_notification(kind: Any, items: dict[str, Any]) -> None:
        if kind == pn.UpdateType.REMOVED:
            for key in items:
                notified.pop(key, None)
        else:
            notified.update(items)

    pn.async_register_callback(hass, on_notification)
    await setup(hass, tender_profile, config(("home", tiles(3))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)

    await save(hass, config(("home", tiles(18))))  # capacity is 15
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 3

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "overflow_tender01_home")
    assert issue is not None
    assert issue.translation_placeholders == {
        "device": "tender01",
        "view": "Home",
        "excess": "3",
        "capacity": "15",
    }
    assert "overflow_tender01_home" in notified
    assert "remove 3 tile(s)" in notified["overflow_tender01_home"]["message"]
    assert issue.translation_key == "view_overflow"
    assert "keeps the last version" in notified["overflow_tender01_home"]["message"]

    await save(hass, config(("home", tiles(15))))  # fits again
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 15
    assert views_publishes(mqtt_mock)[-1]["views"][0]["layout"] == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, "overflow_tender01_home") is None
    assert "overflow_tender01_home" not in notified


async def test_new_overflowing_view_does_not_appear(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    notified: dict[str, Any] = {}
    pn.async_register_callback(hass, lambda _kind, items: notified.update(items))
    await setup(hass, tender_profile, config(("a", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await save(hass, config(("a", tiles(2)), ("b", tiles(16))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    paths = [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]]
    assert paths == ["a"]
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "overflow_tender01_b")
    assert issue is not None
    # The view never fitted, so nothing claims the device keeps a version.
    assert issue.translation_key == "view_overflow_hidden"
    message = notified["overflow_tender01_b"]["message"]
    assert "does not show this view" in message and "keeps" not in message


async def test_last_good_survives_a_restart(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", tiles(3))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await save(hass, config(("home", tiles(18))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)

    mqtt_mock.async_publish.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 3
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_stored_definitions_are_dropped_when_the_profile_changes(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    entry = await setup(hass, tender_profile, config(("home", tiles(3))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await save(hass, config(("home", tiles(18))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert len(views_publishes(mqtt_mock)[-1]["views"][0]["tiles"]) == 3

    # A device with other layouts cannot use the old layout index.
    wall = vector("announce", "wall-panel")["payload"]
    hass.config_entries.async_update_entry(entry, data={**entry.data, "profile": wall})
    await hass.async_block_till_done()
    assert views_publishes(mqtt_mock)[-1]["views"] == []
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_removed_dashboard_views_leave_the_device(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("a", tiles(1)), ("b", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    await save(hass, config(("b", tiles(1))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert [v["path"] for v in views_publishes(mqtt_mock)[-1]["views"]] == ["b"]


async def test_strategy_dashboard_raises_an_issue_and_publishes_nothing(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, None)  # created, never saved: auto-generated
    (payload,) = views_publishes(mqtt_mock)
    assert payload == {"views": [], "snapshot_view": None, "skipped": 0}
    assert ir.async_get(hass).async_get_issue(DOMAIN, "strategy_tender01") is not None

    await save(hass, config(("home", tiles(1))))
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "strategy_tender01") is None
    assert len(views_publishes(mqtt_mock)[-1]["views"]) == 1
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_explicit_strategy_config_counts_as_strategy(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, {"strategy": {"type": "original-states"}})
    assert ir.async_get(hass).async_get_issue(DOMAIN, "strategy_tender01") is not None
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_deleted_dashboard_raises_an_issue_and_empties_the_device(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", tiles(2))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    collection = lovelace_io._collection(hass)
    await collection.async_delete_item("tender_panel")
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deleted_tender01") is not None
    assert views_publishes(mqtt_mock)[-1] == {
        "views": [],
        "snapshot_view": None,
        "skipped": 0,
    }


async def test_skipped_cards_are_counted_in_the_payload(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    cards = [
        *tiles(1),
        {"type": "markdown", "content": "x"},
        {"type": "weather-forecast"},
    ]
    await setup(hass, tender_profile, config(("home", cards)))
    assert views_publishes(mqtt_mock)[-1]["skipped"] == 2
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_wall_panel_gets_its_own_layouts_and_no_snapshot_view(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None
) -> None:
    wall = vector("announce", "wall-panel")["payload"]
    entry = make_entry(wall, "tender01", "tender-panel")  # same prefix for the helper
    await setup(hass, wall, config(("home", tiles(7))), entry=entry)
    payload = views_publishes(mqtt_mock)[-1]
    assert payload["views"][0]["layout"] == 1  # 7 tiles need the 4-column layout
    assert payload["snapshot_view"] is None
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_rename_in_the_registry_republishes_names(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    registry = er.async_get(hass)
    reg_entry = registry.async_get_or_create(
        "light", "test", "l0", suggested_object_id="l0"
    )
    hass.states.async_set(reg_entry.entity_id, "on", {"friendly_name": "Old"})
    await setup(hass, tender_profile, config(("home", tiles(1))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert views_publishes(mqtt_mock)[-1]["views"][0]["tiles"][0]["name"] == "Old"

    hass.states.async_set(reg_entry.entity_id, "on", {"friendly_name": "New"})
    registry.async_update_entity(reg_entry.entity_id, name="New")
    await hass.async_block_till_done()
    await advance(hass, lovelace_io.UPDATE_WAIT + 1)
    assert views_publishes(mqtt_mock)[-1]["views"][0]["tiles"][0]["name"] == "New"
