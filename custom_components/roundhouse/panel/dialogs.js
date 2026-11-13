// The tile dialog and the view dialog: native `<dialog>` elements styled
// like Home Assistant's own dialogs.

import { drawTile } from "./draw.js";
import { h } from "./dom.js";
import { buildControls, controlItems, entityOptions, tileLabel, toggleChoice, toggleItem } from "./rules.js";

export const DIALOG_STYLE = `
  dialog { border: none; border-radius: var(--ha-card-border-radius, 12px); padding: 0; width: min(520px, calc(100vw - 32px)); max-height: calc(100vh - 32px); background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 8px 32px rgba(0,0,0,.35); }
  dialog::backdrop { background: rgba(0,0,0,.5); }
  dialog form { display: flex; flex-direction: column; max-height: calc(100vh - 32px); }
  dialog h2 { margin: 0; padding: 16px 24px 8px; font-size: 20px; font-weight: 500; }
  .dlg-body { padding: 8px 24px; overflow: auto; display: flex; flex-direction: column; gap: 12px; }
  .dlg-actions { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 24px 16px; }
  .field { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .field > span, legend { color: var(--secondary-text-color); font-size: 12px; }
  input[type="text"], input[type="search"], select { font: inherit; padding: 8px; color: var(--primary-text-color); background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #ccc); border-radius: 4px; }
  .results { list-style: none; margin: 0; padding: 0; max-height: 200px; overflow: auto; border: 1px solid var(--divider-color, #ccc); border-radius: 4px; }
  .results button { display: flex; flex-direction: column; align-items: flex-start; width: 100%; padding: 6px 8px; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .results button:hover, .results button:focus-visible { background: var(--secondary-background-color, #eee); }
  .results small, .chip small { color: var(--secondary-text-color); }
  .chip { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--divider-color, #ccc); border-radius: 4px; }
  fieldset { border: 1px solid var(--divider-color, #ccc); border-radius: 4px; margin: 0; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
  fieldset label { display: flex; gap: 8px; align-items: center; font-size: 14px; }
  fieldset .modes { margin-left: 24px; display: flex; flex-wrap: wrap; gap: 4px 16px; }
  .preview { display: flex; justify-content: center; }
  .preview canvas { border: 1px solid var(--divider-color, #ccc); }
  .hint { color: var(--secondary-text-color); font-size: 12px; margin: 0; }
  .hint.bad { color: var(--error-color, #d32f2f); }
  .text-button { font: inherit; padding: 8px 16px; border: 0; border-radius: 4px; background: transparent; color: var(--primary-color); cursor: pointer; text-transform: uppercase; font-weight: 500; letter-spacing: .04em; }
  .text-button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .text-button.danger { color: var(--error-color, #d32f2f); margin-right: auto; }
  .text-button:disabled { opacity: .45; cursor: default; }
`;

const CONTROL_LABELS = {
  hvac_mode: "HVAC modes",
  preset_mode: "Preset modes",
  fan_mode: "Fan modes",
  swing_mode: "Swing modes",
  target_temperature: "Target temperature",
  target_humidity: "Target humidity",
  fan_speed: "Fan speed",
  fan_preset_mode: "Preset modes",
  operation_mode: "Operation modes",
  humidifier_mode: "Modes",
  humidifier_toggle: "On and off",
  number: "Value",
  select: "Options",
  cover_open_close: "Open and close",
  cover_position: "Position",
  valve_open_close: "Open and close",
  valve_position: "Position",
  light_brightness: "Brightness",
  light_color_temp: "Color temperature",
};

function open(ctx, title, body, actions) {
  const dlg = h("dialog", {}, h("form", { method: "dialog" }, h("h2", { textContent: title }), h("div", { className: "dlg-body" }, ...body), h("div", { className: "dlg-actions" }, ...actions)));
  dlg.addEventListener("close", () => {
    dlg.remove();
    ctx.closed?.();
  });
  ctx.root.append(dlg);
  dlg.showModal();
  return dlg;
}

const button = (text, extra, onClick, props = {}) =>
  h("button", { className: `text-button ${extra}`.trim(), type: "button", textContent: text, on: { click: onClick }, ...props });

