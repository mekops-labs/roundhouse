import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addTile,
  addView,
  deleteView,
  errorsOf,
  fromSnapshot,
  isDirty,
  moveTile,
  moveView,
  removeTile,
  replaceTile,
  setLayout,
  setSnapshot,
  setTitle,
  toSave,
} from "../../custom_components/roundhouse/panel/draft.js";
import { vector } from "./helpers.mjs";

const tender = vector("tender"); // layouts of 8 and 15 slots, sleeps
const wall = vector("wall-panel"); // layouts of 6 and 8 slots, no sleep
const rules = {
  domains: ["climate", "light"],
  controls: { climate: [{ type: "hvac_mode", values_attr: "hvac_modes" }] },
};

const tile = (i) => ({ entity_id: `light.l${i}` });
const tiles = (n) => Array.from({ length: n }, (_, i) => tile(i));
const snapshot = (views, extra = {}) => ({
  revision: 4,
  snapshot: null,
  views: views.map((v) => ({ overflow: null, ...v })),
  ...extra,
});
const home = (n = 2) => ({ path: "home", title: "Home", layout: 0, tiles: tiles(n) });

test("a draft copies the saved views and drops what the page added", () => {
  const draft = fromSnapshot(snapshot([home()], { snapshot: "home" }));
  assert.equal(draft.revision, 4);
  assert.equal(draft.snapshot, "home");
  assert.deepEqual(draft.views, [home()]);
  assert.equal(draft.views[0].overflow, undefined);
});

test("a fresh draft is not dirty, and any edit makes it so", () => {
  const draft = fromSnapshot(snapshot([home()]));
  assert.equal(isDirty(draft), false);
  assert.equal(isDirty(setTitle(draft, "home", "Lounge")), true);
  assert.equal(isDirty(setTitle(setTitle(draft, "home", "Lounge"), "home", "Home")), false);
});

test("editing never changes the draft it started from", () => {
  const draft = fromSnapshot(snapshot([home()]));
  const next = removeTile(draft, "home", 0);
  assert.equal(draft.views[0].tiles.length, 2);
  assert.equal(next.views[0].tiles.length, 1);
});

test("a new view has the densest layout, no tiles, and a path of its own", () => {
  const draft = fromSnapshot(snapshot([home()]));
  const next = addView(draft, tender);
  const [, added] = next.views;
  assert.equal(added.layout, 1);
  assert.deepEqual(added.tiles, []);
  assert.match(added.path, /^[0-9a-f]{8}$/);
  assert.notEqual(added.path, "home");
  assert.equal(addView(next, tender).views[2].path === added.path, false);
  assert.equal(addView(draft, wall).views[1].layout, 1);
});

test("a new view gets a title that no other view has", () => {
  let draft = fromSnapshot(snapshot([]));
  draft = addView(addView(draft, tender), tender);
  const titles = draft.views.map((v) => v.title);
  assert.equal(new Set(titles).size, 2);
});

test("a view is renamed by path", () => {
  const draft = setTitle(fromSnapshot(snapshot([home()])), "home", "Lounge");
  assert.equal(draft.views[0].title, "Lounge");
  assert.equal(draft.views[0].path, "home");
});

test("views are reordered, and the ends are respected", () => {
  const draft = fromSnapshot(
    snapshot([
      { ...home(), path: "a", title: "A" },
      { ...home(), path: "b", title: "B" },
      { ...home(), path: "c", title: "C" },
    ]),
  );
  assert.deepEqual(moveView(draft, 0, 2).views.map((v) => v.path), ["b", "c", "a"]);
  assert.deepEqual(moveView(draft, 2, 0).views.map((v) => v.path), ["c", "a", "b"]);
  assert.equal(moveView(draft, 1, 1), draft);
  assert.equal(moveView(draft, 0, 3), draft);
  assert.equal(moveView(draft, -1, 0), draft);
});

test("deleting a view clears the snapshot view when it was that one", () => {
  const draft = fromSnapshot(
    snapshot(
      [
        { ...home(), path: "a" },
        { ...home(), path: "b" },
      ],
      { snapshot: "a" },
    ),
  );
  assert.equal(deleteView(draft, "a").snapshot, null);
  assert.equal(deleteView(draft, "b").snapshot, "a");
  assert.deepEqual(deleteView(draft, "b").views.map((v) => v.path), ["a"]);
});

test("the snapshot view is set and cleared", () => {
  const draft = fromSnapshot(snapshot([home()]));
  assert.equal(setSnapshot(draft, "home").snapshot, "home");
  assert.equal(setSnapshot(setSnapshot(draft, "home"), null).snapshot, null);
});

