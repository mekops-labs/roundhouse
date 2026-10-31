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
