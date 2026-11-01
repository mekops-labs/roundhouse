"""Alert records: creation, aging, and the public payload.

Pure functions with no Home Assistant imports. An alert is a plain dict so it
can be stored as JSON.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

SECONDS_PER_DAY = 86400
MAX_ACTIONS = 8
_SERVICE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_ACTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class AlertError(ValueError):
    """An alert or one of its actions is malformed."""


def new_id() -> str:
    """Return a fresh alert ID (lowercase hex, valid in a topic and the contract)."""
    return uuid.uuid4().hex[:8]


def parse_action(raw: Any, index: int) -> dict[str, Any]:
    """Check one declared action and return it in its stored shape.

    The device sees `id`, `label`, and `confirm`. Roundhouse keeps the service
    call: `action` (`domain.service`), `target`, and `data`.
    """
    if not isinstance(raw, Mapping):
        raise AlertError(f"action {index} must be an object")
    action_id, label, service = raw.get("id"), raw.get("label"), raw.get("action")
    if not isinstance(action_id, str) or not _ACTION_ID.match(action_id):
        raise AlertError(f"action {index}: id must be 1-32 letters, digits, - or _")
    if not isinstance(label, str) or not label.strip():
        raise AlertError(f"action {action_id}: label is required")
    if not isinstance(service, str) or not _SERVICE.match(service):
        raise AlertError(f"action {action_id}: action must be 'domain.service'")
    target, data = raw.get("target") or {}, raw.get("data") or {}
    if not isinstance(target, Mapping) or not isinstance(data, Mapping):
        raise AlertError(f"action {action_id}: target and data must be objects")
    confirm = raw.get("confirm", False)
    if not isinstance(confirm, bool):
        raise AlertError(f"action {action_id}: confirm must be true or false")
    return {
        "id": action_id,
        "label": label.strip(),
        "confirm": confirm,
        "action": service,
        "target": dict(target),
        "data": dict(data),
    }


def parse_actions(raw: Any) -> list[dict[str, Any]]:
    """Check a list of declared actions: unique IDs, a sensible count."""
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise AlertError("actions must be a list")
    if len(raw) > MAX_ACTIONS:
        raise AlertError(f"at most {MAX_ACTIONS} actions")
    actions = [parse_action(a, i) for i, a in enumerate(raw)]
    ids = [a["id"] for a in actions]
    if len(set(ids)) != len(ids):
        raise AlertError("action IDs must be unique")
    return actions


def new_alert(
    *,
    alert_id: str,
    now: float,
    title: str,
    message: str,
    severity: str,
    actions: list[dict[str, Any]],
    tag: str | None,
) -> dict[str, Any]:
    """Build a stored alert record; images are attached later."""
    return {
        "id": alert_id,
        "title": title,
        "message": message,
        "severity": severity,
        "time": int(now),
        "read": False,
        "tag": tag or None,
        "actions": actions,
        "image": None,
        "thumb": None,
    }


def public(alert: Mapping[str, Any]) -> dict[str, Any]:
    """Return the `alert/<id>` payload; the service calls stay behind."""
    return {
        "title": alert["title"],
        "message": alert["message"],
        "severity": alert["severity"],
        "time": alert["time"],
        "read": alert["read"],
        "actions": [
            {"id": a["id"], "label": a["label"], "confirm": a["confirm"]}
            for a in alert["actions"]
        ],
        "image": alert.get("image"),
        "thumb": alert.get("thumb"),
    }


def find_action(alert: Mapping[str, Any], action_id: str) -> dict[str, Any] | None:
    """Return the declared action with this ID."""
    return next((a for a in alert["actions"] if a["id"] == action_id), None)


def service_call(action: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Return (domain, service, data) of a declared action.

    The target keys (`entity_id`, `device_id`, `area_id`) merge into the data,
    as Home Assistant does for a service call with a target.
    """
    domain, service = action["action"].split(".", 1)
    return domain, service, {**action["data"], **action["target"]}


def unread(alerts: Sequence[Mapping[str, Any]]) -> int:
    """Return how many alerts are unread."""
    return sum(1 for a in alerts if not a["read"])


def expire(
    alerts: Sequence[Mapping[str, Any]], now: float, max_count: int, max_age_days: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split alerts into (kept, dropped) by age, then by count, oldest first."""
    oldest_allowed = now - max_age_days * SECONDS_PER_DAY
    by_age = sorted(alerts, key=lambda a: (a["time"], a["id"]))
    fresh = [dict(a) for a in by_age if a["time"] >= oldest_allowed]
    dropped = [dict(a) for a in by_age if a["time"] < oldest_allowed]
    if len(fresh) > max_count:
        dropped += fresh[: len(fresh) - max_count]
        fresh = fresh[len(fresh) - max_count :]
    return fresh, dropped


def same_tag(
    alerts: Sequence[Mapping[str, Any]], tag: str | None
) -> list[dict[str, Any]]:
    """Return the alerts a new alert with this tag replaces."""
    if not tag:
        return []
    return [dict(a) for a in alerts if a.get("tag") == tag]