test("a tile is added into the first free slot, and a full view refuses", () => {
  const draft = fromSnapshot(snapshot([{ ...home(7), layout: 0 }]));
  const full = addTile(draft, "home", tile(9), tender);
  assert.equal(full.error, undefined);
  assert.equal(full.draft.views[0].tiles.length, 8);
  assert.equal(full.draft.views[0].tiles[7].entity_id, "light.l9");
  const over = addTile(full.draft, "home", tile(10), tender);
  assert.equal(over.error, "full");
  assert.equal(over.draft, full.draft);
});

test("a tile is replaced, removed, and moved by index", () => {
  const draft = fromSnapshot(snapshot([home(3)]));
  assert.equal(replaceTile(draft, "home", 1, { entity_id: "light.x", name: "X" }).views[0].tiles[1].name, "X");
  assert.deepEqual(removeTile(draft, "home", 0).views[0].tiles.map((t) => t.entity_id), ["light.l1", "light.l2"]);
  assert.deepEqual(moveTile(draft, "home", 0, 2).views[0].tiles.map((t) => t.entity_id), ["light.l1", "light.l2", "light.l0"]);
  assert.deepEqual(moveTile(draft, "home", 2, 0).views[0].tiles.map((t) => t.entity_id), ["light.l2", "light.l0", "light.l1"]);
  assert.equal(moveTile(draft, "home", 1, 1), draft);
  assert.equal(moveTile(draft, "home", 0, 3), draft); // past the last tile: no gaps
  assert.equal(removeTile(draft, "home", 9), draft);
});

test("the layout can change unless the tiles no longer fit", () => {
  const draft = fromSnapshot(snapshot([{ ...home(9), layout: 1 }]));
  const refused = setLayout(draft, "home", 0, tender);
  assert.equal(refused.error, "too_many_tiles");
  assert.equal(refused.draft, draft);
  const fewer = fromSnapshot(snapshot([{ ...home(8), layout: 1 }]));
  const ok = setLayout(fewer, "home", 0, tender);
  assert.equal(ok.error, undefined);
  assert.equal(ok.draft.views[0].layout, 0);
  assert.equal(setLayout(fewer, "home", 5, tender).error, "unknown_layout");
});

test("saving sends the views as they are, with the revision and the snapshot view", () => {
  const draft = setSnapshot(fromSnapshot(snapshot([home()])), "home");
  assert.deepEqual(toSave(draft), {
    revision: 4,
    views: [home()],
    snapshot: "home",
  });
});

test("a draft with no errors is valid for the device", () => {
  const draft = fromSnapshot(snapshot([home(2)], { snapshot: null }));
  assert.deepEqual(errorsOf(draft, tender, rules), []);
});

test("the draft is checked against the rules the server applies", () => {
  const draft = fromSnapshot(
    snapshot([
      { path: "a", title: "", layout: 0, tiles: tiles(9) },
      {
        path: "b",
        title: "x".repeat(33),
        layout: 7,
        tiles: [
          { entity_id: "weather.x" },
          { entity_id: "light.a", name: "n".repeat(33) },
          { entity_id: "light.b", controls: [{ type: "hvac_mode" }] },
          { entity_id: "climate.c", controls: [{ type: "hvac_mode" }, { type: "hvac_mode" }] },
        ],
      },
      { path: "b", title: "dup", layout: 0, tiles: [] },
    ]),
  );
  const found = errorsOf(draft, tender, rules).map((e) => [e.view, e.tile, e.code]);
  assert.deepEqual(found.sort((x, y) => String(x).localeCompare(String(y))), [
    [0, null, "bad_title"],
    [0, null, "too_many_tiles"],
    [1, 0, "unsupported_domain"],
    [1, 1, "bad_name"],
    [1, 2, "bad_controls"],
    [1, 3, "bad_controls"],
    [1, null, "bad_title"],
    [1, null, "unknown_layout"],
    [2, null, "duplicate_path"],
  ].sort((x, y) => String(x).localeCompare(String(y))));
});

test("the snapshot view must exist, on a device that sleeps", () => {
  const draft = fromSnapshot(snapshot([home()], { snapshot: "gone" }));
  assert.deepEqual(errorsOf(draft, tender, rules).map((e) => e.code), ["bad_snapshot"]);
  const ok = setSnapshot(draft, "home");
  assert.deepEqual(errorsOf(ok, tender, rules), []);
  assert.deepEqual(errorsOf(ok, wall, rules).map((e) => e.code), ["bad_snapshot"]);
});
