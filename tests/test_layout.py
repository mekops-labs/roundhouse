"""Fitting views to a profile, for the Tender and wall-panel profiles."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import codec
from custom_components.roundhouse import layout as lo

from .conftest import vector


def view(path: str, n: int, layout: int = 0) -> dict[str, Any]:
    tiles = [{"entity_id": f"light.l{i}"} for i in range(n)]
    return {"path": path, "title": path.title(), "layout": layout, "tiles": tiles}


def friendly(entity_id: str) -> str | None:
    return entity_id.upper()


@pytest.fixture(params=["tender", "wall-panel"])
def profile(request: pytest.FixtureRequest) -> dict[str, Any]:
    return vector("announce", request.param)["payload"]  # type: ignore[no-any-return]


def test_capacity_is_the_densest_layout(profile: dict[str, Any]) -> None:
    assert lo.capacity(profile) == max(len(x["slots"]) for x in profile["layouts"])


def test_the_densest_layout_need_not_come_last(profile: dict[str, Any]) -> None:
    flipped = {**profile, "layouts": profile["layouts"][::-1]}
    most = max(len(x["slots"]) for x in profile["layouts"])
    assert lo.densest(flipped) == 0
    assert lo.capacity(flipped) == most
    published, overflows = lo.fit([view("home", most)], flipped, friendly)
    assert not overflows
    assert published[0]["layout"] == 0


def test_tender_capacities() -> None:
    tender = vector("announce", "tender")["payload"]
    assert [len(x["slots"]) for x in tender["layouts"]] == [8, 15]
    assert lo.capacity(tender) == 15


def test_wall_panel_capacities() -> None:
    wall = vector("announce", "wall-panel")["payload"]
    assert [len(x["slots"]) for x in wall["layouts"]] == [6, 8]


def test_a_view_that_fits_is_published_with_resolved_tiles(
    profile: dict[str, Any],
) -> None:
    published, overflows = lo.fit([view("home", 2)], profile, friendly)
    assert overflows == []
    assert published[0]["tiles"][0] == {
        "entity_id": "light.l0",
        "name": "LIGHT.L0",
        "kind": "toggle",
        "domain": "light",
    }


def test_the_layout_of_a_view_is_kept(profile: dict[str, Any]) -> None:
    last = len(profile["layouts"]) - 1
    published, _ = lo.fit([view("a", 1, last)], profile, friendly)
    assert published[0]["layout"] == last


def test_a_view_over_its_layout_is_left_out(profile: dict[str, Any]) -> None:
    slots = len(profile["layouts"][0]["slots"])
    published, overflows = lo.fit(
        [view("ok", 1), view("big", slots + 2)], profile, friendly
    )
    assert [v["path"] for v in published] == ["ok"]
    [o] = overflows
    assert (o.path, o.tiles, o.capacity, o.excess, o.layout_gone) == (
        "big",
        slots + 2,
        slots,
        2,
        False,
    )


def test_a_view_whose_layout_is_gone_is_left_out(profile: dict[str, Any]) -> None:
    gone = len(profile["layouts"])
    published, overflows = lo.fit([view("a", 1, gone)], profile, friendly)
    assert published == []
    [o] = overflows
    assert o.layout_gone
    assert o.capacity == lo.capacity(profile)
    assert o.excess == 0  # it would fit another layout


def test_the_published_payload_is_valid_contract(profile: dict[str, Any]) -> None:
    published, _ = lo.fit([view("home", 3)], profile, friendly)
    payload = {"views": published, "snapshot_view": "home", "skipped": 0}
    assert codec.decode("views", codec.encode(payload)) == payload


def test_snapshot_view_only_for_devices_that_sleep() -> None:
    sleeper = vector("announce", "tender")["payload"]
    awake = vector("announce", "wall-panel")["payload"]
    published = [{"path": "a"}, {"path": "b"}]
    assert lo.snapshot_view(published, sleeper, "b") == "b"
    assert lo.snapshot_view(published, sleeper, "gone") == "a"
    assert lo.snapshot_view(published, sleeper, None) == "a"
    assert lo.snapshot_view([], sleeper, "a") is None
    assert lo.snapshot_view(published, awake, "a") is None


def test_the_hash_ignores_key_order_and_follows_content() -> None:
    a = {"views": [], "snapshot_view": None, "skipped": 0}
    b = {"skipped": 0, "snapshot_view": None, "views": []}
    assert lo.definition_hash(a) == lo.definition_hash(b)
    assert lo.definition_hash(a) != lo.definition_hash({**a, "snapshot_view": "x"})
