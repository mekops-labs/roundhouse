// The editor's draft: the views being edited, as plain data. Every function
// returns a new draft and leaves its argument alone, so a draft is easy to test
// and to cancel. The checks mirror the ones the integration makes on a save.

import { densest, layoutIndex } from "./geometry.js";
import { domainOf, isSupported } from "./rules.js";

const MAX_TITLE = 32;
const MAX_NAME = 32;

const clone = (value) => JSON.parse(JSON.stringify(value));

function newPath(taken) {
  for (;;) {
    const bytes = new Uint8Array(4);
    globalThis.crypto.getRandomValues(bytes);
    const path = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    if (!taken.includes(path)) return path;
  }
}

function plain(view) {
  return { path: view.path, title: view.title, layout: view.layout, tiles: clone(view.tiles) };
}

function make(revision, snapshot, views) {
  return { revision, snapshot, views, base: JSON.stringify({ snapshot, views }) };
}

// Start a draft from a snapshot message of the integration. A device that
// does not sleep has no snapshot view, so one kept from before is dropped.
export function fromSnapshot(snapshot) {
  const sleeps = (snapshot.profile?.features ?? []).includes("sleep");
  return make(snapshot.revision, sleeps ? (snapshot.snapshot ?? null) : null, snapshot.views.map(plain));
}

// After `sent` was saved as `revision`, keep the edits made since as a draft of
// that revision.
export function rebase(draft, revision, sent) {
  return { ...draft, revision, base: JSON.stringify({ snapshot: sent.snapshot, views: sent.views }) };
}

export function isDirty(draft) {
  return JSON.stringify({ snapshot: draft.snapshot, views: draft.views }) !== draft.base;
}

function withViews(draft, views, snapshot = draft.snapshot) {
  return { ...draft, snapshot, views };
}

function edit(draft, path, change) {
  return withViews(
    draft,
    draft.views.map((v) => (v.path === path ? change(v) : v)),
  );
}

export function addView(draft, profile) {
  const taken = draft.views.map((v) => v.path);
  const titles = draft.views.map((v) => v.title);
  let n = draft.views.length + 1;
  while (titles.includes(`View ${n}`)) n += 1;
  const view = { path: newPath(taken), title: `View ${n}`, layout: densest(profile), tiles: [] };
  return withViews(draft, [...draft.views, view]);
}

export function setTitle(draft, path, title) {
  return edit(draft, path, (v) => ({ ...v, title }));
}

export function moveView(draft, from, to) {
  const last = draft.views.length - 1;
  if (from === to || from < 0 || to < 0 || from > last || to > last) return draft;
  const views = [...draft.views];
  views.splice(to, 0, ...views.splice(from, 1));
  return withViews(draft, views);
}

export function deleteView(draft, path) {
  const snapshot = draft.snapshot === path ? null : draft.snapshot;
  return withViews(
    draft,
    draft.views.filter((v) => v.path !== path),
    snapshot,
  );
}

export function setSnapshot(draft, path) {
  return withViews(draft, draft.views, path);
}

// Put a tile into the first free slot, or refuse when the view is full.
export function addTile(draft, path, tile, profile) {
  const view = draft.views.find((v) => v.path === path);
  if (view.tiles.length >= profile.layouts[layoutIndex(profile, view)].slots.length) {
    return { draft, error: "full" };
  }
  return { draft: edit(draft, path, (v) => ({ ...v, tiles: [...v.tiles, clone(tile)] })) };
}

export function replaceTile(draft, path, index, tile) {
  return edit(draft, path, (v) => ({ ...v, tiles: v.tiles.map((t, i) => (i === index ? clone(tile) : t)) }));
}

export function removeTile(draft, path, index) {
  const view = draft.views.find((v) => v.path === path);
  if (index < 0 || index >= view.tiles.length) return draft;
  return edit(draft, path, (v) => ({ ...v, tiles: v.tiles.filter((_, i) => i !== index) }));
}

// Tiles fill the slots in order with no gap, so a move is a reinsertion.
export function moveTile(draft, path, from, to) {
  const view = draft.views.find((v) => v.path === path);
  const last = view.tiles.length - 1;
  if (from === to || from < 0 || to < 0 || from > last || to > last) return draft;
  return edit(draft, path, (v) => {
    const tiles = [...v.tiles];
    tiles.splice(to, 0, ...tiles.splice(from, 1));
    return { ...v, tiles };
  });
}

export function setLayout(draft, path, index, profile) {
  const view = draft.views.find((v) => v.path === path);
  const layout = profile.layouts[index];
  if (!Number.isInteger(index) || layout === undefined) return { draft, error: "unknown_layout" };
  if (view.tiles.length > layout.slots.length) return { draft, error: "too_many_tiles" };
  return { draft: edit(draft, path, (v) => ({ ...v, layout: index })) };
}

// What the integration's save command takes.
export function toSave(draft) {
  return { revision: draft.revision, views: draft.views.map(plain), snapshot: draft.snapshot };
}

function controlsError(rules, domain, controls) {
  const allowed = new Map((rules.controls[domain] ?? []).map((c) => [c.type, c]));
  const seen = new Set();
  for (const control of controls) {
    if (!allowed.has(control.type)) return `${control.type} is not a control of ${domain}`;
    if (seen.has(control.type)) return `${control.type} is listed twice`;
    seen.add(control.type);
    if (control.values !== undefined && allowed.get(control.type).values_attr === null) {
      return `${control.type} takes no values`;
    }
  }
  return null;
}

function tileErrors(view, i, tile, at, rules) {
  const out = [];
  const add = (code, message) => out.push({ view: i, tile: at, code, message });
  if (!isSupported(rules, tile.entity_id)) add("unsupported_domain", `${tile.entity_id} cannot be shown on a device`);
  if (tile.name !== undefined && tile.name.length > MAX_NAME) add("bad_name", `A name has at most ${MAX_NAME} characters`);
  if (tile.controls !== undefined) {
    const reason = controlsError(rules, domainOf(tile.entity_id), tile.controls);
    if (reason) add("bad_controls", reason);
  }
  return out;
}

// Every rule the draft breaks, with the view and tile index it belongs to.
export function errorsOf(draft, profile, rules) {
  const out = [];
  const paths = new Set();
  draft.views.forEach((view, i) => {
    if (paths.has(view.path)) out.push({ view: i, tile: null, code: "duplicate_path", message: "A path is used twice" });
    paths.add(view.path);
    if (!view.title || view.title.length > MAX_TITLE) {
      out.push({ view: i, tile: null, code: "bad_title", message: `A title has 1 to ${MAX_TITLE} characters` });
    }
    const layout = profile.layouts[view.layout];
    if (!Number.isInteger(view.layout) || layout === undefined) {
      out.push({ view: i, tile: null, code: "unknown_layout", message: "The device has no such layout" });
    } else if (view.tiles.length > layout.slots.length) {
      const excess = view.tiles.length - layout.slots.length;
      out.push({ view: i, tile: null, code: "too_many_tiles", message: `The layout holds ${layout.slots.length} tiles; remove ${excess}` });
    }
    view.tiles.forEach((tile, at) => out.push(...tileErrors(view, i, tile, at, rules)));
  });
  const sleeps = (profile.features ?? []).includes("sleep");
  if (draft.snapshot !== null && (!sleeps || !paths.has(draft.snapshot))) {
    out.push({ view: null, tile: null, code: "bad_snapshot", message: "The snapshot view must be a view of a device that sleeps" });
  }
  return out;
}
