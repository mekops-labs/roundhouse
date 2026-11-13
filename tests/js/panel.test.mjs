// The panel's subscription lifecycle: device switches and re-attachment.

import assert from "node:assert/strict";
import { test } from "node:test";

import { recorder, vector } from "./helpers.mjs";

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.style = {};
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  addEventListener() {}
  setAttribute() {}
  getContext() {
    return recorder().ctx;
  }
  get classList() {
    return { add() {}, remove() {}, toggle() {} };
  }
}

const defined = {};
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = new FakeNode("root");
    return this.shadowRoot;
  }
  get isConnected() {
    return this._connected ?? false;
  }
};
globalThis.customElements = { define: (name, cls) => (defined[name] = cls), get: () => undefined };
globalThis.document = { createElement: (tag) => new FakeNode(tag) };
globalThis.requestAnimationFrame = () => 1; // never draw: the test reads the model

await import("../../custom_components/roundhouse/panel/panel.js");
const Panel = defined["roundhouse-panel"];

// A connection whose subscriptions resolve when the test says so.
function connection() {
  const subs = [];
  return {
    subs,
    subscribeMessage(callback, msg) {
      const sub = { callback, deviceId: msg.device_id, closed: false };
      sub.promise = new Promise((resolve) => {
        sub.resolve = () => resolve(() => (sub.closed = true));
      });
      subs.push(sub);
      return sub.promise;
    },
  };
}

async function panel(devices) {
  const conn = connection();
  const el = new Panel();
  el._connected = true;
  el.hass = { callWS: async () => devices, connection: conn };
  await new Promise((r) => setImmediate(r));
  return { el, conn };
}

const tick = () => new Promise((r) => setImmediate(r));
const snapshot = (id) => ({ type: "snapshot", device_id: id, views: [] });

test("a slow subscription for a device picked earlier is closed", async () => {
  const { el, conn } = await panel([{ device_id: "a" }, { device_id: "b" }, { device_id: "c" }]);
  el._deviceId = "b";
  el._subscribe();
  el._deviceId = "c";
  el._subscribe();
  const [first, b, c] = conn.subs;
  c.resolve();
  await tick();
  first.resolve();
  b.resolve(); // resolves last, after the newer one
  await tick();
  assert.deepEqual(
    conn.subs.map((s) => [s.deviceId, s.closed]),
    [
      ["a", true],
      ["b", true],
      ["c", false],
    ],
  );
  b.callback(snapshot("b")); // a late message from a dropped subscription
  assert.equal(el._model.snapshot, null);
  c.callback(snapshot("c"));
  assert.equal(el._model.snapshot.device_id, "c");
});

test("a re-attached panel subscribes again", async () => {
  const { el, conn } = await panel([{ device_id: "a" }]);
  conn.subs[0].resolve();
  await tick();
  el._connected = false;
  el.disconnectedCallback();
  assert.equal(conn.subs[0].closed, true);
  el._connected = true;
  el.connectedCallback();
  assert.equal(conn.subs.length, 2);
  conn.subs[1].resolve();
  await tick();
  assert.equal(conn.subs[1].closed, false);
});

test("a subscription still pending when the panel detaches is closed", async () => {
  const { el, conn } = await panel([{ device_id: "a" }]);
  el._connected = false;
  el.disconnectedCallback();
  conn.subs[0].resolve();
  await tick();
  assert.equal(conn.subs[0].closed, true);
});

test("a state frame keeps the device picker", async () => {
  const { el, conn } = await panel([{ device_id: "a" }, { device_id: "b" }]);
  conn.subs[0].resolve();
  await tick();
  const [, header] = el.shadowRoot.children;
  const picker = header.children[1];
  assert.equal(picker.tagName, "select");
  el._render(); // what each animation frame does after a state message
  el._render();
  assert.equal(el.shadowRoot.children[1], header);
  assert.equal(header.children[1], picker);
});

// --- editing -----------------------------------------------------------------

const tender = vector("tender");
const rules = { domains: ["light", "climate"], controls: {} };
const home = { path: "home", title: "Home", layout: 0, tiles: [{ entity_id: "light.a" }], overflow: null };
const saved = (revision = 3, views = [home]) => ({
  type: "snapshot",
  device_id: "a",
  profile: tender,
  rules,
  revision,
  snapshot: null,
  views,
  states: {},
  icons: {},
});

