"""Digest fixtures: Lovelace config in, tiles out."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import digest as dg

NAMES = {
    "light.ceiling": "Ceiling",
    "switch.pump": "Pump",
    "climate.heatpump": "Heat pump",
    "sensor.temp": "Temperature",
}


def friendly(entity_id: str) -> str | None:
    return NAMES.get(entity_id)


def run(config: dict[str, Any]) -> dg.DigestResult:
    return dg.digest(config, friendly)


def names(view: dg.DigestView) -> list[str]:
    return [t.entity_id for t in view.tiles]


def test_masonry_view_keeps_order_and_names() -> None:
    result = run(
        {
            "views": [
                {
                    "title": "Home",
                    "path": "home",
                    "cards": [
                        {"type": "tile", "entity": "light.ceiling"},
                        {
                            "type": "tile",
                            "entity": "switch.pump",
                            "name": "Boiler pump",
                        },
                    ],
                }
            ]
        }
    )
    (view,) = result.views
    assert (view.path, view.title) == ("home", "Home")
    assert [(t.entity_id, t.name, t.kind) for t in view.tiles] == [
        ("light.ceiling", "Ceiling", "toggle"),
        ("switch.pump", "Boiler pump", "toggle"),
    ]
    assert result.skipped == {}


def test_sections_view_reads_every_section() -> None:
    result = run(
        {
            "views": [
                {
                    "type": "sections",
                    "sections": [
                        {"cards": [{"type": "tile", "entity": "light.ceiling"}]},
                        {"cards": [{"type": "button", "entity": "switch.pump"}]},
                    ],
                }
            ]
        }
    )
    assert names(result.views[0]) == ["light.ceiling", "switch.pump"]


def test_view_identity_and_title_fall_back() -> None:
    result = run({"views": [{"cards": []}, {"path": "b", "cards": []}, {"title": "T"}]})
    assert [(v.path, v.title) for v in result.views] == [
        ("0", "0"),
        ("b", "b"),
        ("2", "T"),
    ]


def test_stacks_and_grids_are_flattened_in_order() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {
                            "type": "vertical-stack",
                            "cards": [
                                {"type": "tile", "entity": "light.ceiling"},
                                {
                                    "type": "horizontal-stack",
                                    "cards": [
                                        {"type": "tile", "entity": "switch.pump"},
                                        {
                                            "type": "grid",
                                            "cards": [
                                                {
                                                    "type": "tile",
                                                    "entity": "sensor.temp",
                                                }
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                        {"type": "tile", "entity": "climate.heatpump"},
                    ]
                }
            ]
        }
    )
    assert names(result.views[0]) == [
        "light.ceiling",
        "switch.pump",
        "sensor.temp",
        "climate.heatpump",
    ]


def test_thermostat_and_humidifier_cards_become_tiles() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {"type": "thermostat", "entity": "climate.heatpump"},
                        {"type": "humidifier", "entity": "humidifier.bedroom"},
                    ]
                }
            ]
        }
    )
    tiles = result.views[0].tiles
    assert [(t.entity_id, t.kind, t.domain, t.controls) for t in tiles] == [
        ("climate.heatpump", "readonly", "climate", ()),
        ("humidifier.bedroom", "readonly", "humidifier", ()),
    ]


def test_entities_card_rows() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {
                            "type": "entities",
                            "entities": [
                                "light.ceiling",
                                {"entity": "switch.pump", "name": "Boiler"},
                                {"type": "section", "label": "x"},
                                42,
                                "not an entity",
                            ],
                        }
                    ]
                }
            ]
        }
    )
    assert [(t.entity_id, t.name) for t in result.views[0].tiles] == [
        ("light.ceiling", "Ceiling"),
        ("switch.pump", "Boiler"),
    ]
    assert result.skipped == {dg.SKIP_UNSUPPORTED_TYPE: 1, dg.SKIP_NO_ENTITY: 2}


def test_skipped_cards_are_counted_with_reasons() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {"type": "markdown", "content": "hi"},
                        {"type": "history-graph", "entities": ["sensor.temp"]},
                        {"type": "tile"},
                        {"type": "button", "entity": 5},
                        {
                            "type": "tile",
                            "entity": "light.ceiling",
                            "visibility": [{"condition": "state"}],
                        },
                        "stray",
                        {"type": "vertical-stack", "cards": [{"type": "gauge"}]},
                    ]
                }
            ]
        }
    )
    assert result.views[0].tiles == ()
    assert result.skipped == {
        dg.SKIP_UNSUPPORTED_TYPE: 4,
        dg.SKIP_NO_ENTITY: 2,
        dg.SKIP_VISIBILITY: 1,
    }
    assert result.skipped_total == 7


def test_empty_visibility_list_means_visible() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {"type": "tile", "entity": "light.ceiling", "visibility": []}
                    ]
                }
            ]
        }
    )
    assert names(result.views[0]) == ["light.ceiling"]


def test_a_stack_with_visibility_is_skipped_whole() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {
                            "type": "vertical-stack",
                            "visibility": [{"condition": "user"}],
                            "cards": [{"type": "tile", "entity": "light.ceiling"}],
                        }
                    ]
                }
            ]
        }
    )
    assert result.views[0].tiles == ()
    assert result.skipped == {dg.SKIP_VISIBILITY: 1}


def test_missing_entity_still_becomes_a_tile() -> None:
    result = run({"views": [{"cards": [{"type": "tile", "entity": "light.nowhere"}]}]})
    (tile,) = result.views[0].tiles
    assert (tile.entity_id, tile.name) == ("light.nowhere", "light.nowhere")


@pytest.mark.parametrize(
    ("entity", "kind", "domain"),
    [
        ("light.a", "toggle", "light"),
        ("switch.a", "toggle", "switch"),
        ("input_boolean.a", "toggle", "switch"),
        ("fan.a", "toggle", "fan"),
        ("scene.a", "activate", "scene"),
        ("script.a", "activate", "script"),
        ("button.a", "activate", "button"),
        ("input_button.a", "activate", "button"),
        ("cover.a", "readonly", "cover"),
        ("climate.a", "readonly", "climate"),
        ("input_number.a", "readonly", "number"),
        ("input_select.a", "readonly", "select"),
        ("lock.a", "readonly", "lock"),
        ("sensor.a", "readonly", "sensor"),
    ],
)
def test_kind_and_detail_domain(entity: str, kind: str, domain: str) -> None:
    assert dg.tile_kind(entity) == kind
    assert dg.page_domain(entity) == domain


def test_tile_features_become_controls() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {
                            "type": "tile",
                            "entity": "climate.heatpump",
                            "features": [
                                {
                                    "type": "climate-hvac-modes",
                                    "hvac_modes": ["heat", "off"],
                                },
                                {
                                    "type": "climate-preset-modes",
                                    "preset_modes": ["eco", "comfort"],
                                },
                                {"type": "target-temperature"},
                                {"type": "climate-fan-modes"},
                            ],
                        }
                    ]
                }
            ]
        }
    )
    (tile,) = result.views[0].tiles
    assert tile.controls == (
        {"type": "hvac_mode", "values": ["heat", "off"]},
        {"type": "preset_mode", "values": ["eco", "comfort"]},
        {"type": "target_temperature"},
        {"type": "fan_mode"},
    )
    assert tile.kind == "readonly"  # features never add a tap action


def test_every_feature_type_maps() -> None:
    types = {
        "climate-hvac-modes": "hvac_mode",
        "climate-preset-modes": "preset_mode",
        "climate-fan-modes": "fan_mode",
        "climate-swing-modes": "swing_mode",
        "target-temperature": "target_temperature",
        "target-humidity": "target_humidity",
        "fan-speed": "fan_speed",
        "fan-preset-modes": "fan_preset_mode",
        "water-heater-operation-modes": "operation_mode",
        "humidifier-modes": "humidifier_mode",
        "humidifier-toggle": "humidifier_toggle",
        "numeric-input": "number",
        "select-options": "select",
        "cover-open-close": "cover_open_close",
        "cover-position": "cover_position",
        "valve-open-close": "valve_open_close",
        "valve-position": "valve_position",
        "light-brightness": "light_brightness",
        "light-color-temp": "light_color_temp",
    }
    config = {
        "views": [
            {
                "cards": [
                    {
                        "type": "tile",
                        "entity": "light.ceiling",
                        "features": [{"type": t} for t in types],
                    }
                ]
            }
        ]
    }
    (tile,) = run(config).views[0].tiles
    assert [c["type"] for c in tile.controls] == list(types.values())


def test_unknown_feature_is_ignored_and_counted() -> None:
    result = run(
        {
            "views": [
                {
                    "cards": [
                        {
                            "type": "tile",
                            "entity": "light.ceiling",
                            "features": [
                                {"type": "bar-gauge"},
                                {"type": "light-brightness"},
                                "x",
                            ],
                        }
                    ]
                }
            ]
        }
    )
    (tile,) = result.views[0].tiles
    assert tile.controls == ({"type": "light_brightness"},)
    assert result.skipped == {dg.SKIP_UNSUPPORTED_FEATURE: 2}


def test_mode_values_must_be_strings() -> None:
    config = {
        "views": [
            {
                "cards": [
                    {
                        "type": "tile",
                        "entity": "climate.heatpump",
                        "features": [
                            {"type": "climate-hvac-modes", "hvac_modes": [1, 2]}
                        ],
                    }
                ]
            }
        ]
    }
    assert run(config).views[0].tiles[0].controls == ({"type": "hvac_mode"},)


def test_strategy_dashboard_is_detected() -> None:
    assert dg.is_strategy({"strategy": {"type": "original-states"}})
    assert not dg.is_strategy({"strategy": {"type": "x"}, "views": [{"cards": []}]})
    assert not dg.is_strategy({"views": []})


def test_garbage_config_digests_to_nothing() -> None:
    assert run({}).views == []
    assert run({"views": "x"}).views == []
    assert run({"views": [None, 3]}).views == []
