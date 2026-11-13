import assert from "node:assert/strict";
import { test } from "node:test";

import {
  capacity,
  fitScale,
  frameHeight,
  layoutIndex,
  overflowCount,
  slotAt,
  slotCount,
  slotRects,
  tileRect,
} from "../../custom_components/roundhouse/panel/geometry.js";
import { vector } from "./helpers.mjs";

const tender = vector("tender");
const wall = vector("wall-panel");
const view = (n, layout = null) => ({ layout, tiles: Array.from({ length: n }, (_, i) => ({ entity_id: `light.l${i}` })) });

test("capacity is the densest layout", () => {
  assert.equal(capacity(tender), 15);
  assert.equal(capacity(wall), 8);
});

test("the densest layout need not come last", () => {
  const flipped = { ...tender, layouts: [...tender.layouts].reverse() };
  assert.equal(capacity(flipped), 15);
  assert.equal(layoutIndex(flipped, view(20, null)), 0);
  assert.equal(overflowCount(flipped, view(10, 0)), 0);
});

test("a view is drawn in its layout, or the densest one when it overflows", () => {
  assert.equal(layoutIndex(tender, view(3, 0)), 0);
  assert.equal(layoutIndex(tender, view(3, 1)), 1);
  assert.equal(layoutIndex(tender, view(20, null)), 1);
  assert.equal(layoutIndex(wall, view(20, null)), 1);
});

test("a slot is the rectangle the device announced", () => {
  assert.deepEqual(tileRect(tender, 0, 0), { x: 12, y: 92, w: 252, h: 185 });
  assert.deepEqual(tileRect(tender, 1, 14), { x: 12 + 2 * 176, y: 92 + 4 * 157, w: 164, h: 145 });
  assert.deepEqual(tileRect(wall, 1, 7), { x: 12 + 3 * 197, y: 68 + 178, w: 185, h: 166 });
});

test("tiles past the last slot continue the grid below the screen", () => {
  const first = tileRect(tender, 1, 15);
  assert.deepEqual(first, { x: 12, y: 960 + 48, w: 164, h: 145 });
  assert.deepEqual(tileRect(tender, 1, 16), { x: 12 + 176, y: 960 + 48, w: 164, h: 145 });
  assert.deepEqual(tileRect(tender, 1, 18), { x: 12, y: 960 + 48 + 157, w: 164, h: 145 });
  // None of the excess overlaps the screen or the tab strip.
  for (let i = 15; i < 40; i++) assert.ok(tileRect(tender, 1, i).y >= 960);
  assert.deepEqual(tileRect(wall, 1, 8), { x: 12, y: 480 + 48, w: 185, h: 166 });
});

test("a single-slot layout still has a pitch", () => {
  const one = {
    display: { width: 100, height: 200 },
    layouts: [{ columns: 1, slots: [[5, 5, 90, 40]] }],
  };
  assert.deepEqual(tileRect(one, 0, 1), { x: 5, y: 200 + 48, w: 90, h: 40 });
  assert.deepEqual(tileRect(one, 0, 2), { x: 5, y: 200 + 48 + 52, w: 90, h: 40 });
});

test("the drawing is as tall as the screen unless tiles overflow", () => {
  assert.equal(frameHeight(tender, view(15, 1)), 960);
  assert.equal(overflowCount(tender, view(15, 1)), 0);
  assert.equal(overflowCount(tender, view(18)), 3);
  const tall = frameHeight(tender, view(18));
  assert.equal(tall, 960 + 48 + 145 + 24); // one overflow row below the screen
  assert.ok(frameHeight(tender, view(25)) > tall);
});

test("the scale only shrinks", () => {
  assert.equal(fitScale(540, 1000), 1);
  assert.equal(fitScale(540, 270), 0.5);
  assert.equal(fitScale(540, 0), 1);
});

test("a bad layout index falls back to the densest layout", () => {
  for (const layout of [undefined, null, -1, 2, 1.5, "1"]) {
    assert.equal(layoutIndex(tender, view(1, layout)), 1, String(layout));
  }
});

test("the slots of a view are those of its own layout", () => {
  assert.equal(slotCount(tender, view(1, 0)), 8);
  assert.equal(slotCount(tender, view(1, 1)), 15);
  assert.equal(slotCount(tender, view(1, 9)), 15);
  assert.equal(slotRects(tender, view(1, 0)).length, 8);
  assert.equal(overflowCount(tender, view(9, 0)), 1); // 8 slots in the small layout
});

test("a point finds the slot under it", () => {
  const v = view(3, 0);
  assert.equal(slotAt(tender, v, 20, 100), 0);
  assert.equal(slotAt(tender, v, 280, 100), 1);
  assert.equal(slotAt(tender, v, 0, 0), -1); // the header
  assert.equal(slotAt(tender, v, 270, 100), -1); // the gap between slots
});
