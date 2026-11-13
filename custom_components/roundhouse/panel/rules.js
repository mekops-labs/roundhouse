// What the editor offers: supported entities and the controls of each domain.
// `rules` is what the integration sends with a snapshot, so the page and the
// server agree on what a device can show.

const ENTITY_ID = /^([a-z0-9_]+)\.[a-z0-9_]+$/;

export function domainOf(entityId) {
  const match = ENTITY_ID.exec(entityId ?? "");
  return match ? match[1] : null;
}

export function isSupported(rules, entityId) {
  const domain = domainOf(entityId);
  return domain !== null && rules.domains.includes(domain);
}

function friendlyName(states, entityId) {
  return states[entityId]?.attributes?.friendly_name ?? null;
}

// The name a tile shows: its override, the entity's friendly name, or its id.
export function tileLabel(tile, states) {
  return tile.name || friendlyName(states, tile.entity_id) || tile.entity_id;
}

// The entities of supported domains that match `query`, by name.
export function entityOptions(rules, states, query, limit = 50) {
  const needle = query.trim().toLowerCase();
  return Object.keys(states)
    .filter((id) => isSupported(rules, id))
    .map((id) => ({ entity_id: id, name: friendlyName(states, id) ?? id }))
    .filter((o) => !needle || o.name.toLowerCase().includes(needle) || o.entity_id.includes(needle))
    .sort((a, b) => a.name.localeCompare(b.name))
    .slice(0, limit);
}

// The controls of an entity's detail page as a checklist. `saved` is the tile's
// `controls`: none means every control and every mode. A saved mode the entity
// no longer lists stays in the list, so saving does not drop it silently.
export function controlItems(rules, entityId, stateObj, saved) {
  const controls = rules.controls[domainOf(entityId)] ?? [];
  return controls.map((control) => {
    const keep = saved?.find((c) => c.type === control.type);
    const listed = control.values_attr ? (stateObj?.attributes?.[control.values_attr] ?? []) : [];
    const values = [...listed, ...(keep?.values ?? []).filter((v) => !listed.includes(v))];
    return {
      type: control.type,
      on: saved === undefined || keep !== undefined,
      choices: values.map((value) => ({ value, on: keep?.values === undefined || keep.values.includes(value) })),
    };
  });
}

// The `controls` to store for a checklist, or undefined for no restriction.
export function buildControls(items) {
  const on = items.filter((i) => i.on);
  if (!on.length) return undefined;
  const restricted = on.length < items.length || on.some((i) => i.choices.some((c) => !c.on));
  if (!restricted) return undefined;
  return on.map((item) => {
    const control = { type: item.type };
    if (item.choices.some((c) => !c.on)) control.values = item.choices.filter((c) => c.on).map((c) => c.value);
    return control;
  });
}
