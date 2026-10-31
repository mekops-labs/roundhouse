"""Run every contract vector through the reference codec and the schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from custom_components.roundhouse import codec

CONTRACT = Path(__file__).parents[1] / "contract"
VECTORS = CONTRACT / "vectors" / "v1.0"
SCHEMA = json.loads((CONTRACT / "schema.json").read_text())
JSON_KINDS = (
    "announce",
    "availability",
    "status",
    "meta",
    "views",
    "state",
    "alert",
    "cmd",
    "result",
)
# Errors the schema cannot express: the payload is well formed.
SEMANTIC_ERRORS = {"major_mismatch"}


def _load(kinds: tuple[str, ...]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for kind in kinds:
        for path in sorted((VECTORS / kind).glob("*.json")):
            out.append((f"{kind}/{path.stem}", json.loads(path.read_text())))
    return out


def _payload(vec: dict[str, Any]) -> bytes:
    if "payload_text" in vec:
        return str(vec["payload_text"]).encode()
    return json.dumps(
        vec["payload"], separators=(",", ":"), ensure_ascii=False
    ).encode()


def _schema_errors(vec: dict[str, Any]) -> list[Any] | None:
    """Schema errors, or None when the payload is not JSON at all."""
    if vec["kind"] == "availability":
        doc: Any = _payload(vec).decode()
    else:
        try:
            doc = json.loads(_payload(vec))
        except ValueError:
            return None
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{vec['kind']}", "$defs": SCHEMA["$defs"]}
    )
    return list(validator.iter_errors(doc))


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_every_structured_topic_has_a_definition() -> None:
    assert set(JSON_KINDS) <= set(SCHEMA["$defs"])


def test_every_kind_has_valid_and_invalid_vectors() -> None:
    for kind in JSON_KINDS:
        vecs = [v for _, v in _load((kind,))]
        assert any(v["valid"] for v in vecs), kind
        if kind != "availability":
            assert any(not v["valid"] for v in vecs), kind


@pytest.mark.parametrize(("name", "vec"), _load(JSON_KINDS))
def test_codec_matches_vector(name: str, vec: dict[str, Any]) -> None:
    payload = _payload(vec)
    if vec["valid"]:
        assert codec.decode(vec["kind"], payload) == vec["decoded"]
    else:
        with pytest.raises(codec.ContractError) as err:
            codec.decode(vec["kind"], payload)
        assert err.value.code == vec["error"]


@pytest.mark.parametrize(("name", "vec"), _load(JSON_KINDS))
def test_schema_agrees_with_vector(name: str, vec: dict[str, Any]) -> None:
    errors = _schema_errors(vec)
    if vec["valid"] or vec["error"] in SEMANTIC_ERRORS:
        assert errors == []
    else:
        assert errors != [], "schema accepts a payload the vector rejects"


@pytest.mark.parametrize(("name", "vec"), _load(("bitmap",)))
def test_bitmap_vectors(name: str, vec: dict[str, Any]) -> None:
    data = bytes.fromhex(vec["payload_hex"])
    args = (vec["format"], vec["width"], vec["height"])
    if vec["valid"]:
        assert codec.decode_bitmap(*args, data) == vec["pixels"]
        assert codec.encode_bitmap(*args, vec["pixels"]) == data
    else:
        with pytest.raises(codec.ContractError) as err:
            codec.decode_bitmap(*args, data)
        assert err.value.code == vec["error"]


def test_topic_vectors() -> None:
    for case in json.loads((VECTORS / "topics.json").read_text()):
        parsed = codec.parse_topic(case["topic"])
        if case["device_id"] is None:
            assert parsed is None, case["topic"]
        else:
            assert parsed == (case["device_id"], case["name"], case["rest"])


def test_icon_topic_names() -> None:
    for icon, name in json.loads((VECTORS / "icons.json").read_text()):
        assert codec.icon_topic_name(icon) == name


def test_version_vectors() -> None:
    for case in json.loads((VECTORS / "versions.json").read_text()):
        assert codec.compatible(case["device"], case["peer"]) is case["compatible"]


def test_rgb565_vectors() -> None:
    for case in json.loads((VECTORS / "rgb565.json").read_text()):
        assert codec.rgb888_to_565(*case["rgb"]) == case["rgb565"]
