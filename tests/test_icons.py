"""Icon resolution and golden alpha masks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.roundhouse import icons

GOLDEN = json.loads((Path(__file__).parent / "golden/rendering.json").read_text())


def resolve(**kw: Any) -> str:
    base = {
        "card_icon": None,
        "registry_icon": None,
        "attribute_icon": None,
        "translated": None,
        "domain": "light",
    }
    return icons.resolve_icon(**{**base, **kw})


def test_resolution_order() -> None:
    full = {
        "card_icon": "mdi:a",
        "registry_icon": "mdi:b",
        "attribute_icon": "mdi:c",
        "translated": "mdi:d",
    }
    assert resolve(**full) == "mdi:a"
    assert resolve(**{**full, "card_icon": None}) == "mdi:b"
    assert resolve(**{**full, "card_icon": None, "registry_icon": None}) == "mdi:c"
    assert resolve(translated="mdi:d") == "mdi:d"
    assert resolve() == "mdi:lightbulb"


def test_unknown_domain_gets_the_fallback() -> None:
    assert resolve(domain="vacuum") == icons.FALLBACK
    assert resolve(card_icon="", domain="vacuum") == icons.FALLBACK


def test_every_default_icon_is_in_the_bundled_font() -> None:
    missing = [n for n in icons.DOMAIN_ICONS.values() if not icons.known(n)]
    assert missing == []
    assert icons.known(icons.FALLBACK)


def test_translated_icon_by_state_and_device_class() -> None:
    entry = {
        "_": {
            "default": "mdi:window-shutter",
            "state": {"open": "mdi:window-shutter-open"},
        },
        "garage": {"default": "mdi:garage", "state": {"open": "mdi:garage-open"}},
    }
    assert icons.translated_icon(entry, "open", None) == "mdi:window-shutter-open"
    assert icons.translated_icon(entry, "closed", None) == "mdi:window-shutter"
    assert icons.translated_icon(entry, "open", "garage") == "mdi:garage-open"
    assert (
        icons.translated_icon(entry, "open", "unknown-class")
        == "mdi:window-shutter-open"
    )
    assert icons.translated_icon(None, "open", None) is None
    assert icons.translated_icon({}, "open", None) is None


def test_unknown_icon_names_fall_back() -> None:
    assert icons.effective_name("mdi:lightbulb") == "mdi:lightbulb"
    assert icons.effective_name("mdi:not-a-real-icon") == icons.FALLBACK
    assert icons.effective_name("custom:thing") == icons.FALLBACK
    assert icons.mask("mdi:not-a-real-icon", 16) == icons.mask(icons.FALLBACK, 16)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("mdi:lightbulb", 16),
        ("mdi:lock", 16),
        ("mdi:thermostat", 24),
        ("mdi:help-circle-outline", 16),
    ],
)
def test_golden_masks(name: str, size: int) -> None:
    got = icons.mask(name, size)
    want = GOLDEN[f"mask:{name}:{size}"]
    assert len(got) == size and all(len(r) == size for r in got)
    diffs = [
        abs(a - b)
        for g, w in zip(got, want, strict=True)
        for a, b in zip(g, w, strict=True)
    ]
    # Pillow and FreeType versions shift anti-aliasing slightly.
    assert max(diffs) <= 3
    assert sum(diffs) / len(diffs) < 0.3
    assert all(0 <= v <= 15 for row in got for v in row)


def test_mask_has_ink_and_transparent_corners() -> None:
    m = icons.mask("mdi:lightbulb", 32)
    assert sum(v > 8 for row in m for v in row) > 100
    assert m[0][0] == m[0][31] == m[31][0] == m[31][31] == 0


def test_cache_is_keyed_by_name_and_size() -> None:
    icons._mask.cache_clear()
    icons.mask("mdi:lock", 16)
    icons.mask("mdi:lock", 16)
    icons.mask("mdi:lock", 24)
    icons.mask("mdi:lightbulb", 16)
    info = icons.cache_info()
    assert (info.hits, info.misses, info.currsize) == (1, 3, 3)


def test_cache_is_bounded() -> None:
    assert icons.cache_info().maxsize == icons.CACHE_SIZE


def test_font_covers_the_name_map() -> None:
    names = json.loads(icons.NAMES_PATH.read_text())
    assert len(names) > 7000
    assert names["lightbulb"] == 0xF0335
