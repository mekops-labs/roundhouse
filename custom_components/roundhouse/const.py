"""Constants for Roundhouse."""

DOMAIN = "roundhouse"

CONF_DEVICE_ID = "device_id"
CONF_MODEL = "model"
CONF_SLUG = "slug"
CONF_PROFILE = "profile"

OPT_SNAPSHOT_VIEW = "snapshot_view"
OPT_PRESENCE_GRACE_HOURS = "presence_grace_hours"
OPT_ALERT_MAX_COUNT = "alert_max_count"
OPT_ALERT_MAX_AGE_DAYS = "alert_max_age_days"

DEFAULT_PRESENCE_GRACE_HOURS = 2
DEFAULT_ALERT_MAX_COUNT = 20
DEFAULT_ALERT_MAX_AGE_DAYS = 7

# How long to collect retained topics before judging which are stale.
STALE_SETTLE_SECONDS = 2.0

ISSUE_MQTT_BIRTH = "mqtt_birth_disabled"

EVENT_ALERT_ACKNOWLEDGED = "roundhouse_alert_acknowledged"
SERVICE_SEND_ALERT = "send_alert"
SERVICE_ACKNOWLEDGE_ALERT = "acknowledge_alert"

SEVERITIES = ("critical", "warning", "event")
DEFAULT_SEVERITY = "event"


def alerts_signal(device_id: str) -> str:
    """Return the dispatcher signal sent when a device's alerts change."""
    return f"{DOMAIN}_alerts_{device_id}"


def status_signal(device_id: str) -> str:
    """Return the signal sent when a device's `status` changes."""
    return f"{DOMAIN}_status_{device_id}"


def views_signal(device_id: str) -> str:
    """Return the signal sent when a device's view definition changes."""
    return f"{DOMAIN}_views_{device_id}"


def presence_signal(device_id: str) -> str:
    """Return the signal sent when a device's presence changes."""
    return f"{DOMAIN}_presence_{device_id}"
