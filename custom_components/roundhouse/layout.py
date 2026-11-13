"""Fit stored views to a profile and build the `views` payload.

Pure functions with no Home Assistant imports.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .viewrules import resolve_tile

EMPTY_VIEWS: dict[str, Any] = {"views": [], "snapshot_view": None, "skipped": 0}


@dataclass(frozen=True)
class Overflow:
    """A view the device's profile can no longer show."""

    path: str
    title: str
    tiles: int
    capacity: int  # the slots of the view's layout; of the densest if it is gone
    layout_gone: bool = False

    @property
    def excess(self) -> int:
        """Return how many tiles to remove."""
        return max(0, self.tiles - self.capacity)


def densest(profile: Mapping[str, Any]) -> int:
    """Return the index of the layout with the most slots, the first on a tie."""
    layouts = profile["layouts"]
    return max(range(len(layouts)), key=lambda i: len(layouts[i]["slots"]))


def capacity(profile: Mapping[str, Any]) -> int:
    """Return the slot count of the densest layout."""
    return len(profile["layouts"][densest(profile)]["slots"])


def fit(
    views: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    friendly_name: Callable[[str], str | None],
) -> tuple[list[dict[str, Any]], list[Overflow]]:
    """Return the views to publish and the views the profile cannot show.

    A view fits when its layout exists and has a slot for every tile. A view
    that does not fit is left out.
    """
    layouts = profile["layouts"]
    published: list[dict[str, Any]] = []
    overflows: list[Overflow] = []
    for view in views:
        tiles = view["tiles"]
        index = view["layout"]
        if not 0 <= index < len(layouts):
            overflows.append(
                Overflow(
                    view["path"], view["title"], len(tiles), capacity(profile), True
                )
            )
            continue
        slots = len(layouts[index]["slots"])
        if len(tiles) > slots:
            overflows.append(Overflow(view["path"], view["title"], len(tiles), slots))
            continue
        published.append(
            {
                "path": view["path"],
                "title": view["title"],
                "layout": index,
                "tiles": [resolve_tile(t, friendly_name) for t in tiles],
            }
        )
    return published, overflows


def snapshot_view(
    published: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    chosen: str | None,
) -> str | None:
    """Return the view a sleeping device refreshes, or None for other devices."""
    if "sleep" not in profile.get("features", []) or not published:
        return None
    paths = [v["path"] for v in published]
    return chosen if chosen in paths else paths[0]


def definition_hash(payload: Mapping[str, Any]) -> str:
    """Return the content hash of a `views` payload."""
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
