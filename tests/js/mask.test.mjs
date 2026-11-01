import assert from "node:assert/strict";
import { test } from "node:test";

import { decodeMask, tint } from "../../custom_components/roundhouse/panel/mask.js";
import { golden, nibbleBase64 } from "./helpers.mjs";

test("a mask is two pixels a byte, high nibble first", () => {
  const b64 = Buffer.from([0x0f, 0x81]).toString("base64");
  assert.deepEqual([...decodeMask(b64, 2)], [0, 255, 136, 17]);
});

test("rows of an odd size start on a byte boundary", () => {
  const rows = [[1, 2, 3], [4, 5, 6], [7, 8, 9]];
  const bytes = Buffer.from([0x12, 0x30, 0x45, 0x60, 0x78, 0x90]);
  assert.deepEqual([...decodeMask(bytes.toString("base64"), 3)], rows.flat().map((v) => v * 17));
  assert.equal(nibbleBase64(rows), bytes.toString("base64"));
});

test("a mask of the wrong length is refused", () => {
  assert.throws(() => decodeMask(Buffer.from([1, 2, 3]).toString("base64"), 2), /expected 2/);
});

test("tinting keeps the mask as alpha", () => {
  const out = tint(Uint8Array.from([0, 255, 17]), [10, 20, 30]);
  assert.deepEqual([...out], [10, 20, 30, 0, 10, 20, 30, 255, 10, 20, 30, 17]);
});

test("the browser reads the masks the integration rasterizes", () => {
  const g = golden();
  for (const key of Object.keys(g).filter((k) => k.startsWith("mask:"))) {
    const rows = g[key];
    const alpha = decodeMask(nibbleBase64(rows), rows.length);
    assert.deepEqual([...alpha], rows.flat().map((v) => v * 17), key);
  }
});
