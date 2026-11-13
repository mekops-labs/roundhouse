# Roundhouse

Home Assistant custom integration that serves panel devices over MQTT. Each
device gets views you build in Roundhouse's own editor page, live entity state,
control of those entities, and alerts. Devices draw their own pixels;
Roundhouse stores the views, formats state, rasterizes icons, and scales images
for each device's announced screen.

Status: early release. `CHANGELOG.md` lists the current version.

## Install

See `docs/install.md`: the Marketplace or HACS, the MQTT birth message,
per-device broker logins, and the broker ACL that is the security control.

## Requirements

- Home Assistant stable or the release before it.
- Home Assistant's `mqtt` integration, with the birth message enabled.

## Editor

One admin-only "Roundhouse" entry in the sidebar edits the views of every
device. The page draws each view as the device will draw it: its screen size,
header, tab strip, layout, and live tiles with the same icons, state text, and
colors the device gets. Fonts differ slightly from the device; the geometry and
the slot count do not.

- Select the pencil to edit. Changes stay a draft until you select **Done**.
- Each view has a layout that you choose from the device's own. A view takes no
  more tiles than its layout has slots.
- A tile is one entity of a supported domain. Its dialog offers a name, an icon,
  and the controls of the entity's detail page on the device.
- The header shows the running Roundhouse version and links to its changelog.

## Entities

Each panel is a Home Assistant device with:

- a `device_tracker` for presence (home while online, and for the grace period
  after it goes offline);
- sensors for the battery level, the power mode (devices that sleep), the
  contract version, and the unread alerts;
- a binary sensor for charging, when the device reports a charging state;
- a `notify` entity.

The battery and charging entities appear when the device first reports them.

## Alerts

Call `roundhouse.send_alert` from an automation. Name one or more Roundhouse
devices in `device_id`; the call returns the alert ID of each.

```yaml
action: roundhouse.send_alert
data:
  device_id:
    - <panel device>
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
mise run check      # ruff, mypy, pytest, and the panel's JavaScript tests
```

To try the integration against a real Home Assistant, see "Trying it by hand" in
`CONTRIBUTING.md`.

Home Assistant internals the integration relies on are recorded in
`docs/ha-internals.md`, with the versions they were checked on.

## Layout

- `custom_components/roundhouse/` - the integration.
- `contract/` - MQTT schemas, encodings, and test vectors.
- `tests/` - unit and integration tests.
- `docs/` - notes on Home Assistant internals.
