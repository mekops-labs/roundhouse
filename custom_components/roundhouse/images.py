"""Scale, dither, and encode alert images for a device.

Uses Pillow. Every function here is blocking: call it from the executor.
"""

from __future__ import annotations

import io
import sys
from array import array

from PIL import Image, UnidentifiedImageError

# Smallest edge `encode_within` shrinks an image to before giving up.
MIN_EDGE = 16


class ImageError(ValueError):
    """The image cannot be decoded."""


def fit_size(src: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Return `src` scaled to fit `box`, aspect kept, never enlarged."""
    sw, sh = src
    scale = min(box[0] / sw, box[1] / sh, 1.0)
    return max(1, round(sw * scale)), max(1, round(sh * scale))


def _open(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as err:
        raise ImageError(str(err)) from err
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def _gray_palette() -> Image.Image:
    palette = Image.new("P", (1, 1))
    flat: list[int] = []
    for level in range(16):
        flat += [level * 17] * 3
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return palette


def _pack_gray4(indices: bytes, width: int, height: int) -> bytes:
    out = bytearray()
    for y in range(height):
        row = indices[y * width : (y + 1) * width]
        if width % 2:
            row += b"\x00"
        out += bytes((a << 4) | b for a, b in zip(row[0::2], row[1::2], strict=True))
    return bytes(out)


def _pack_rgb565(rgb: bytes) -> bytes:
    pixels = array(
        "H",
        (
            ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3], strict=True)
        ),
    )
    if sys.byteorder == "big":
        pixels.byteswap()
    return pixels.tobytes()


def encode(
    image: Image.Image, fmt: str, size: tuple[int, int]
) -> tuple[bytes, int, int]:
    """Scale an image to `size` and encode it; return (bytes, width, height)."""
    width, height = size
    scaled = image.resize((width, height), Image.Resampling.LANCZOS)
    if fmt == "gray4":
        gray = scaled.convert("L").convert("RGB")
        dithered = gray.quantize(
            palette=_gray_palette(), dither=Image.Dither.FLOYDSTEINBERG
        )
        return _pack_gray4(dithered.tobytes(), width, height), width, height
    if fmt == "rgb565":
        return _pack_rgb565(scaled.tobytes()), width, height
    raise ValueError(f"unknown pixel format {fmt!r}")


def encode_image(data: bytes, fmt: str, box: tuple[int, int]) -> tuple[bytes, int, int]:
    """Decode `data`, fit it in `box`, and encode it in the display format."""
    image = _open(data)
    return encode(image, fmt, fit_size(image.size, box))


def encode_within(
    data: bytes, fmt: str, box: tuple[int, int], max_bytes: int
) -> tuple[bytes, int, int] | None:
    """Encode at the largest size that fits `max_bytes`, or None if none does."""
    image = _open(data)
    size = fit_size(image.size, box)
    while True:
        encoded = encode(image, fmt, size)
        if len(encoded[0]) <= max_bytes:
            return encoded
        size = (size[0] * 3 // 4, size[1] * 3 // 4)
        if min(size) < MIN_EDGE:
            return None
