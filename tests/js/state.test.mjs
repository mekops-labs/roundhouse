import assert from "node:assert/strict";
import { test } from "node:test";

import { emptyModel, reduce, tileState } from "../../custom_components/roundhouse/panel/state.js";

const snapshot = {
  type: "snapshot",
  device_id: "tender01",
  views: [{ path: "home" }],
  states: { "light.a": { text: "Off" } },
  icons: { "mdi:lightbulb": "AAAA" },
};

test("a snapshot replaces the model", () => {
  const model = reduce(emptyModel(), snapshot);
  assert.equal(model.snapshot.device_id, "tender01");
  assert.equal(model.snapshot.states, undefined);
  assert.deepEqual(model.states, { "light.a": { text: "Off" } });
  assert.deepEqual(model.icons, { "mdi:lightbulb": "AAAA" });
  const next = reduce(model, { ...snapshot, states: {}, icons: {} });
  assert.deepEqual(next.states, {});
});

test("a state message updates one entity and adds its icons", () => {
  const model = reduce(emptyModel(), snapshot);
  const next = reduce(model, {
    type: "state",
    entity_id: "light.a",
    state: { text: "On" },
    icons: { "mdi:lightbulb-on": "BBBB" },
  });
  assert.equal(tileState(next, "light.a").text, "On");
  assert.deepEqual(Object.keys(next.icons).sort(), ["mdi:lightbulb", "mdi:lightbulb-on"]);
  assert.equal(next.snapshot, model.snapshot);
  assert.equal(tileState(model, "light.a").text, "Off"); // the old model is untouched
});

test("an unknown message and a missing state change nothing", () => {
  const model = reduce(emptyModel(), snapshot);
  assert.equal(reduce(model, { type: "other" }), model);
  assert.equal(tileState(model, "light.nope"), null);
});
