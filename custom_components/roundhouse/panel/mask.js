// Decode the 4-bit alpha masks the device receives, and tint them.

// A mask is `size` x `size`, two pixels a byte (left pixel in the high nibble),
// each row starting on a byte boundary. Returns alpha values 0-255.
export function decodeMask(base64, size) {
  const raw = atob(base64);
  const stride = Math.ceil(size / 2);
  if (raw.length !== stride * size) {
    throw new Error(`mask is ${raw.length} bytes, expected ${stride * size}`);
  }
  const alpha = new Uint8Array(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const byte = raw.charCodeAt(y * stride + (x >> 1));
      const nibble = x % 2 === 0 ? byte >> 4 : byte & 0x0f;
      alpha[y * size + x] = nibble * 17;
    }
  }
  return alpha;
}

// RGBA pixels of the mask in one color, as the device tints it.
export function tint(alpha, rgb) {
  const out = new Uint8ClampedArray(alpha.length * 4);
  for (let i = 0; i < alpha.length; i++) {
    out[i * 4] = rgb[0];
    out[i * 4 + 1] = rgb[1];
    out[i * 4 + 2] = rgb[2];
    out[i * 4 + 3] = alpha[i];
  }
  return out;
}
