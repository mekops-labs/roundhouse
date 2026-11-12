"""Layout choice, overflow, and the views payload, for two profiles."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import codec
from custom_components.roundhouse import digest as dg
from custom_components.roundhouse import layout as lo

from .conftest import vector


def view(path: str, n: int) -> dg.DigestView:
    tiles = tuple(dg.Tile(f"light.l{i}", f"L{i}", "toggle", "light") for i in range(n))
    return dg.DigestView(path, path.title(), tiles)


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
    published, overflows = lo.merge([view("home", most)], {}, flipped)
    assert not overflows
    assert published[0]["layout"] == 0


def test_tender_capacities() -> None:
    tender = vector("announce", "tender")["payload"]
    assert [len(layout["slots"]) for layout in tender["layouts"]] == [8, 15]
    assert lo.capacity(tender) == 15


def test_wall_panel_capacities() -> None:
    wall = vector("announce", "wall-panel")["payload"]
    assert [len(layout["slots"]) for layout in wall["layouts"]] == [6, 8]


def test_first_layout_that_fits_is_chosen(profile: dict[str, Any]) -> None:
    first = len(profile["layouts"][0]["slots"])
    last = lo.capacity(profile)
    assert lo.choose_layout(profile, 0) == 0
    assert lo.choose_layout(profile, first) == 0
    assert lo.choose_layout(profile, first + 1) == 1
    assert lo.choose_layout(profile, last) == len(profile["layouts"]) - 1
    assert lo.choose_layout(profile, last + 1) is None


def test_fitting_views_are_published_with_their_layout() -> None:
    tender = vector("announce", "tender")["payload"]
    published, overflows = lo.merge([view("a", 8), view("b", 9)], {}, tender)
    assert [(v["path"], v["layout"], len(v["tiles"])) for v in published] == [
        ("a", 0, 8),
        ("b", 1, 9),
    ]
    assert overflows == []


def test_overflowing_view_without_history_is_left_out(profile: dict[str, Any]) -> None:
    cap = lo.capacity(profile)
    published, overflows = lo.merge([view("a", 1), view("big", cap + 3)], {}, profile)
    assert [v["path"] for v in published] == ["a"]
    (over,) = overflows
    assert (over.path, over.tiles, over.capacity, over.excess) == (
        "big",
        cap + 3,
        cap,
        3,
    )


def test_overflowing_view_keeps_its_last_good_definition(
    profile: dict[str, Any],
) -> None:
    cap = lo.capacity(profile)
    good, _ = lo.merge([view("a", 2)], {}, profile)
    old = {v["path"]: v for v in good}
    published, overflows = lo.merge([view("a", cap + 1), view("b", 1)], old, profile)
    assert published[0] == old["a"]
    assert [v["path"] for v in published] == ["a", "b"]
    assert [o.path for o in overflows] == ["a"]


def test_removed_views_disappear() -> None:
    tender = vector("announce", "tender")["payload"]
    good, _ = lo.merge([view("a", 1), view("b", 1)], {}, tender)
    old = {v["path"]: v for v in good}
    published, _ = lo.merge([view("b", 1)], old, tender)
    assert [v["path"] for v in published] == ["b"]


def test_snapshot_view_only_for_sleeping_devices() -> None:
    tender = vector("announce", "tender")["payload"]
    wall = vector("announce", "wall-panel")["payload"]
    published = [{"path": "a"}, {"path": "b"}]
    assert lo.snapshot_view(published, tender, "") == "a"
    assert lo.snapshot_view(published, tender, "b") == "b"
    assert lo.snapshot_view(published, tender, "gone") == "a"
    assert lo.snapshot_view([], tender, "") is None
    assert lo.snapshot_view(published, wall, "b") is None


def test_hash_changes_with_content_only() -> None:
    a = {"views": [{"path": "a"}], "snapshot_view": None, "skipped": 0}
    b = {"skipped": 0, "snapshot_view": None, "views": [{"path": "a"}]}
    c = {"views": [{"path": "b"}], "snapshot_view": None, "skipped": 0}
    assert lo.definition_hash(a) == lo.definition_hash(b)
    assert lo.definition_hash(a) != lo.definition_hash(c)


def test_profile_fingerprint_tracks_layouts() -> None:
    tender = vector("announce", "tender")["payload"]
    wall = vector("announce", "wall-panel")["payload"]
    assert lo.profile_fingerprint(tender) == lo.profile_fingerprint(
        dict(tender, fw="9")
    )
    assert lo.profile_fingerprint(tender) != lo.profile_fingerprint(wall)


def test_published_views_satisfy_the_contract(profile: dict[str, Any]) -> None:
    published, _ = lo.merge([view("a", 3), view("b", 0)], {}, profile)
    payload = {"views": published, "snapshot_view": "a", "skipped": 2}
    assert codec.decode("views", codec.encode(payload)) == payload