function storage() {
  const items = new Map();
  globalThis.sessionStorage = {
    getItem: (k) => items.get(k) ?? null,
    setItem: (k, v) => items.set(k, v),
    removeItem: (k) => items.delete(k),
  };
  return items;
}

// A panel showing device "a" with a saved snapshot, and the calls it makes.
async function editor(results = {}, items = storage(), revision = 3) {
  const calls = [];
  const conn = connection();
  const el = new Panel();
  el._connected = true;
  el.hass = {
    states: {},
    connection: conn,
    callWS: async (msg) => {
      calls.push(msg);
      if (msg.type === "roundhouse/devices") return [{ device_id: "a", title: "Tender" }];
      return results[msg.type] ?? {};
    },
  };
  await tick();
  conn.subs[0].resolve();
  await tick();
  conn.subs[0].callback(saved(revision));
  return { el, calls, conn, items };
}

test("Done saves the draft with the revision it started from", async () => {
  const { el, calls } = await editor({ "roundhouse/editor/save": { ok: true, revision: 4 } });
  el._edit();
  el._changed(
    (await import("../../custom_components/roundhouse/panel/draft.js")).setTitle(el._draft, "home", "Lounge"),
  );
  await el._done();
  const save = calls.find((c) => c.type === "roundhouse/editor/save");
  assert.equal(save.device_id, "a");
  assert.equal(save.revision, 3);
  assert.equal(save.views[0].title, "Lounge");
  assert.equal(save.snapshot, null);
  assert.equal(el._draft, null, "edit mode ends after a save");
});

test("Done with a broken draft shows the errors and saves nothing", async () => {
  const { el, calls } = await editor();
  el._edit();
  const { setTitle } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._changed(setTitle(el._draft, "home", ""));
  await el._done();
  assert.equal(calls.some((c) => c.type === "roundhouse/editor/save"), false);
  assert.ok(el._draft, "still editing");
  assert.equal(el._banner.list.length, 1);
  assert.match(el._banner.list[0], /title has 1 to 32/);
});

test("a conflict keeps the draft and offers to discard it", async () => {
  const { el } = await editor({ "roundhouse/editor/save": { ok: false, error: "conflict", revision: 4 } });
  el._edit();
  await el._done();
  assert.ok(el._draft);
  assert.equal(el._banner.action[0], "Discard my edits");
  el._banner.action[1]();
  assert.equal(el._draft, null);
});

test("errors from the server are shown by their view and tile", async () => {
  const errors = [{ view: 0, tile: 0, code: "unsupported_domain", message: "light.a cannot be shown on a device" }];
  const { el } = await editor({ "roundhouse/editor/save": { ok: false, error: "invalid", errors } });
  el._edit();
  await el._done();
  assert.deepEqual(el._errors, errors);
  assert.match(el._banner.list[0], /View "Home", tile 1: light.a cannot be shown/);
});

test("views saved elsewhere while editing raise a banner, but not for our own save", async () => {
  const { el, conn } = await editor();
  el._edit();
  conn.subs[0].callback(saved(4));
  assert.match(el._banner.text, /saved from another page/);

  const own = await editor();
  own.el._edit();
  own.el._saving = true;
  own.conn.subs[0].callback(saved(4));
  assert.equal(own.el._banner, null);
});

test("an unsaved draft survives leaving the page when the views did not change", async () => {
  const { el, items } = await editor();
  el._edit();
  const { setTitle } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._changed(setTitle(el._draft, "home", "Lounge"));
  el._connected = false;
  el.disconnectedCallback();
  assert.ok(items.get("roundhouse.draft.a"));

  // Home Assistant builds a new element when the user comes back.
  const back = await editor({}, items);
  assert.equal(back.el._draft.views[0].title, "Lounge");
  assert.match(back.el._banner.text, /restored/);
  assert.equal(items.has("roundhouse.draft.a"), false, "kept once, then taken");
});

test("a kept draft is dropped when the views changed meanwhile", async () => {
  const { el, items } = await editor();
  el._edit();
  const { setTitle } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._changed(setTitle(el._draft, "home", "Lounge"));
  el._connected = false;
  el.disconnectedCallback();

  const back = await editor({}, items, 9); // the views were saved elsewhere in between
  assert.equal(back.el._draft, null);
  assert.equal(items.has("roundhouse.draft.a"), false);
});

