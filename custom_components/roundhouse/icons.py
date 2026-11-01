"""Icon names and alpha masks.

`resolve_icon` is pure. The rasterizer uses Pillow and the bundled Material
Design Icons font; call it from the executor.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

MDI_DIR = Path(__file__).parent / "mdi"
FONT_PATH = MDI_DIR / "materialdesignicons-webfont.ttf"
NAMES_PATH = MDI_DIR / "names.json"
FALLBACK = "mdi:help-circle-outline"
CACHE_SIZE = 512

# The icon of a domain when nothing more specific is known.
DOMAIN_ICONS = {
    "light": "mdi:lightbulb",
    "switch": "mdi:toggle-switch-variant",
    "input_boolean": "mdi:toggle-switch-variant",
    "fan": "mdi:fan",
    "cover": "mdi:window-shutter",
    "valve": "mdi:valve",
    "climate": "mdi:thermostat",
    "water_heater": "mdi:water-boiler",
    "humidifier": "mdi:air-humidifier",
    "number": "mdi:ray-vertex",
    "input_number": "mdi:ray-vertex",
    "select": "mdi:format-list-bulleted",
    "input_select": "mdi:format-list-bulleted",
    "lock": "mdi:lock",
    "sensor": "mdi:eye",
    "binary_sensor": "mdi:checkbox-blank-circle-outline",
    "person": "mdi:account",
    "alarm_control_panel": "mdi:shield",
    "scene": "mdi:palette",
    "script": "mdi:script-text",
    "button": "mdi:gesture-tap-button",
    "input_button": "mdi:gesture-tap-button",
}


def resolve_icon(
    *,
    card_icon: str | None,
    registry_icon: str | None,
    attribute_icon: str | None,
    translated: str | None,
    domain: str,
) -> str:
    """Pick the icon: card, registry, the entity's own, translated, domain default."""
    for candidate in (card_icon, registry_icon, attribute_icon, translated):
        if isinstance(candidate, str) and candidate:
            return candidate
    return DOMAIN_ICONS.get(domain, FALLBACK)


def translated_icon(
    icons: Mapping[str, Any] | None, state: str | None, device_class: str | None
) -> str | None:
    """Read a state-dependent icon from an icon-translation entry.

    `icons` is the `{"_": {...}, "<device_class>": {...}}` mapping of a domain.
    """
    if not icons:
        return None
    entry = icons.get(device_class or "_") or icons.get("_") or {}
    by_state = entry.get("state") or {}
    if state is not None and state in by_state:
        return str(by_state[state])
    default = entry.get("default")
    return str(default) if default else None


@lru_cache(maxsize=1)
def _names() -> dict[str, int]:
    return {str(k): int(v) for k, v in json.loads(NAMES_PATH.read_text()).items()}


def warm() -> None:
    """Load the name map. Call it from the executor before rendering."""
    _names()


def known(name: str) -> bool:
    """Return whether `name` (`mdi:...`) is an icon of the bundled font."""
    return name.startswith("mdi:") and name[4:] in _names()


def effective_name(name: str) -> str:
    """Return `name` when it is a bundled icon, else the fallback icon."""
    return name if known(name) else FALLBACK


@lru_cache(maxsize=CACHE_SIZE)
def _mask(name: str, size: int) -> bytes:
    code = _names()[name[4:]]
    font = ImageFont.truetype(str(FONT_PATH), size)
    canvas = Image.new("L", (size, size), 0)
    ImageDraw.Draw(canvas).text(
        (size / 2, size / 2), chr(code), font=font, fill=255, anchor="mm"
    )
    return bytes((px * 15 + 127) // 255 for px in canvas.tobytes())


def mask(name: str, size: int) -> list[list[int]]:
    """Return a `size` x `size` 4-bit alpha mask of an icon.

    An unknown icon draws the fallback. Cached by (name, size).
    """
    flat = _mask(effective_name(name), size)
    return [list(flat[y * size : (y + 1) * size]) for y in range(size)]


def cache_info() -> Any:
    """Return the cache statistics."""
    return _mask.cache_info()
