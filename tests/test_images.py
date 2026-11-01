"""Scaling, dithering, and encoding of alert images."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from custom_components.roundhouse import codec, images

GOLDEN = json.loads((Path(__file__).parent / "golden/rendering.json").read_text())


def png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def gradient(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h))
    for x in range(w):
        v = round(x * 255 / max(w - 1, 1))
        for y in range(h):
            im.putpixel((x, y), (v, v, v))
    return im


def test_fit_keeps_aspect_and_never_enlarges() -> None:
    assert images.fit_size((1920, 1080), (480, 640)) == (480, 270)
    assert images.fit_size((1080, 1920), (480, 640)) == (360, 640)
    assert images.fit_size((100, 50), (480, 640)) == (100, 50)
    assert images.fit_size((1, 5000), (480, 640)) == (1, 640)


def test_gray4_golden_gradient() -> None:
    data, w, h = images.encode_image(png(gradient(16, 8)), "gray4", (16, 8))
    assert (w, h) == (16, 8)
    got = codec.decode_bitmap("gray4", 16, 8, data)
    want = codec.decode_bitmap(
        "gray4", 16, 8, bytes.fromhex(GOLDEN["gray4:gradient-16x8"])
    )
    diffs = [
        abs(a - b)
        for g, x in zip(got, want, strict=True)
        for a, b in zip(g, x, strict=True)
    ]
    assert sum(diffs) / len(diffs) <= 0.5
    assert got[0][0] == 0 and got[0][15] == 15


def test_gray4_levels_and_odd_width_padding() -> None:
    white, _, _ = images.encode_image(
        png(Image.new("RGB", (4, 2), "white")), "gray4", (4, 2)
    )
    assert white == b"\xff\xff\xff\xff"
    black, *_ = images.encode_image(
        png(Image.new("RGB", (3, 2), "black")), "gray4", (3, 2)
    )
    assert black == b"\x00" * 4  # rows of 3 pixels take 2 bytes
    data, _, _ = images.encode_image(
        png(Image.new("RGB", (5, 3), (128, 128, 128))), "gray4", (5, 3)
    )
    assert len(data) == 3 * 3
    rows = codec.decode_bitmap("gray4", 5, 3, data)
    assert all(7 <= v <= 8 for row in rows for v in row)


def test_gray4_dithering_spreads_error() -> None:
    data, *_ = images.encode_image(
        png(Image.new("RGB", (32, 32), (136, 136, 136))), "gray4", (32, 32)
    )
    levels = {v for row in codec.decode_bitmap("gray4", 32, 32, data) for v in row}
    assert levels == {8}  # exactly on a level: no dither noise
    data, *_ = images.encode_image(
        png(Image.new("RGB", (32, 32), (130, 130, 130))), "gray4", (32, 32)
    )
    levels = {v for row in codec.decode_bitmap("gray4", 32, 32, data) for v in row}
    assert levels == {7, 8}  # between two levels: error diffusion mixes them


def test_rgb565_matches_the_contract_packing() -> None:
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
        (0, 0, 0),
        (8, 4, 8),
    ]
    im = Image.new("RGB", (6, 2))
    for x, c in enumerate(colors):
        for y in range(2):
            im.putpixel((x, y), c)
    data, _, _ = images.encode_image(png(im), "rgb565", (6, 2))
    assert data.hex() == GOLDEN["rgb565:colors-6x2"]
    row = codec.decode_bitmap("rgb565", 6, 2, data)[0]
    assert row == [codec.rgb888_to_565(*c) for c in colors]


def test_scaling_to_the_box() -> None:
    data, w, h = images.encode_image(
        png(Image.new("RGB", (1920, 1080), "red")), "rgb565", (480, 640)
    )
    assert (w, h) == (480, 270) and len(data) == 480 * 270 * 2


def test_alpha_is_composited_over_white() -> None:
    clear = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
    data, *_ = images.encode_image(png(clear), "gray4", (4, 2))
    assert data == b"\xff" * 4


def test_encode_within_shrinks_until_it_fits() -> None:
    src = png(gradient(400, 300))
    _, fw, fh = images.encode_within(src, "rgb565", (400, 300), 10**9) or (b"", 0, 0)
    assert (fw, fh) == (400, 300)
    result = images.encode_within(src, "rgb565", (400, 300), 60_000)
    assert result is not None
    data, w, h = result
    assert len(data) <= 60_000 and (w, h) < (400, 300)
    assert abs(w / h - 400 / 300) < 0.05


def test_encode_within_gives_up_when_nothing_fits() -> None:
    assert (
        images.encode_within(png(gradient(400, 300)), "rgb565", (400, 300), 100) is None
    )


def test_undecodable_data_raises() -> None:
    with pytest.raises(images.ImageError):
        images.encode_image(b"not an image", "gray4", (10, 10))


def test_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unknown pixel format"):
        images.encode_image(png(Image.new("RGB", (2, 2))), "rgb888", (2, 2))