// Edit one tile. `ctx` supplies hass, profile, rules, the view, the model,
// `render` for entities the model lacks, and `drawIcon`.
export function tileDialog(ctx, tile, onSave) {
  let entity = tile?.entity_id ?? null;
  let items = entity ? controlItems(ctx.rules, entity, ctx.hass.states[entity], tile?.controls) : [];
  const nameInput = h("input", { type: "text", maxLength: 32, value: tile?.name ?? "" });
  const iconInput = h("input", { type: "text", value: tile?.icon ?? "", placeholder: "mdi:lightbulb" });
  const iconHint = h("p", { className: "hint" });
  const search = h("input", { type: "search", placeholder: "Search entities", ariaLabel: "Search entities" });
  const results = h("ul", { className: "results" });
  const picked = h("div", {});
  const controls = h("div", {});
  const canvas = h("canvas", {});
  const save = button("Save", "primary", () => {
    const controlsOut = buildControls(items);
    const out = { entity_id: entity };
    if (nameInput.value.trim()) out.name = nameInput.value.trim();
    if (iconInput.value.trim()) out.icon = iconInput.value.trim();
    if (controlsOut) out.controls = controlsOut;
    dlg.close();
    onSave(out);
  });

  const preview = () => {
    const rect = ctx.slotRect;
    const scale = Math.min(1, 240 / rect.w);
    canvas.width = rect.w;
    canvas.height = rect.h;
    canvas.style.width = `${Math.round(rect.w * scale)}px`;
    canvas.style.height = `${Math.round(rect.h * scale)}px`;
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, rect.w, rect.h);
    if (!entity) return;
    const shown = { entity_id: entity, name: nameInput.value, icon: iconInput.value };
    shown.label = tileLabel(shown, ctx.hass.states);
    drawTile(g, ctx.profile, ctx.model(), shown, { x: 0, y: 0, w: rect.w, h: rect.h }, { drawIcon: ctx.drawIcon });
  };

  const refresh = async () => {
    if (!entity) return;
    await ctx.render({ [entity]: iconInput.value.trim() || null });
    preview();
  };

  const showIconHint = () => {
    const value = iconInput.value.trim();
    iconHint.className = value && !value.startsWith("mdi:") ? "hint bad" : "hint";
    const fallback = entity ? ctx.model().states[entity]?.icon : null;
    iconHint.textContent = value && !value.startsWith("mdi:") ? "Use an mdi: icon name." : fallback ? `Default: ${fallback}` : "";
  };

  const showControls = () => {
    controls.replaceChildren();
    if (!items.length) return;
    const field = h("fieldset", {}, h("legend", { textContent: "Controls on the detail page" }));
    for (const item of items) {
      const box = h("input", { type: "checkbox", checked: item.on, on: { change: () => {
        if (!toggleItem(items, item.type)) box.checked = true;
        showControls();
      } } });
      field.append(h("label", {}, box, CONTROL_LABELS[item.type] ?? item.type));
      if (item.on && item.choices.length) {
        const modes = h("div", { className: "modes" });
        for (const choice of item.choices) {
          const cb = h("input", { type: "checkbox", checked: choice.on, on: { change: () => {
            if (!toggleChoice(item, choice.value)) cb.checked = true;
          } } });
          modes.append(h("label", {}, cb, choice.value));
        }
        field.append(modes);
      }
    }
    controls.append(field, h("p", { className: "hint", textContent: "Unticked controls and modes are hidden on the device." }));
  };

  const showPicked = () => {
    picked.replaceChildren();
    save.disabled = !entity;
    if (!entity) return;
    const name = ctx.hass.states[entity]?.attributes?.friendly_name ?? entity;
    picked.append(
      h("div", { className: "chip" }, h("span", {}, name, h("br"), h("small", { textContent: entity })), button("Change", "", () => {
        entity = null;
        items = [];
        search.hidden = false;
        results.hidden = false;
        showPicked();
        showResults();
        showControls();
        preview();
      })),
    );
    search.hidden = true;
    results.hidden = true;
  };

  const showResults = () => {
    results.replaceChildren(
      ...entityOptions(ctx.rules, ctx.hass.states, search.value).map((o) =>
        h("li", {}, h("button", { type: "button", on: { click: () => {
          entity = o.entity_id;
          items = controlItems(ctx.rules, entity, ctx.hass.states[entity], undefined);
          showPicked();
          showControls();
          showIconHint();
          refresh();
        } } }, o.name, h("small", { textContent: o.entity_id }))),
      ),
    );
  };

  search.addEventListener("input", showResults);
  nameInput.addEventListener("input", preview);
  iconInput.addEventListener("input", showIconHint);
  iconInput.addEventListener("change", refresh);

  const dlg = open(
    ctx,
    tile ? "Edit tile" : "Add tile",
    [
      h("div", { className: "field" }, h("span", { textContent: "Entity" }), picked, search, results),
      h("label", { className: "field" }, h("span", { textContent: "Name (optional)" }), nameInput),
      h("label", { className: "field" }, h("span", { textContent: "Icon (optional)" }), iconInput, iconHint),
      controls,
      h("div", { className: "preview" }, canvas),
    ],
    [button("Cancel", "", () => dlg.close()), save],
  );
  showPicked();
  showResults();
  showControls();
  showIconHint();
  refresh();
}

// Edit one view: title, layout and snapshot flag, or move or delete it. The
// flag shows when the device sleeps, or when it is set, so it can be cleared.
export function viewDialog(ctx, view, position, onApply) {
  const title = h("input", { type: "text", maxLength: 32, value: view.title });
  const layout = h(
    "select",
    {},
    ...ctx.profile.layouts.map((l, i) =>
      h("option", { value: String(i), selected: i === view.layout, disabled: l.slots.length < view.tiles.length, textContent: `${l.columns} columns, ${l.slots.length} tiles` }),
    ),
  );
  const snapshot = h("input", { type: "checkbox", checked: ctx.snapshot === view.path });
  const apply = (extra) => {
    dlg.close();
    onApply({ title: title.value.trim(), layout: Number(layout.value), snapshot: snapshot.checked, ...extra });
  };
  let sure = false;
  const remove = button("Delete view", "danger", () => {
    if (!sure) {
      sure = true;
      remove.textContent = "Click again to delete";
      return;
    }
    apply({ remove: true });
  });
  const dlg = open(
    ctx,
    "Edit view",
    [
      h("label", { className: "field" }, h("span", { textContent: "Title" }), title),
      h("label", { className: "field" }, h("span", { textContent: "Layout" }), layout),
      ctx.sleeps || ctx.snapshot === view.path ? h("label", { className: "field" }, h("span", { textContent: "Snapshot view" }), h("span", {}, snapshot, " Shown on the device while it sleeps")) : null,
      h("p", { className: "hint", textContent: "A layout with fewer slots than the view has tiles cannot be chosen." }),
      h("div", {}, button("Move left", "", () => apply({ move: -1 }), { disabled: position.index === 0 }), button("Move right", "", () => apply({ move: 1 }), { disabled: position.index === position.count - 1 })),
    ],
    [remove, button("Cancel", "", () => dlg.close()), button("Save", "primary", () => apply({}))],
  );
}
