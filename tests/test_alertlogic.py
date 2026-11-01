"""Alert records, aging, and the public payload."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.roundhouse import alertlogic as al
from custom_components.roundhouse import codec

DAY = al.SECONDS_PER_DAY


def alert(alert_id: str, time: int, **kw: Any) -> dict[str, Any]:
    base = al.new_alert(
        alert_id=alert_id,
        now=time,
        title="t",
        message="m",
        severity="event",
        actions=[],
        tag=None,
    )
    return {**base, **kw}


def test_ids_are_valid_topic_segments_and_contract_ids() -> None:
    ids = {al.new_id() for _ in range(50)}
    assert len(ids) == 50
    for alert_id in ids:
        payload = codec.encode({"req": "r", "ack": alert_id})
        assert codec.decode("cmd", payload)["ack"] == alert_id


def test_a_declared_action_keeps_its_call_apart_from_what_the_device_sees() -> None:
    raw = {
        "id": "open",
        "label": " Open gate ",
        "action": "cover.open_cover",
        "target": {"entity_id": "cover.gate"},
        "data": {"x": 1},
        "confirm": True,
    }
    stored = al.parse_action(raw, 0)
    assert stored == {
        "id": "open",
        "label": "Open gate",
        "confirm": True,
        "action": "cover.open_cover",
        "target": {"entity_id": "cover.gate"},
        "data": {"x": 1},
    }
    a = al.new_alert(
        alert_id="a1",
        now=100.7,
        title="T",
        message="M",
        severity="critical",
        actions=[stored],
        tag="gate",
    )
    payload = al.public(a)
    assert payload["actions"] == [{"id": "open", "label": "Open gate", "confirm": True}]
    assert "target" not in str(payload) and "cover.gate" not in str(payload)
    assert payload["time"] == 100 and payload["read"] is False
    assert codec.decode("alert", codec.encode(payload)) == payload


def test_action_defaults() -> None:
    a = al.parse_action({"id": "go", "label": "Go", "action": "script.turn_on"}, 0)
    assert (a["confirm"], a["target"], a["data"]) == (False, {}, {})


@pytest.mark.parametrize(
    "raw",
    [
        "open",
        None,
        {"label": "x", "action": "a.b"},
        {"id": "", "label": "x", "action": "a.b"},
        {"id": "a b", "label": "x", "action": "a.b"},
        {"id": "x" * 33, "label": "x", "action": "a.b"},
        {"id": "a", "label": "", "action": "a.b"},
        {"id": "a", "label": " ", "action": "a.b"},
        {"id": "a", "label": "x", "action": "nodot"},
        {"id": "a", "label": "x", "action": "A.b"},
        {"id": "a", "label": "x", "action": "a.b", "target": [1]},
        {"id": "a", "label": "x", "action": "a.b", "data": "x"},
        {"id": "a", "label": "x", "action": "a.b", "confirm": "yes"},
    ],
)
def test_bad_actions_are_refused(raw: Any) -> None:
    with pytest.raises(al.AlertError):
        al.parse_action(raw, 0)


def test_action_lists() -> None:
    ok = {"id": "a", "label": "x", "action": "a.b"}
    assert al.parse_actions(None) == [] and al.parse_actions([]) == []
    assert len(al.parse_actions([ok, {**ok, "id": "b"}])) == 2
    with pytest.raises(al.AlertError, match="unique"):
        al.parse_actions([ok, ok])
    with pytest.raises(al.AlertError, match="list"):
        al.parse_actions("open")
    with pytest.raises(al.AlertError, match="at most"):
        al.parse_actions([{**ok, "id": f"a{i}"} for i in range(al.MAX_ACTIONS + 1)])


def test_service_call_merges_the_target_into_the_data() -> None:
    a = al.parse_action(
        {
            "id": "a",
            "label": "x",
            "action": "light.turn_on",
            "target": {"entity_id": "light.l"},
            "data": {"brightness": 5},
        },
        0,
    )
    assert al.service_call(a) == (
        "light",
        "turn_on",
        {"brightness": 5, "entity_id": "light.l"},
    )


def test_find_action_and_unread() -> None:
    a = alert("a1", 1, actions=[{"id": "x", "label": "X", "confirm": False}])
    assert al.find_action(a, "x") is a["actions"][0]
    assert al.find_action(a, "y") is None
    assert al.unread([a, alert("a2", 2, read=True), alert("a3", 3)]) == 2


def test_aging_by_time_then_by_count() -> None:
    now = 100 * DAY
    items = [alert(f"a{i}", now - i * DAY) for i in range(10)]  # 0 to 9 days old
    kept, dropped = al.expire(items, now, max_count=20, max_age_days=7)
    assert [a["id"] for a in kept] == ["a7", "a6", "a5", "a4", "a3", "a2", "a1", "a0"]
    assert [a["id"] for a in dropped] == ["a9", "a8"]
    kept, dropped = al.expire(items, now, max_count=3, max_age_days=7)
    assert [a["id"] for a in kept] == ["a2", "a1", "a0"]  # the newest three
    assert {a["id"] for a in dropped} == {"a9", "a8", "a7", "a6", "a5", "a4", "a3"}


def test_aging_boundaries_and_ties() -> None:
    now = 50 * DAY
    exactly = alert("edge", now - 7 * DAY)
    kept, dropped = al.expire([exactly], now, 20, 7)
    assert kept and not dropped  # exactly at the limit is still fresh
    kept, dropped = al.expire([alert("old", now - 7 * DAY - 1)], now, 20, 7)
    assert dropped and not kept
    same = [alert("b", 10), alert("a", 10), alert("c", 10)]
    kept, dropped = al.expire(same, 11, 2, 1)
    assert [a["id"] for a in dropped] == ["a"]  # a stable choice among equal times
    assert al.expire([], now, 1, 1) == ([], [])


def test_the_tag_finds_what_a_new_alert_replaces() -> None:
    items = [
        alert("a", 1, tag="gate"),
        alert("b", 2, tag="door"),
        alert("c", 3, tag="gate"),
        alert("d", 4),
    ]
    assert [a["id"] for a in al.same_tag(items, "gate")] == ["a", "c"]
    assert al.same_tag(items, None) == [] and al.same_tag(items, "") == []
    assert al.same_tag(items, "none") == []
