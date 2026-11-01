import assert from "node:assert/strict";
import { test } from "node:test";

import { drawView, fitText, tileColors } from "../../custom_components/roundhouse/panel/draw.js";
import { emptyModel, reduce } from "../../custom_components/roundhouse/panel/state.js";
import { nibbleBase64, recorder, vector } from "./helpers.mjs";

const tender = vector("tender");
const wall = vector("wall-panel");

function mask(size) {
  return nibbleBase64(Array.from({ length: size }, () => Array(size).fill(15)));
}

function model(profile, view, states) {
  const views = [view];
  const icons = Object.fromEntries(Object.values(states).map((s) => [s.icon, mask(profile.icon_px)]));
  return reduce(emptyModel(), { type: "snapshot", profile, views, dashboard: "config", states, icons });
}

function tileFor(i, name = `Tile ${i}`) {
  return { entity_id: `light.l${i}`, name, kind: "toggle", domain: "light" };
}

function run(profile, view, states) {
  const { ctx, calls } = recorder();
  const icons = [];
  const height = drawView(ctx, profile, model(profile, view, states), view, {
    drawIcon: (_c, rgba, size, x, y) => icons.push({ rgba, size, x, y }),
  });
  return { calls, icons, height };
}

const texts = (calls) => calls.filter((c) => c.name === "fillText").map((c) => c.args[0]);

test("a view is drawn at the screen's own size with its chrome and tiles", () => {
  const view = { path: "home", title: "Home", layout: 0, tiles: [tileFor(0, "Lamp"), tileFor(1, "Door")], count: 2, capacity: 15 };
  const states = {
    "light.l0": { text: "On · 80%", on: true, available: true, icon: "mdi:lightbulb", color: null },
    "light.l1": { text: "Off", on: false, available: true, icon: "mdi:lightbulb-off", color: null },
  };
  const { calls, icons, height } = run(tender, view, states);
  assert.equal(height, 960);
  assert.ok(texts(calls).includes("Home"), "the view title is in the header");
  for (const t of ["Lamp", "On · 80%", "Door", "Off"]) assert.ok(texts(calls).includes(t), t);
  assert.equal(icons.length, 2);
  // The icon sits in the middle of its slot, at the announced size.
  assert.equal(icons[0].size, 64);
  assert.equal(icons[0].x, Math.round(12 + (252 - 64) / 2));
});

test("on a gray display the icon is tinted white on an on tile and black on an off tile", () => {
  const view = { path: "h", title: "H", layout: 0, tiles: [tileFor(0), tileFor(1)] };
  const states = {
    "light.l0": { text: "On", on: true, available: true, icon: "mdi:a", color: [255, 0, 0] },
    "light.l1": { text: "Off", on: false, available: true, icon: "mdi:b", color: null },
  };
  const { icons } = run(tender, view, states);
  assert.deepEqual([...icons[0].rgba.slice(0, 3)], [255, 255, 255]); // the red color is ignored
  assert.deepEqual([...icons[1].rgba.slice(0, 3)], [0, 0, 0]);
});

test("on a color display an on tile uses the state color", () => {
  const view = { path: "h", title: "H", layout: 0, tiles: [tileFor(0)] };
  const states = { "light.l0": { text: "On", on: true, available: true, icon: "mdi:a", color: [10, 200, 30] } };
  const { icons } = run(wall, view, states);
  assert.deepEqual([...icons[0].rgba.slice(0, 3)], [10, 200, 30]);
  assert.equal(icons[0].size, 48);
});

test("tiles beyond the capacity are hatched in red with n / max", () => {
  const tiles = Array.from({ length: 17 }, (_, i) => tileFor(i));
  const view = { path: "h", title: "H", layout: null, tiles, count: 17, capacity: 15 };
  const states = Object.fromEntries(tiles.map((t) => [t.entity_id, { text: "On", on: true, available: true, icon: "mdi:a", color: null }]));
  const { calls, icons, height } = run(tender, view, states);
  assert.equal(icons.length, 15, "the excess draws no icon");
  const labels = texts(calls);
  assert.ok(labels.includes("16 / 15") && labels.includes("17 / 15"));
  assert.ok(!labels.includes("15 / 15"));
  assert.ok(labels.includes("Does not fit: remove 2 tile(s)"));
  assert.ok(height > 960);
  const red = calls.filter((c) => c.name === "strokeRect" && c.style.strokeStyle === "#d32f2f");
  assert.equal(red.length, 2);
  assert.deepEqual(red[0].args, [12, 1008, 164, 145]); // the first excess tile, below the screen
  const lines = calls.filter((c) => c.name === "lineTo" && c.style.strokeStyle === "#d32f2f");
  assert.ok(lines.length > 4, "hatch lines");
});

test("an exactly full view has no overflow marks", () => {
  const tiles = Array.from({ length: 15 }, (_, i) => tileFor(i));
  const view = { path: "h", title: "H", layout: 1, tiles };
  const { calls, height } = run(tender, view, {});
  assert.equal(height, 960);
  assert.ok(!texts(calls).some((t) => t.includes(" / ") || t.startsWith("Does not fit")));
});

test("tabs appear when the dashboard has several views", () => {
  const a = { path: "a", title: "Alpha", layout: 0, tiles: [] };
  const b = { path: "b", title: "Beta", layout: 0, tiles: [] };
  const { ctx, calls } = recorder();
  const m = reduce(emptyModel(), { type: "snapshot", profile: tender, views: [a, b], dashboard: "config", states: {}, icons: {} });
  drawView(ctx, tender, m, b, { drawIcon() {} });
  const labels = texts(calls);
  assert.ok(labels.includes("Alpha") && labels.includes("Beta"));
  const one = recorder();
  drawView(one.ctx, tender, reduce(emptyModel(), { type: "snapshot", profile: tender, views: [a], dashboard: "config", states: {}, icons: {} }), a, { drawIcon() {} });
  assert.equal(texts(one.calls).filter((t) => t === "Alpha").length, 1, "no tab strip for one view");
});

test("a tile without a state yet shows an ellipsis and no icon", () => {
  const view = { path: "h", title: "H", layout: 0, tiles: [tileFor(0, "Lamp")] };
  const { calls, icons } = run(tender, view, {});
  assert.deepEqual(icons, []);
  assert.ok(texts(calls).includes("Lamp") && texts(calls).includes("…"));
});

test("long text is shortened to fit the tile", () => {
  const { ctx } = recorder(); // 10 px a character
  assert.equal(fitText(ctx, "short", 100), "short");
  assert.equal(fitText(ctx, "a very long tile name", 100), "a very lo…");
  assert.equal(fitText(ctx, "xyz", 5), "x…"); // never shorter than one character
});

test("an unavailable tile is dimmed", () => {
  assert.equal(tileColors(tender, { on: false, available: false }).fg, "#777");
  assert.equal(tileColors(wall, { on: false, available: false }).fg, "#8a8f98");
  assert.equal(tileColors(tender, null).bg, "#fff");
  assert.equal(tileColors(wall, { on: true, available: true, color: null }).icon.join(), "255,193,7");
});
