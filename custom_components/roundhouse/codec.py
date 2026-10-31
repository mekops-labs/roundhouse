"""Reference codec for the panel MQTT contract.

Pure functions with no Home Assistant imports. The JSON schema in
`contract/schema.json` and the vectors in `contract/vectors/` define the
contract; this module is the Python implementation that CI checks against them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

SUPPORTED_MAJOR = 1
PIXEL_FORMATS = ("gray4", "rgb565")
BITMAP_FORMATS = ("mask4", "gray4", "rgb565")

_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)$")
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_ALERT_ID = re.compile(r"^[a-z0-9]{1,32}$")
_DEVICE_ID = re.compile(r"^[a-z0-9_-]{1,64}$")
_TOPIC_NAMES = frozenset(
    {
        "announce",
        "availability",
        "status",
        "meta",
        "views",
        "state",
        "icon",
        "alert",
        "cmd",
        "result",
    }
)


class ContractError(ValueError):
    """A payload broke the contract.

    `code` is one of: `unparsable`, `invalid`, `unknown_format`,
    `major_mismatch`.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# --- versions ---------------------------------------------------------------


def parse_version(text: object) -> tuple[int, int]:
    """Parse `major.minor`."""
    match = _VERSION.match(text) if isinstance(text, str) else None
    if match is None:
        raise ContractError("invalid", f"bad contract version {text!r}")
    return int(match.group(1)), int(match.group(2))


def compatible(own: str, peer: str) -> bool:
    """Return whether two contract versions can talk: the major must match."""
    return parse_version(own)[0] == parse_version(peer)[0]


def _check_major(text: object) -> None:
    major, _ = parse_version(text)
    if major != SUPPORTED_MAJOR:
        raise ContractError(
            "major_mismatch", f"contract {text} (supported: {SUPPORTED_MAJOR}.x)"
        )


# --- topics -----------------------------------------------------------------


def parse_topic(topic: str) -> tuple[str, str, str | None] | None:
    """Split `roundhouse/<device>/<name>[/<rest>]`; None for any other topic."""
    parts = topic.split("/", 3)
    if len(parts) < 3 or parts[0] != "roundhouse":
        return None
    device_id, name = parts[1], parts[2]
    if not _DEVICE_ID.match(device_id) or name not in _TOPIC_NAMES:
        return None
    return device_id, name, parts[3] if len(parts) == 4 else None


def icon_topic_name(icon: str) -> str:
    """Return the topic segment of an icon: `:` becomes `_`."""
    return icon.replace(":", "_")


# --- field checks -----------------------------------------------------------


def _fail(path: str, why: str) -> ContractError:
    return ContractError("invalid", f"{path}: {why}")


