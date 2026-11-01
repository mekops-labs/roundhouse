"""Presence of a device: home while online, not home after a grace period offline.

Pure logic with no Home Assistant imports. Times are Unix seconds.
"""

from __future__ import annotations

HOME = "home"
NOT_HOME = "not_home"
ONLINE = "online"
OFFLINE = "offline"


class Presence:
    """Track availability and answer what the device tracker reads.

    Before the first availability message the state is unknown (None). `online`
    reads home. `offline` starts a grace period and reads not home when it ends.
    The offline time can be restored, so a restart does not reset the countdown.
    """

    def __init__(
        self, grace_seconds: float, offline_since: float | None = None
    ) -> None:
        """Initialize with the grace period and a restored offline time."""
        self.grace = grace_seconds
        self.availability: str | None = None
        self.offline_since = offline_since

    def on_availability(self, value: str, now: float) -> bool:
        """Apply an availability message; return whether anything changed."""
        if value not in (ONLINE, OFFLINE):
            return False
        before = (self.availability, self.offline_since)
        self.availability = value
        if value == ONLINE:
            self.offline_since = None
        elif self.offline_since is None:
            # A restored time wins: the device went offline before the restart.
            self.offline_since = now
        return (self.availability, self.offline_since) != before

    def state(self, now: float) -> str | None:
        """Return `home`, `not_home`, or None while unknown."""
        if self.availability is None:
            return None
        if self.availability == ONLINE:
            return HOME
        return NOT_HOME if self.seconds_left(now) == 0 else HOME

    def seconds_left(self, now: float) -> float | None:
        """Return the seconds until `not_home`, or None when not counting down."""
        if self.availability != OFFLINE or self.offline_since is None:
            return None
        return max(0.0, self.offline_since + self.grace - now)
