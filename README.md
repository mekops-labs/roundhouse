# Roundhouse

Home Assistant custom integration that serves panel devices over MQTT. Each
device gets a dashboard authored in Home Assistant, live entity state, control
of those entities, and alerts. Devices draw their own pixels; Roundhouse reads
Lovelace, formats state, rasterizes icons, and scales images for each device's
announced screen.

Status: under development. No release yet.

## Requirements

- Home Assistant stable or the release before it.
- Home Assistant's `mqtt` integration, with the birth message enabled.

## Alerts

Call `roundhouse.send_alert` from an automation. Target one or more Roundhouse
devices; the call returns the alert ID of each.

```yaml
action: roundhouse.send_alert
target:
  device_id: <panel device>
data:
  title: Motion at the gate
  message: The gate camera saw a person.
  severity: critical        # critical, warning, or event (default)
  camera_entity: camera.gate
  tag: gate                 # a new alert with this tag replaces the old one
  actions:
    - id: open
      label: Open gate
      action: cover.open_cover
      target:
        entity_id: cover.gate
      confirm: true
```

The device sends only the action ID; the service call stays in Home Assistant.
`roundhouse.acknowledge_alert` marks alerts read by `alert_id` or `tag`. An
acknowledgment from the panel or from that service fires the event
`roundhouse_alert_acknowledged` with `alert_id`, `tag`, and `device_id`. Each
panel also has a `notify` entity: `notify.send_message` shows an `event` alert.

## Development

Dependencies and tasks run through [mise](https://mise.jdx.dev).

```sh
mise install        # Python and uv
mise run setup      # test dependencies into .venv
mise run check      # ruff, mypy, pytest
```

Home Assistant internals the integration relies on are recorded in
`docs/ha-internals.md`, with the versions they were checked on.

## Layout

- `custom_components/roundhouse/` - the integration.
- `contract/` - MQTT schemas, encodings, and test vectors.
- `tests/` - unit and integration tests.
- `docs/` - notes on Home Assistant internals.
