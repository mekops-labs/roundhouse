# Panel MQTT contract

Schema, encodings, and test vectors for the MQTT contract between Roundhouse
and a panel device. The current version is **1.0**.

- `schema.json` - JSON Schema (2020-12), one definition per structured topic
  under `$defs`.
- `ENCODINGS.md` - bitmap encodings and the topic table.
- `VERSIONING.md` - what each version number allows.
- `vectors/v1.0/` - test vectors for contract 1.0.

All topics sit under `roundhouse/<device_id>/`. Structured payloads are
compact UTF-8 JSON. Icons and images are raw bytes.

## Topics

| Topic | Direction | Retained | Payload |
| --- | --- | --- | --- |
| `announce` | device to HA | yes | `announce` |
| `availability` | device to HA | yes, last will | text `online` or `offline` |
| `status` | device to HA | yes | `status` |
| `meta` | HA to device | yes | `meta` |
| `views` | HA to device | yes | `views` |
| `state/<entity_id>` | HA to device | yes | `state` |
| `icon/<name>` | HA to device | yes | `mask4` bitmap, `icon_px` square |
| `alert/<id>` | HA to device | yes | `alert` |
| `alert/<id>/image` | HA to device | yes | bitmap in the display format |
| `alert/<id>/thumb` | HA to device | yes | bitmap in the display format |
| `cmd` | device to HA | no, QoS 1 | `cmd` |
| `result` | HA to device | no, QoS 1 | `result` |

An icon name replaces `:` with `_`: `mdi:lightbulb` is `icon/mdi_lightbulb`.
A bitmap has no header. Its size comes from the profile (`icon_px`) or from
the `image` and `thumb` objects of the `alert` payload.

## Pin and run the vectors

1. Copy the `contract/` directory at the tag `contract-vMAJOR.MINOR` into the
   device repository. Use a submodule, a subtree, or a release archive. Record
   the tag.
2. For each file under `vectors/v<MAJOR>.<MINOR>/<kind>/`, run the check below.
3. Run the four list files in `vectors/v<MAJOR>.<MINOR>/` the same way.
4. Fail the build on any mismatch.

A vector file is a JSON object with a `kind`, a `topic`, and:

- `payload` (JSON value) or `payload_text` (string): the message body. For a
  JSON payload, serialize it compactly.
- `valid`: whether a receiver must accept the payload.
- `decoded`: for a valid payload, the expected result. Unknown fields are
  dropped; absent optional fields take the default shown here.
- `error`: for an invalid payload, the expected code: `unparsable`, `invalid`,
  `unknown_format`, or `major_mismatch`.

A `bitmap` vector has `format` (`mask4`, `gray4`, or `rgb565`), `width`,
`height`, `payload_hex`, and for a valid one `pixels`, the rows of expected
pixel values.

The list files are `topics.json` (topic parsing), `icons.json` (icon topic
names), `versions.json` (version compatibility), and `rgb565.json` (color
packing).

Roundhouse's reference codec is `custom_components/roundhouse/codec.py`.
`tests/test_contract_vectors.py` runs it and the schema against every vector.
