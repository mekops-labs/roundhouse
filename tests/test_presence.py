"""The presence state machine."""

from __future__ import annotations

from custom_components.roundhouse.presence import HOME, NOT_HOME, Presence

HOUR = 3600


def test_unknown_before_the_first_availability_message() -> None:
    p = Presence(2 * HOUR)
    assert p.state(0) is None and p.seconds_left(0) is None


def test_online_is_home() -> None:
    p = Presence(2 * HOUR)
    assert p.on_availability("online", 10) is True
    assert p.state(10) == HOME and p.seconds_left(10) is None
    assert p.on_availability("online", 20) is False  # nothing changed


def test_offline_keeps_home_for_the_grace_period_then_flips() -> None:
    p = Presence(2 * HOUR)
    p.on_availability("online", 0)
    p.on_availability("offline", 100)
    assert p.state(100) == HOME
    assert p.seconds_left(100) == 2 * HOUR
    assert p.state(100 + 2 * HOUR - 1) == HOME
    assert p.state(100 + 2 * HOUR) == NOT_HOME
    assert p.seconds_left(100 + 5 * HOUR) == 0


def test_coming_back_cancels_the_countdown() -> None:
    p = Presence(HOUR)
    p.on_availability("offline", 0)
    p.on_availability("online", 600)
    assert p.state(10 * HOUR) == HOME and p.offline_since is None
    p.on_availability("offline", 11 * HOUR)  # a new countdown starts from now
    assert p.seconds_left(11 * HOUR) == HOUR


def test_a_repeated_offline_does_not_restart_the_countdown() -> None:
    p = Presence(HOUR)
    p.on_availability("offline", 0)
    assert p.on_availability("offline", 1800) is False
    assert p.seconds_left(1800) == 1800


def test_a_restored_offline_time_survives_the_first_offline_message() -> None:
    p = Presence(2 * HOUR, offline_since=1000)
    assert p.state(1000) is None  # still unknown until the broker says something
    p.on_availability("offline", 5000)  # the retained last will after a restart
    assert p.offline_since == 1000
    assert p.seconds_left(5000) == 2 * HOUR - 4000


def test_a_grace_that_ran_out_while_hass_was_down_reads_not_home_at_once() -> None:
    p = Presence(HOUR, offline_since=0)
    p.on_availability("offline", 10 * HOUR)
    assert p.state(10 * HOUR) == NOT_HOME


def test_online_after_a_restart_clears_a_restored_time() -> None:
    p = Presence(HOUR, offline_since=0)
    p.on_availability("online", 100)
    assert p.offline_since is None and p.state(100) == HOME


def test_a_zero_grace_flips_immediately() -> None:
    p = Presence(0)
    p.on_availability("offline", 50)
    assert p.state(50) == NOT_HOME


def test_other_text_is_ignored() -> None:
    p = Presence(HOUR)
    assert p.on_availability("maybe", 0) is False
    assert p.state(0) is None
