# Changelog

## Unreleased

- Add the integration skeleton, CI, and Home Assistant internals notes.
- Add panel contract 1.0: JSON schema, encodings, versioning rules, and vectors.
- Add the reference codec, checked against every vector in CI.
- Add discovery, the setup flow with dashboard creation, options, the retained-topic publisher with stale cleanup and resync, and repair issues.
- Digest the dashboard into a view definition: supported cards, stacks, tile features, layouts, overflow handling, and repair issues for strategy, deleted, and overflowing dashboards.
- Render entity states for the device: translated state text, icons from a bundled Material Design Icons font as 4-bit masks, colors, detail-page attributes, and retained `state/` and `icon/` topics.
- Add alert image fetching and dithering (gray4 and rgb565) within the device's payload limit.
- Run device commands behind an allowlist: per-domain actions, value checks against the entity and the tile, confirmation for lock and alarm actions, request-ID dedupe, a 10 s cap, and a result for every command.
- Add alerts: `roundhouse.send_alert` and `roundhouse.acknowledge_alert`, a notify entity per device, persistent storage with aging, snapshots, action buttons routed through the command checks, and the `roundhouse_alert_acknowledged` event.
