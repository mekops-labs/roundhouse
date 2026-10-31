"""Differences between supported Home Assistant releases."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow as _flow

# Home Assistant moved its schema library from voluptuous to probatio, and its
# flow serializer only accepts the one it uses. Use whichever HA imports.
vol: Any = getattr(_flow, "probatio", None) or _flow.vol  # type: ignore[attr-defined]
