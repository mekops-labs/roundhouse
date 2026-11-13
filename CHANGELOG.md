# Changelog

## Unreleased

### Changed

- Views are built in the Roundhouse page in the sidebar and stored by
  Roundhouse. Setup asks only for confirmation and adds one empty view, `Home`.
  No dashboard is created or read, so a device adds nothing else to the sidebar.
- The Roundhouse page is an editor: add, rename, reorder, and delete views;
  choose each view's layout; add, edit, move, and remove tiles; save with
  **Done**. It follows the Lovelace edit mode and the user's theme.
- A save is checked as a whole against the device's profile and publishes at
  once. A save that breaks a rule, or is based on stale views, changes nothing.
- Each view has a layout you choose. A full view takes no more tiles.
- A view that a changed device profile can no longer show is not shown on the
  device, and a repair issue names it.
- A tile follows its entity when the entity ID changes.
- The page header shows the running version and links to its changelog.
- WebSocket commands: `roundhouse/devices`, `roundhouse/editor/subscribe`,
  `roundhouse/editor/save`, and `roundhouse/editor/render`.
- A tile offers only the controls its entity's domain supports.

### Removed

- The dashboard per device, its URL path in setup, and the dashboard digest.
  Views of 0.1.0 are not carried over: each device starts with one empty view.
  Delete the old dashboards by hand.
- The snapshot-view option: choose the snapshot view in the view dialog.
- The skipped-cards sensor, and the repair issues for an auto-generated or a
  deleted dashboard.

## 0.1.0 (2026-11-12)

### Added

- Home Assistant integration that serves panel devices over MQTT: a dashboard
  per device, live entity state, commands, and alerts.
- Panel contract 1.0 in `contract/`: a JSON schema, the bitmap encodings, the
  versioning rules, and test vectors.
- A reference codec in Python that CI checks against every vector and the
  schema.
- Discovery of a device from its retained announce on `roundhouse/+/announce`.
- A setup flow that asks for the dashboard URL path, adds a numeric suffix when
  another device uses it, and creates the dashboard with a starter view.
- An existing dashboard is used as it is and is never overwritten.
- Options: the snapshot view (devices that sleep), the presence grace (default 2
  hours), and the alert count (20) and age (7 days).
- Repair issues for an unusable profile, a contract major version mismatch, a
  disabled MQTT birth message, an auto-generated dashboard, a deleted dashboard,
  and a view with more tiles than the densest layout holds.
- A device with an unusable profile or another contract major version receives
  only `meta`.
- Dashboard digest of `tile`, `button`, `thermostat`, `humidifier` and
  `entities` cards, in masonry and sections views; stacks and grids are
  flattened.
- Tile features become `controls` of the tile.
- Skipped cards and features are counted with their reasons: unsupported type,
  visibility, no entity, unsupported feature.
- The first layout with enough slots is chosen.
- A view that does not fit keeps its last published definition, also across a
  restart.
- A view fits when the layout with the most slots holds it; the device may
  announce its layouts in any order.
- An overflowing view raises a repair issue and a persistent notification that
  give the number of tiles to remove and say whether the device keeps an
  earlier version of the view.
- The view definition is digested 2 seconds after the last dashboard save and is
  published only when its content changes.
- State text in Home Assistant's language for lights, switches, fans, covers,
  valves, climate, water heaters, humidifiers, numbers, selects, locks, sensors,
  binary sensors, persons and alarm panels.
- State text uses the display precision, the unit, and local time.
- Icons resolve from the card, the entity registry, the entity, the translated
  state icon, and the domain default.
- Material Design Icons 7.4.47 is bundled.
- Icons are 4-bit alpha masks, cached by name and size.
- State messages carry an active flag, a color, and the attributes of the detail
  page, with every mode and option as a value and a translated label.
- Alert snapshots from a camera or an http(s) URL, with a 10 second timeout and
  a 5 MB cap.
- Snapshots are scaled to fit without enlarging and encoded as dithered `gray4`
  or `rgb565`, smaller if the device's payload limit needs it.
- Rasterizing, dithering and image fetching run off the event loop.
- Retained topics are tracked per device, and stale ones are cleared at startup.
- The full set of retained topics is republished after a reconnect.
- A send that fails while the broker is away is retried every 5 seconds and
  after a reconnect; the latest value is the one sent.
- Commands are accepted for lights, switches, fans, covers, climate, water
  heaters, humidifiers, numbers, selects, valves, locks, alarm panels, scenes,
  scripts and buttons, and only for entities on the device's views.
- Modes and numbers are checked against the entity and the tile's controls; any
  other value in `data` is refused.
- `unlock`, `open` and `alarm_disarm` need `confirmed: true`.
- A command's result is `ok`, `denied`, `invalid`, `needs_confirmation`,
  `timeout`, or the error text of the action.
- The last 32 request IDs are remembered; a repeat gets the stored result
  without a second call.
- A service call is capped at 10 seconds.
- `roundhouse.send_alert` with a title, a message, a severity, a snapshot, a
  tag, and action buttons; it returns the alert ID of each device.
- `roundhouse.acknowledge_alert` by alert ID or tag.
- The event `roundhouse_alert_acknowledged` carries the alert ID, the tag, and
  the device ID.
- A `notify` entity per device turns a message into an `event` alert.
- Alerts are stored with their images, aged by count and age, and published
  again after a restart.
- An alert action runs the service call declared in the alert; the device sends
  only the action ID.
- A snapshot that takes longer than 3 seconds does not delay its alert.
- An alert to several devices fetches its snapshot once.
- A stored alert image that a changed device profile cannot take is dropped
  from the alert.
- Removing a device clears its retained topics, its stored data, and its repair
  issues.
- Clearing a removed device's retained topics is retried every 60 seconds when
  it fails or the broker is away.
- A Home Assistant device per panel, with sensors for the battery level, the
  power mode (devices that sleep), the contract version, the skipped cards and
  the unread alerts, and a charging binary sensor.
- A presence tracker: home while the device is online and for a grace period
  after it goes offline; the grace period survives a restart.
- An admin-only Roundhouse sidebar panel that draws each view at the device's
  resolution, with live tiles and hatched overflow tiles.
- A websocket subscription for the panel: a snapshot after every digest and a
  state message after every state change.
- Install guide, a Mosquitto ACL example, and latency measurements in `docs/`.
- MQTT is plain, with a login per device.
- TLS is not supported.
