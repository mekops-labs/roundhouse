# Versioning

The contract version is `major.minor`. A device sends it in `announce`, and
Roundhouse sends it in `meta`.

## Minor version

A minor version adds only:

- optional fields to an existing object;
- new topics;
- new values in an open set (see `ENCODINGS.md`);
- new control types and new pixel formats.

A minor version never removes, renames, or retypes a field. It never makes an
optional field required, never changes a meaning, and never changes a binary
encoding.

## Major version

Any other change needs a new major version. Adding a value to a closed set
(`kind`, `severity`) is one.

## Receiver rules

- Ignore fields, topics, and open-set values that you do not know.
- Accept a peer whose major version equals yours, whatever its minor version.
- Refuse a peer with another major version and report it:
  - A device shows the mismatch on its screen.
  - Roundhouse raises a repair issue that names both versions. It publishes
    only `meta` for that device.
- Treat a payload that breaks the schema as invalid. Do not guess its meaning.

A device that announces a pixel format Roundhouse does not implement is
refused the same way: Roundhouse raises a repair issue and publishes only
`meta`.

## Tags and vectors

Each version is tagged `contract-vMAJOR.MINOR`. The directory
`vectors/vMAJOR.MINOR/` holds the complete vector set for that version. A new
minor version adds a new directory with the old vectors plus the new ones.
A device repository pins one tag and runs that directory.
