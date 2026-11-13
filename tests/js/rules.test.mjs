import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildControls,
  controlItems,
  domainOf,
  entityOptions,
  isSupported,
  tileLabel,
} from "../../custom_components/roundhouse/panel/rules.js";

const rules = {
  domains: ["climate", "light", "lock", "sensor"],
  controls: {
    climate: [
      { type: "hvac_mode", values_attr: "hvac_modes" },
      { type: "target_temperature", values_attr: null },
    ],
    light: [{ type: "light_brightness", values_attr: null }],
  },
};

const states = {
  "light.kitchen": { attributes: { friendly_name: "Kitchen ceiling" } },
  "light.porch": { attributes: {} },
  "lock.door": { attributes: { friendly_name: "Front door" } },
  "weather.home": { attributes: { friendly_name: "Home" } },
  "climate.heat": {
    attributes: { friendly_name: "Heat pump", hvac_modes: ["heat", "cool", "off"] },
  },
  "sensor.temp": { attributes: { friendly_name: "Temperature" } },
};

test("the domain is what comes before the dot", () => {
  assert.equal(domainOf("light.kitchen"), "light");
  assert.equal(domainOf("light."), null);
  assert.equal(domainOf("nodot"), null);
  assert.equal(domainOf(""), null);
});

test("only the domains of the rules are supported", () => {
  assert.equal(isSupported(rules, "light.kitchen"), true);
  assert.equal(isSupported(rules, "weather.home"), false);
  assert.equal(isSupported(rules, "bad"), false);
});

test("the picker lists supported entities by name, with the best matches", () => {
  const all = entityOptions(rules, states, "").map((o) => o.entity_id);
  assert.deepEqual(all, ["lock.door", "climate.heat", "light.kitchen", "light.porch", "sensor.temp"]);
  assert.ok(!all.includes("weather.home"));
  assert.deepEqual(entityOptions(rules, states, "door").map((o) => o.entity_id), ["lock.door"]);
  assert.deepEqual(entityOptions(rules, states, "LIGHT.").map((o) => o.entity_id), ["light.kitchen", "light.porch"]);
  assert.deepEqual(entityOptions(rules, states, "ceiling")[0].name, "Kitchen ceiling");
  assert.deepEqual(entityOptions(rules, states, "zzz"), []);
});

test("an option without a friendly name shows its entity id", () => {
  const [porch] = entityOptions(rules, states, "porch");
  assert.equal(porch.name, "light.porch");
});

test("the picker shows at most the limit", () => {
  const many = Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`light.l${i}`, { attributes: {} }]));
  assert.equal(entityOptions(rules, many, "").length, 50);
  assert.equal(entityOptions(rules, many, "", 5).length, 5);
});

test("a tile is labelled by its override, its friendly name, then its entity", () => {
  assert.equal(tileLabel({ entity_id: "light.kitchen", name: "Lamp" }, states), "Lamp");
  assert.equal(tileLabel({ entity_id: "light.kitchen" }, states), "Kitchen ceiling");
  assert.equal(tileLabel({ entity_id: "light.gone" }, states), "light.gone");
});

test("a climate tile starts with every control and every mode on", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  assert.deepEqual(
    items.map((i) => [i.type, i.on, i.choices.map((c) => [c.value, c.on])]),
    [
      ["hvac_mode", true, [["heat", true], ["cool", true], ["off", true]]],
      ["target_temperature", true, []],
    ],
  );
});

test("saved controls switch the others off and keep their modes", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], [
    { type: "hvac_mode", values: ["heat", "off"] },
  ]);
  assert.deepEqual(items.map((i) => [i.type, i.on]), [["hvac_mode", true], ["target_temperature", false]]);
  assert.deepEqual(items[0].choices.map((c) => [c.value, c.on]), [["heat", true], ["cool", false], ["off", true]]);
});

test("a saved mode the entity no longer lists stays visible, switched on", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], [
    { type: "hvac_mode", values: ["heat", "dry"] },
  ]);
  assert.deepEqual(items[0].choices.map((c) => c.value), ["heat", "cool", "off", "dry"]);
  assert.equal(items[0].choices.find((c) => c.value === "dry").on, true);
});

test("an entity that is not loaded offers its controls without modes", () => {
  const items = controlItems(rules, "climate.heat", undefined, undefined);
  assert.deepEqual(items.map((i) => [i.type, i.choices.length]), [["hvac_mode", 0], ["target_temperature", 0]]);
});

test("every control on with every mode means no restriction", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  assert.equal(buildControls(items), undefined);
});

test("switching a control off lists the others", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  items[1].on = false;
  assert.deepEqual(buildControls(items), [{ type: "hvac_mode" }]);
});

test("switching a mode off lists the modes that stay", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  items[0].choices[1].on = false;
  assert.deepEqual(buildControls(items), [
    { type: "hvac_mode", values: ["heat", "off"] },
    { type: "target_temperature" },
  ]);
});

test("no control on cannot be saved as an empty list, which would mean all", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  items.forEach((i) => (i.on = false));
  assert.equal(buildControls(items), undefined);
});

test("a mode control with no mode on lists no values rather than all of them", () => {
  const items = controlItems(rules, "climate.heat", states["climate.heat"], undefined);
  items[0].choices.forEach((c) => (c.on = false));
  assert.deepEqual(buildControls(items), [{ type: "hvac_mode", values: [] }, { type: "target_temperature" }]);
});

test("a domain without controls has none to choose", () => {
  assert.deepEqual(controlItems(rules, "lock.door", states["lock.door"], undefined), []);
  assert.equal(buildControls([]), undefined);
});
