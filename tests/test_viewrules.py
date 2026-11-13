"""The rules every saved set of views must pass."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import viewrules as vr

from .conftest import vector


@pytest.fixture(params=["tender", "wall-panel"])
def profile(request: pytest.FixtureRequest) -> dict[str, Any]:
    return vector("announce", request.param)["payload"]  # type: ignore[no-any-return]


def tile(entity_id: str = "light.kitchen", **extra: Any) -> dict[str, Any]:
    return {"entity_id": entity_id, **extra}


def view(
    path: str = "home", n: int = 1, layout: int = 0, title: str = "Home"
) -> dict[str, Any]:
    return {
        "path": path,
        "title": title,
        "layout": layout,
        "tiles": [tile(f"light.l{i}") for i in range(n)],
    }


def check(
    views: list[dict[str, Any]],
    profile: dict[str, Any],
    snapshot: str | None = None,
) -> list[vr.RuleError]:
    return vr.validate(views, snapshot, profile, icon_known=lambda n: n != "mdi:nope")


def codes(errors: list[vr.RuleError]) -> list[str]:
    return [e.code for e in errors]


def test_a_valid_set_of_views_has_no_errors(profile: dict[str, Any]) -> None:
    assert check([view(n=2)], profile) == []


def test_an_empty_set_of_views_is_valid(profile: dict[str, Any]) -> None:
    assert check([], profile) == []


@pytest.mark.parametrize(
    ("entity_id", "ok"),
    [
        ("light.kitchen", True),
        ("input_boolean.away", True),
        ("scene.movie", True),
        ("sensor.temp", True),
        ("binary_sensor.door", True),
        ("person.kamil", True),
        ("weather.home", False),
        ("device_tracker.phone", False),
        ("camera.gate", False),
        ("notaentity", False),
        ("light.", False),
    ],
)
def test_only_supported_domains_are_accepted(
    profile: dict[str, Any], entity_id: str, ok: bool
) -> None:
    views = [{**view(n=0), "tiles": [tile(entity_id)]}]
    assert (check(views, profile) == []) is ok


def test_an_error_names_its_view_and_tile(profile: dict[str, Any]) -> None:
    bad = {**view("b", n=0), "tiles": [tile(), tile("weather.home")]}
    [error] = check([view("a"), bad], profile)
    assert (error.view, error.tile, error.code) == (1, 1, "unsupported_domain")


def test_a_view_cannot_hold_more_tiles_than_its_layout(
    profile: dict[str, Any],
) -> None:
    slots = len(profile["layouts"][0]["slots"])
    assert check([view(n=slots)], profile) == []
    [error] = check([view(n=slots + 1)], profile)
    assert (error.view, error.tile, error.code) == (0, None, "too_many_tiles")


def test_the_layout_must_exist_in_the_profile(profile: dict[str, Any]) -> None:
    count = len(profile["layouts"])
    for bad in (count, -1):
        assert codes(check([view(layout=bad)], profile)) == ["unknown_layout"]


@pytest.mark.parametrize("title", ["", "x" * 33])
def test_a_title_has_1_to_32_characters(profile: dict[str, Any], title: str) -> None:
    assert codes(check([view(title=title)], profile)) == ["bad_title"]


def test_a_title_of_32_characters_is_valid(profile: dict[str, Any]) -> None:
    assert check([view(title="x" * 32)], profile) == []


def test_paths_are_unique(profile: dict[str, Any]) -> None:
    assert codes(check([view("a"), view("a")], profile)) == ["duplicate_path"]


@pytest.mark.parametrize("path", ["", None, 3])
def test_a_view_needs_a_path(profile: dict[str, Any], path: Any) -> None:
    assert codes(check([{**view(), "path": path}], profile)) == ["bad_path"]


def test_a_name_has_at_most_32_characters(profile: dict[str, Any]) -> None:
    ok = {**view(n=0), "tiles": [tile(name="n" * 32)]}
    bad = {**view(n=0), "tiles": [tile(name="n" * 33)]}
    assert check([ok], profile) == []
    assert codes(check([bad], profile)) == ["bad_name"]


def test_an_icon_must_be_a_known_mdi_name(profile: dict[str, Any]) -> None:
    def with_icon(icon: str) -> list[dict[str, Any]]:
        return [{**view(n=0), "tiles": [tile(icon=icon)]}]

    assert check(with_icon("mdi:lightbulb"), profile) == []
    assert codes(check(with_icon("mdi:nope"), profile)) == ["bad_icon"]
    assert codes(check(with_icon("fa:lightbulb"), profile)) == ["bad_icon"]


def test_controls_must_belong_to_the_domain(profile: dict[str, Any]) -> None:
    def with_controls(entity: str, controls: list[Any]) -> list[dict[str, Any]]:
        return [{**view(n=0), "tiles": [tile(entity, controls=controls)]}]

    ok = with_controls("climate.heat", [{"type": "hvac_mode", "values": ["heat"]}])
    assert check(ok, profile) == []
    bad = with_controls("light.kitchen", [{"type": "hvac_mode"}])
    assert codes(check(bad, profile)) == ["bad_controls"]


@pytest.mark.parametrize(
    "controls",
    [
        [{"type": "target_temperature", "values": ["x"]}],  # no values for this one
        [{"type": "hvac_mode", "values": "heat"}],
        [{"type": "hvac_mode", "values": [1]}],
        [{"type": "hvac_mode"}, {"type": "hvac_mode"}],  # twice
        ["hvac_mode"],
        "hvac_mode",
    ],
)
def test_malformed_controls_are_refused(profile: dict[str, Any], controls: Any) -> None:
    views = [{**view(n=0), "tiles": [tile("climate.heat", controls=controls)]}]
    assert codes(check(views, profile)) == ["bad_controls"]


def test_the_snapshot_view_must_exist_on_a_device_that_sleeps(
    profile: dict[str, Any],
) -> None:
    sleeps = "sleep" in profile["features"]
    errors = check([view("a")], profile, snapshot="a")
    assert (errors == []) is sleeps
    if sleeps:
        assert codes(check([view("a")], profile, snapshot="b")) == ["bad_snapshot"]
    else:
        assert codes(errors) == ["bad_snapshot"]


def test_an_unset_snapshot_is_always_valid(profile: dict[str, Any]) -> None:
    assert check([view("a")], profile, snapshot=None) == []


def test_every_error_is_reported_not_just_the_first(profile: dict[str, Any]) -> None:
    views = [
        view("a", title=""),
        {**view("b", n=0), "tiles": [tile("weather.x"), tile(icon="mdi:nope")]},
    ]
    assert sorted(codes(check(views, profile))) == [
        "bad_icon",
        "bad_title",
        "unsupported_domain",
    ]


def test_a_tile_is_a_mapping_with_an_entity(profile: dict[str, Any]) -> None:
    views = [{**view(n=0), "tiles": ["light.kitchen", {}]}]
    assert codes(check(views, profile)) == ["bad_tile", "bad_tile"]


@pytest.mark.parametrize(
    ("entity_id", "kind", "page"),
    [
        ("light.a", "toggle", "light"),
        ("input_boolean.a", "toggle", "switch"),
        ("scene.a", "activate", "scene"),
        ("input_button.a", "activate", "button"),
        ("climate.a", "readonly", "climate"),
        ("input_number.a", "readonly", "number"),
        ("input_select.a", "readonly", "select"),
        ("sensor.a", "readonly", "sensor"),
    ],
)
def test_kind_and_detail_page_come_from_the_domain(
    entity_id: str, kind: str, page: str
) -> None:
    assert vr.tile_kind(entity_id) == kind
    assert vr.page_domain(entity_id) == page


def test_every_domain_with_controls_is_a_supported_domain() -> None:
    assert set(vr.CONTROLS) <= vr.SUPPORTED_DOMAINS


def test_a_mode_control_names_the_attribute_that_lists_its_values() -> None:
    by_type = {c.type: c for cs in vr.CONTROLS.values() for c in cs}
    assert by_type["hvac_mode"].values_attr == "hvac_modes"
    assert by_type["select"].values_attr == "options"
    assert by_type["target_temperature"].values_attr is None


def test_resolve_builds_the_contract_tile() -> None:
    resolved = vr.resolve_tile(
        tile("climate.heat", name="Heat", controls=[{"type": "hvac_mode"}]),
        lambda _e: "Friendly",
    )
    assert resolved == {
        "entity_id": "climate.heat",
        "name": "Heat",
        "kind": "readonly",
        "domain": "climate",
        "controls": [{"type": "hvac_mode"}],
    }


def test_resolve_falls_back_to_the_friendly_name_then_the_entity_id() -> None:
    assert vr.resolve_tile(tile(), lambda _e: "Kitchen")["name"] == "Kitchen"
    assert vr.resolve_tile(tile(), lambda _e: None)["name"] == "light.kitchen"
    assert "controls" not in vr.resolve_tile(tile(), lambda _e: None)


def test_the_first_icon_override_of_an_entity_wins() -> None:
    views = [
        {"tiles": [{"entity_id": "light.a"}, {"entity_id": "light.b", "icon": ""}]},
        {
            "tiles": [
                {"entity_id": "light.a", "icon": "mdi:lamp"},
                {"entity_id": "light.a", "icon": "mdi:star"},
            ]
        },
    ]
    assert vr.icon_overrides(views) == {"light.a": "mdi:lamp", "light.b": None}