test("a draft that was never changed is not kept", async () => {
  const { el, items } = await editor();
  el._edit();
  el._connected = false;
  el.disconnectedCallback();
  assert.equal(items.has("roundhouse.draft.a"), false);
});

test("the header shows the version, linked only for a release", async () => {
  const { el } = await editor();
  el.panel = { config: { version: "0.2.0" } };
  const link = el._headerEl.children.find((c) => c.className === "version");
  assert.equal(link.tagName, "a");
  assert.match(link.href, /blob\/v0\.2\.0\/CHANGELOG\.md$/);
  el.panel = { config: { version: "dev" } };
  const plain = el._headerEl.children.find((c) => c.className === "version");
  assert.equal(plain.tagName, "span");
});

// A callWS answer the test releases when it wants.
function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

test("a second Done while saving sends nothing", async () => {
  const pending = deferred();
  const { el, calls } = await editor({ "roundhouse/editor/save": pending.promise });
  el._edit();
  const first = el._done();
  await el._done();
  assert.equal(calls.filter((c) => c.type === "roundhouse/editor/save").length, 1);
  pending.resolve({ ok: true, revision: 4 });
  await first;
  assert.equal(el._draft, null);
  assert.equal(el._banner, null);
});

test("edits made while a save is in flight are kept on the new revision", async () => {
  const pending = deferred();
  const { el, conn } = await editor({ "roundhouse/editor/save": pending.promise });
  const { setTitle } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._edit();
  el._changed(setTitle(el._draft, "home", "Lounge"));
  const saving = el._done();
  el._changed(setTitle(el._draft, "home", "Kitchen"));
  pending.resolve({ ok: true, revision: 4 });
  await saving;
  assert.equal(el._draft.views[0].title, "Kitchen");
  assert.equal(el._draft.revision, 4);
  assert.equal(el._dirty(), true);
  conn.subs[0].callback(saved(4)); // the snapshot of our own save, arriving late
  assert.equal(el._banner, null);
});

test("switching devices drops the draft kept for the old one", async () => {
  const { el, items } = await editor();
  const { setTitle } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._edit();
  el._changed(setTitle(el._draft, "home", "Lounge"));
  el._keepDraft(); // as leaving the page and coming back does
  globalThis.confirm = () => true;
  assert.equal(el._pickDevice("b"), true);
  delete globalThis.confirm;
  assert.equal(items.has("roundhouse.draft.a"), false);
  assert.equal(el._draft, null);
});

test("states rendered for the draft never reach view mode", async () => {
  const lamp = { states: { "light.a": { icon: "mdi:lamp", text: "On" } }, icons: {} };
  const { el, conn } = await editor({ "roundhouse/editor/render": lamp });
  conn.subs[0].callback({ ...saved(3), states: { "light.a": { icon: "mdi:lightbulb", text: "On" } } });
  el._edit();
  const { replaceTile } = await import("../../custom_components/roundhouse/panel/draft.js");
  el._changed(replaceTile(el._draft, "home", 0, { entity_id: "light.a", icon: "mdi:lamp" }));
  await el._renderDraft();
  assert.equal(el._drawModel().states["light.a"].icon, "mdi:lamp");

  // Undoing the icon draws the saved state again.
  el._changed(replaceTile(el._draft, "home", 0, { entity_id: "light.a" }));
  await el._renderDraft();
  assert.equal(el._drawModel().states["light.a"].icon, "mdi:lightbulb");

  // A dialog's render is dropped with the edit.
  await el._renderEntities({ "light.a": "mdi:lamp" });
  el._leaveEdit();
  assert.equal(el._drawModel().states["light.a"].icon, "mdi:lightbulb");
});

test("a large draft is rendered in batches the integration accepts", async () => {
  const { el, calls } = await editor({ "roundhouse/editor/render": { states: {}, icons: {} } });
  el._edit();
  el._hass.states = {};
  const many = Array.from({ length: 70 }, (_, i) => ({ entity_id: `light.x${i}` }));
  el._draft = { ...el._draft, views: [{ ...el._draft.views[0], tiles: many }] };
  await el._renderDraft();
  const sizes = calls.filter((c) => c.type === "roundhouse/editor/render").map((c) => Object.keys(c.entities).length);
  assert.deepEqual(sizes, [64, 6]);
});
