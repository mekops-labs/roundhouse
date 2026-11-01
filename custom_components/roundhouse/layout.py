"""Choose layouts, handle overflow, and build the `views` payload.

Pure functions with no Home Assistant imports.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .digest import DigestView

EMPTY_VIEWS: dict[str, Any] = {"views": [], "snapshot_view": None, "skipped": 0}


@dataclass(frozen=True)
class Overflow:
    """A view with more tiles than the densest layout holds."""

    path: str
    title: str
    tiles: int
    capacity: int

    @property
    def excess(self) -> int:
        """Return how many tiles to remove."""
        return self.tiles - self.capacity


def capacity(profile: Mapping[str, Any]) -> int:
    """Return the slot count of the densest (last) layout."""
    return len(profile["layouts"][-1]["slots"])


def choose_layout(profile: Mapping[str, Any], tiles: int) -> int | None:
    """Return the first layout with enough slots, or None when none has."""
    for index, layout in enumerate(profile["layouts"]):
        if len(layout["slots"]) >= tiles:
            return index
    return None


def profile_fingerprint(profile: Mapping[str, Any]) -> str:
    """Return a hash of what a stored view definition depends on."""
    blob = json.dumps(
        [profile["display"], profile["layouts"]], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def merge(
    views: Sequence[DigestView],
    last_good: Mapping[str, dict[str, Any]],
    profile: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[Overflow]]:
    """Return the views to publish and the views held back.

    A view that fits is published as digested. A view that overflows keeps its
    last definition that fitted, or is left out when it never fitted.
    """
    published: list[dict[str, Any]] = []
    overflows: list[Overflow] = []
    cap = capacity(profile)
    for view in views:
        layout = choose_layout(profile, len(view.tiles))
        if layout is None:
            overflows.append(Overflow(view.path, view.title, len(view.tiles), cap))
            if view.path in last_good:
                published.append(last_good[view.path])
            continue
        published.append(
            {
                "path": view.path,
                "title": view.title,
                "layout": layout,
                "tiles": [t.as_dict() for t in view.tiles],
            }
        )
    return published, overflows


def snapshot_view(
    published: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], option: str
) -> str | None:
    """Return the view a sleeping device refreshes, or None for other devices."""
    if "sleep" not in profile.get("features", []) or not published:
        return None
    paths = [v["path"] for v in published]
    return option if option in paths else paths[0]


def definition_hash(payload: Mapping[str, Any]) -> str:
    """Return the content hash of a `views` payload."""
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