def _obj(v: Any, path: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise _fail(path, "expected an object")
    return v


def _req(o: dict[str, Any], key: str, path: str) -> Any:
    if key not in o:
        raise _fail(path, f"missing {key!r}")
    return o[key]


def _str(v: Any, path: str, *, min_len: int = 0) -> str:
    if not isinstance(v, str) or len(v) < min_len:
        raise _fail(path, "expected a string")
    return v


def _int(v: Any, path: str, *, lo: int | None = None, hi: int | None = None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise _fail(path, "expected an integer")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise _fail(path, f"{v} out of range")
    return v


def _bool(v: Any, path: str) -> bool:
    if not isinstance(v, bool):
        raise _fail(path, "expected a boolean")
    return v


def _list(v: Any, path: str, *, min_items: int = 0) -> list[Any]:
    if not isinstance(v, list) or len(v) < min_items:
        raise _fail(path, "expected an array")
    return v


def _enum(v: Any, allowed: tuple[str, ...], path: str) -> str:
    if v not in allowed:
        raise _fail(path, f"{v!r} not one of {allowed}")
    return str(v)


def _pattern(v: Any, rx: re.Pattern[str], path: str) -> str:
    s = _str(v, path)
    if not rx.match(s):
        raise _fail(path, f"{s!r} is malformed")
    return s


def _rect(v: Any, path: str) -> list[int]:
    items = _list(v, path)
    if len(items) != 4:
        raise _fail(path, "a rectangle has four numbers")
    return [
        _int(items[0], path, lo=0),
        _int(items[1], path, lo=0),
        _int(items[2], path, lo=1),
        _int(items[3], path, lo=1),
    ]


def _size(v: Any, path: str) -> dict[str, int]:
    o = _obj(v, path)
    return {
        "width": _int(_req(o, "width", path), f"{path}.width", lo=1),
        "height": _int(_req(o, "height", path), f"{path}.height", lo=1),
    }


def _opt(
    o: dict[str, Any], key: str, conv: Callable[[Any, str], Any], path: str
) -> Any:
    """Convert an optional field; absent and null both give None."""
    return None if o.get(key) is None else conv(o[key], f"{path}.{key}")


# --- structured topics ------------------------------------------------------


def _layout(raw: Any, i: int) -> dict[str, Any]:
    p = f"layouts[{i}]"
    lay = _obj(raw, p)
    slots = _list(_req(lay, "slots", p), f"{p}.slots", min_items=1)
    return {
        "columns": _int(_req(lay, "columns", p), f"{p}.columns", lo=1),
        "slots": [_rect(s, f"{p}.slots") for s in slots],
    }


def _announce(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "announce")
    _check_major(_req(o, "contract", "announce"))
    disp = _obj(_req(o, "display", "announce"), "display")
    fmt = _req(disp, "format", "display")
    if fmt not in PIXEL_FORMATS:
        raise ContractError("unknown_format", f"pixel format {fmt!r}")
    chrome = _obj(_req(o, "chrome", "announce"), "chrome")
    layouts = _list(_req(o, "layouts", "announce"), "layouts", min_items=1)
    limits = _obj(_req(o, "limits", "announce"), "limits")
    return {
        "contract": _str(o["contract"], "contract"),
        "model": _str(_req(o, "model", "announce"), "model", min_len=1),
        "fw": _str(_req(o, "fw", "announce"), "fw"),
        "wapp": _str(_req(o, "wapp", "announce"), "wapp"),
        "display": {
            "width": _int(_req(disp, "width", "display"), "display.width", lo=1),
            "height": _int(_req(disp, "height", "display"), "display.height", lo=1),
            "format": str(fmt),
        },
        "chrome": {
            "header": _rect(_req(chrome, "header", "chrome"), "chrome.header"),
            "tabs": _rect(_req(chrome, "tabs", "chrome"), "chrome.tabs"),
        },
        "layouts": [_layout(raw, i) for i, raw in enumerate(layouts)],
        "icon_px": _int(_req(o, "icon_px", "announce"), "icon_px", lo=1),
        "image_box": _size(_req(o, "image_box", "announce"), "image_box"),
        "thumb_box": _size(_req(o, "thumb_box", "announce"), "thumb_box"),
        "features": [
            _str(f, "features")
            for f in _list(_req(o, "features", "announce"), "features")
        ],
        "limits": {
            "max_payload": _int(
                _req(limits, "max_payload", "limits"), "limits.max_payload", lo=1
            )
        },
    }


def _status(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "status")
    return {
        "battery": _opt(o, "battery", lambda v, p: _int(v, p, lo=0, hi=100), "status"),
        "charging": _opt(o, "charging", _bool, "status"),
        "power_mode": _str(_req(o, "power_mode", "status"), "power_mode", min_len=1),
    }


def _meta(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "meta")
    _check_major(_req(o, "contract", "meta"))
    return {
        "contract": _str(o["contract"], "contract"),
        "language": _str(_req(o, "language", "meta"), "language", min_len=1),
        "views_hash": _str(_req(o, "views_hash", "meta"), "views_hash"),
    }


def _control(v: Any, path: str) -> dict[str, Any]:
    o = _obj(v, path)
    out: dict[str, Any] = {
        "type": _str(_req(o, "type", path), f"{path}.type", min_len=1)
    }
    if "values" in o:
        out["values"] = [
            _str(x, f"{path}.values") for x in _list(o["values"], f"{path}.values")
        ]
    return out


def _tile(v: Any, path: str) -> dict[str, Any]:
    o = _obj(v, path)
    kinds = ("toggle", "activate", "readonly")
    out: dict[str, Any] = {
        "entity_id": _pattern(
            _req(o, "entity_id", path), _ENTITY_ID, f"{path}.entity_id"
        ),
        "name": _str(_req(o, "name", path), f"{path}.name"),
        "kind": _enum(_req(o, "kind", path), kinds, f"{path}.kind"),
        "domain": _str(_req(o, "domain", path), f"{path}.domain", min_len=1),
    }
    if "controls" in o:
        out["controls"] = [
            _control(c, f"{path}.controls")
            for c in _list(o["controls"], f"{path}.controls")
        ]
    return out


def _view(raw: Any, i: int) -> dict[str, Any]:
    p = f"views[{i}]"
    v = _obj(raw, p)
    return {
        "path": _str(_req(v, "path", p), f"{p}.path", min_len=1),
        "title": _str(_req(v, "title", p), f"{p}.title"),
        "layout": _int(_req(v, "layout", p), f"{p}.layout", lo=0),
        "tiles": [
            _tile(t, f"{p}.tiles") for t in _list(_req(v, "tiles", p), f"{p}.tiles")
        ],
    }


def _views(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "views")
    snapshot = _req(o, "snapshot_view", "views")
    return {
        "views": [
            _view(v, i) for i, v in enumerate(_list(_req(o, "views", "views"), "views"))
        ],
        "snapshot_view": None if snapshot is None else _str(snapshot, "snapshot_view"),
        "skipped": _int(_req(o, "skipped", "views"), "skipped", lo=0),
    }


def _state(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "state")
    color = o.get("color")
    if color is not None:
        items = _list(color, "color")
        if len(items) != 3:
            raise _fail("color", "expected three numbers")
        color = [_int(c, "color", lo=0, hi=255) for c in items]
    attrs = o.get("attributes")
    return {
        "text": _str(_req(o, "text", "state"), "text"),
        "on": _bool(_req(o, "on", "state"), "on"),
        "available": _bool(_req(o, "available", "state"), "available"),
        "icon": _str(_req(o, "icon", "state"), "icon", min_len=1),
        "color": color,
        "attributes": {} if attrs is None else _obj(attrs, "attributes"),
    }


def _action(v: Any, path: str) -> dict[str, Any]:
    o = _obj(v, path)
    return {
        "id": _str(_req(o, "id", path), f"{path}.id", min_len=1),
        "label": _str(_req(o, "label", path), f"{path}.label"),
        "confirm": _bool(o.get("confirm", False), f"{path}.confirm"),
    }


def _alert(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "alert")
    severities = ("critical", "warning", "event")
    return {
        "title": _str(_req(o, "title", "alert"), "title"),
        "message": _str(_req(o, "message", "alert"), "message"),
        "severity": _enum(_req(o, "severity", "alert"), severities, "severity"),
        "time": _int(_req(o, "time", "alert"), "time", lo=0),
        "read": _bool(_req(o, "read", "alert"), "read"),
        "actions": [
            _action(a, "actions") for a in _list(_req(o, "actions", "alert"), "actions")
        ],
        "image": _opt(o, "image", _size, "alert"),
        "thumb": _opt(o, "thumb", _size, "alert"),
    }


def _cmd(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "cmd")
    rid = _str(_req(o, "req", "cmd"), "req", min_len=1)
    if len(rid) > 64:
        raise _fail("req", "longer than 64 characters")
    confirmed = _bool(o.get("confirmed", False), "confirmed")
    if "entity_id" in o:
        data = o.get("data")
        return {
            "req": rid,
            "entity_id": _pattern(o["entity_id"], _ENTITY_ID, "entity_id"),
            "action": _str(_req(o, "action", "cmd"), "action", min_len=1),
            "data": {} if data is None else _obj(data, "data"),
            "confirmed": confirmed,
        }
    if "alert" in o:
        return {
            "req": rid,
            "alert": _pattern(o["alert"], _ALERT_ID, "alert"),
            "action_id": _str(_req(o, "action_id", "cmd"), "action_id", min_len=1),
            "confirmed": confirmed,
        }
    if "ack" in o:
        return {"req": rid, "ack": _pattern(o["ack"], _ALERT_ID, "ack")}
    raise _fail("cmd", "no entity_id, alert, or ack")


def _result(doc: Any) -> dict[str, Any]:
    o = _obj(doc, "result")
    return {
        "req": _str(_req(o, "req", "result"), "req", min_len=1),
        "result": _str(_req(o, "result", "result"), "result", min_len=1),
    }


_DECODERS: dict[str, Callable[[Any], Any]] = {
    "announce": _announce,
    "status": _status,
    "meta": _meta,
    "views": _views,
    "state": _state,
    "alert": _alert,
    "cmd": _cmd,
    "result": _result,
}


def decode(kind: str, payload: bytes) -> Any:
    """Decode and check one structured payload; raise `ContractError` if bad.

    `availability` is plain text, every other kind is UTF-8 JSON. Unknown
    fields are dropped and optional fields get their default.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ContractError("unparsable", "not UTF-8") from err
    if kind == "availability":
        if text not in ("online", "offline"):
            raise _fail("availability", f"{text!r}")
        return text
    try:
        decoder = _DECODERS[kind]
    except KeyError:
        raise ValueError(f"unknown kind {kind!r}") from None
    try:
        doc = json.loads(text)
    except ValueError as err:
        raise ContractError("unparsable", str(err)) from err
    return decoder(doc)


def encode(doc: Any) -> bytes:
    """Serialize a structured payload as compact UTF-8 JSON."""
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


# --- bitmaps ----------------------------------------------------------------


def rgb888_to_565(r: int, g: int, b: int) -> int:
    """Pack an 8-bit-per-channel color into `rgb565`."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _stride(fmt: str, width: int) -> int:
    return 2 * width if fmt == "rgb565" else (width + 1) // 2


def _check_bitmap(fmt: str, width: int, height: int) -> None:
    if fmt not in BITMAP_FORMATS:
        raise _fail("format", f"{fmt!r} is not a bitmap format")
    if width < 1 or height < 1:
        raise _fail("size", "width and height must be at least 1")


def decode_bitmap(fmt: str, width: int, height: int, data: bytes) -> list[list[int]]:
    """Decode raw bitmap bytes into rows of pixel values.

    `mask4` and `gray4` give values 0..15. `rgb565` gives 16-bit values.
    Rows start on a byte boundary. The length must match exactly.
    """
    _check_bitmap(fmt, width, height)
    stride = _stride(fmt, width)
    if len(data) != stride * height:
        raise _fail("bitmap", f"{len(data)} bytes, expected {stride * height}")
    rows: list[list[int]] = []
    for y in range(height):
        row = data[y * stride : (y + 1) * stride]
        if fmt == "rgb565":
            rows.append([row[2 * x] | (row[2 * x + 1] << 8) for x in range(width)])
        else:
            rows.append(
                [
                    (row[x // 2] >> 4) if x % 2 == 0 else (row[x // 2] & 0x0F)
                    for x in range(width)
                ]
            )
    return rows


def encode_bitmap(fmt: str, width: int, height: int, rows: list[list[int]]) -> bytes:
    """Encode rows of pixel values; the inverse of `decode_bitmap`."""
    _check_bitmap(fmt, width, height)
    if len(rows) != height or any(len(r) != width for r in rows):
        raise _fail("bitmap", "rows do not match the size")
    out = bytearray()
    for row in rows:
        if fmt == "rgb565":
            for px in row:
                out += _int(px, "pixel", lo=0, hi=0xFFFF).to_bytes(2, "little")
        else:
            packed = bytearray((width + 1) // 2)
            for x, px in enumerate(row):
                v = _int(px, "pixel", lo=0, hi=15)
                packed[x // 2] |= v << 4 if x % 2 == 0 else v
            out += packed
    return bytes(out)
