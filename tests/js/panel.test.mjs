// The panel's subscription lifecycle: device switches and re-attachment.

import assert from "node:assert/strict";
import { test } from "node:test";

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
globalThis.customElements = { define: (name, cls) => (defined[name] = cls) };
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
