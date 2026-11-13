// The Roundhouse sidebar page: edit the views of a device on a canvas that shows
// them as the device will draw them.

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
} from "./draft.js";
import { DIALOG_STYLE, tileDialog, viewDialog } from "./dialogs.js";
import { card, h, icon, iconButton, menuButton } from "./dom.js";
import { drawView } from "./draw.js";
import { fitScale, frameHeight, layoutIndex, slotAt, slotCount, slotRects, tileRect } from "./geometry.js";
import { tileLabel } from "./rules.js";
import { emptyModel, mergeRender, reduce } from "./state.js";
import { changelogUrl } from "./version.js";

const DRAFT_KEY = "roundhouse.draft.";
const RENDER_WAIT = 150;

const STYLE = `
  :host { display: block; min-height: 100%; box-sizing: border-box; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  header.bar { display: flex; align-items: center; gap: 12px; padding: 0 16px; height: var(--header-height, 56px); box-sizing: border-box; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); }
  header.bar h1 { margin: 0; font-size: 20px; font-weight: 400; }
  header.bar .grow { flex: 1; }
  .version { font-size: 12px; opacity: .8; color: inherit; text-decoration: none; }
  a.version:hover { text-decoration: underline; }
  header.bar select { font: inherit; padding: 4px 8px; }
  .icon-button { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: inherit; cursor: pointer; --mdc-icon-size: 24px; }
  .icon-button:hover, .icon-button:focus-visible { background: rgba(127,127,127,.2); }
  .glyph { font-size: 20px; line-height: 1; }
  header.bar .text-button { color: inherit; }
  header.bar .text-button.primary { background: rgba(255,255,255,.2); }
  nav.tabs { display: flex; align-items: stretch; gap: 4px; padding: 0 16px; overflow-x: auto; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); }
  nav.tabs:empty { display: none; }
  nav.tabs .tab { display: flex; align-items: center; gap: 4px; padding: 0 16px; height: 48px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: inherit; font: inherit; text-transform: uppercase; letter-spacing: .04em; opacity: .75; cursor: pointer; white-space: nowrap; }
  nav.tabs .tab[aria-selected="true"] { opacity: 1; border-bottom-color: currentColor; }
  nav.tabs .tab.bad { color: #ffcdd2; }
  nav.tabs .tab.dragging { opacity: .4; }
  nav.tabs .tab.over { background: rgba(255,255,255,.15); }
  nav.tabs .tabgroup { display: flex; align-items: center; }
  nav.tabs .tabgroup .icon-button { width: 28px; height: 28px; --mdc-icon-size: 18px; margin-left: -8px; }
  .banner { display: flex; align-items: center; gap: 12px; margin: 16px 16px 0; padding: 12px 16px; border-radius: var(--ha-card-border-radius, 12px); background: var(--error-color, #d32f2f); color: #fff; }
  .banner.info { background: var(--info-color, #0288d1); }
  .banner ul { margin: 4px 0 0; padding-left: 18px; }
  .banner .text { flex: 1; }
  .banner .text-button { color: #fff; border: 1px solid rgba(255,255,255,.6); }
  main { padding: 16px; display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.2)); padding: 16px; box-sizing: border-box; }
  .meta { font-size: 14px; color: var(--secondary-text-color); margin: 8px 0 0; text-align: center; }
  .meta .bad { color: var(--error-color, #d32f2f); font-weight: 500; }
  .frame { position: relative; }
  canvas { display: block; border: 1px solid var(--divider-color, #ccc); }
  .overlay { position: absolute; inset: 0; }
  .slot { position: absolute; box-sizing: border-box; }
  .slot.empty { border: 2px dashed var(--divider-color, #bbb); border-radius: 4px; }
  .slot.add { display: flex; align-items: center; justify-content: center; border: 2px dashed var(--primary-color); border-radius: 4px; background: transparent; color: var(--primary-color); cursor: pointer; --mdc-icon-size: 40px; font-size: 40px; padding: 0; }
  .slot.add:hover, .slot.add:focus-visible { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .slot.tile { cursor: pointer; outline: 2px solid transparent; }
  .slot.tile:hover { outline-color: var(--primary-color); }
  .slot.drop { outline: 3px solid var(--primary-color); }
  .slot.bad { outline: 3px solid var(--error-color, #d32f2f); }
  .slot .actions { position: absolute; top: 2px; right: 2px; display: flex; background: var(--card-background-color, #fff); border-radius: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.4); color: var(--primary-text-color); }
  .slot .actions .icon-button { width: 28px; height: 28px; --mdc-icon-size: 18px; }
  .slot .actions .glyph { font-size: 15px; }
  .slot .handle { cursor: grab; touch-action: none; }
  .slot .warn { position: absolute; left: 4px; bottom: 4px; padding: 0 6px; border-radius: 8px; background: var(--warning-color, #ffa600); color: #000; font-size: 12px; }
  .note { color: var(--secondary-text-color); }
  .error { color: var(--error-color, #d32f2f); }
  ${DIALOG_STYLE}
`;

function drawIcon(ctx, rgba, size, x, y) {
  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = size;
  scratch.getContext("2d").putImageData(new ImageData(rgba, size, size), 0, 0);
  ctx.drawImage(scratch, x, y);
}

function place(el, rect, scale) {
  el.style.left = `${rect.x * scale}px`;
  el.style.top = `${rect.y * scale}px`;
  el.style.width = `${rect.w * scale}px`;
  el.style.height = `${rect.h * scale}px`;
}

function stored(key) {
  try {
    return JSON.parse(globalThis.sessionStorage?.getItem(key) ?? "null");
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    if (value === null) globalThis.sessionStorage?.removeItem(key);
    else globalThis.sessionStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be blocked; the draft is then lost on leaving, which is all.
  }
}

class RoundhousePanel extends HTMLElement {
  constructor() {
    super();
    this._model = emptyModel();
    this._devices = [];
    this._deviceId = null;
    this._unsubscribe = null;
    this._generation = 0; // bumped by _stop; a subscription from an older one is dropped
    this._frame = 0;
    this._error = null;
    this._draft = null; // the views being edited; null in view mode
    this._activePath = null;
    this._errors = []; // what a failed check or save reported
    this._banner = null;
    this._saving = false;
    this._version = null;
    this._narrow = false;
    this._renderTimer = 0;
    this._drafted = {}; // entity -> the Home Assistant state last rendered for a draft tile
    this._beforeUnload = (event) => {
      if (this._dirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    const root = this.attachShadow({ mode: "open" });
    // The header is built once per device list or mode, so a state frame never
    // resets an open device picker; each render replaces the rest.
    const style = document.createElement("style");
    style.textContent = STYLE;
    this._headerEl = document.createElement("header");
    this._headerEl.className = "bar";
    this._tabsEl = document.createElement("nav");
    this._tabsEl.className = "tabs";
    this._bannerEl = document.createElement("div");
    this._body = document.createElement("main");
    root.append(style, this._headerEl, this._tabsEl, this._bannerEl, this._body);
    this._renderHeader();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._start();
    else if (this._draft) this._scheduleDraftRender();
  }

  set narrow(value) {
    if (value === this._narrow) return;
    this._narrow = value;
    this._renderHeader();
  }

  set panel(panel) {
    const version = panel?.config?.version ?? null;
    if (version === this._version) return;
    this._version = version;
    this._renderHeader();
  }

  set route(_value) {}

  connectedCallback() {
    globalThis.addEventListener?.("beforeunload", this._beforeUnload);
    this._render();
    // Re-attached after a navigation: follow the device again.
    if (this._hass && this._deviceId && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    globalThis.removeEventListener?.("beforeunload", this._beforeUnload);
    this._keepDraft();
    this._stop();
  }

  // --- the connection ---------------------------------------------------------

  async _start() {
    try {
      this._devices = await this._hass.callWS({ type: "roundhouse/devices" });
      this._deviceId = this._devices[0]?.device_id ?? null;
      this._renderHeader();
      this._render();
      if (this._deviceId && this.isConnected) await this._subscribe();
    } catch (err) {
      this._fail(err);
    }
  }

  async _subscribe() {
    this._stop();
    const generation = this._generation;
    this._model = emptyModel();
    this._error = null;
    const deviceId = this._deviceId;
    try {
      const unsubscribe = await this._hass.connection.subscribeMessage(
        (message) => {
          if (generation !== this._generation) return;
          this._message(message);
        },
        { type: "roundhouse/editor/subscribe", device_id: deviceId },
      );
      if (generation !== this._generation) {
        unsubscribe(); // another device was picked, or the panel was detached
        return;
      }
      this._unsubscribe = unsubscribe;
    } catch (err) {
      if (generation === this._generation) this._fail(err);
    }
  }

  _stop() {
    this._generation += 1;
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  _message(message) {
    const first = !this._model.snapshot;
    this._model = reduce(this._model, message);
    if (message.type === "snapshot") {
      if (first && !this._draft) this._restore(message);
      const stale = this._draft && !this._saving && message.revision !== this._draft.revision;
      if (stale) {
        this._banner = {
          kind: "error",
          text: "These views were saved from another page, so saving your edits would conflict.",
          action: ["Discard my edits", () => this._leaveEdit()],
        };
      }
      this._renderHeader();
    }
    this._schedule();
  }

  _fail(err) {
    this._error = err?.message ?? String(err);
    this._render();
  }

  _schedule() {
    if (this._frame) return;
    this._frame = requestAnimationFrame(() => {
      this._frame = 0;
      this._render();
    });
  }

  // --- the draft --------------------------------------------------------------

  _dirty() {
    return Boolean(this._draft && isDirty(this._draft));
  }

  _snapshot() {
    return this._model.snapshot;
  }

  _views() {
    return this._draft ? this._draft.views : (this._snapshot()?.views ?? []);
  }

  _active() {
    const views = this._views();
    return views.find((v) => v.path === this._activePath) ?? views[0] ?? null;
  }

  _keepDraft() {
    if (this._deviceId) store(DRAFT_KEY + this._deviceId, this._dirty() ? this._draft : null);
  }

  // Take back the edits kept while the page was away, if the views are unchanged.
  _restore(snapshot) {
    const kept = stored(DRAFT_KEY + this._deviceId);
    store(DRAFT_KEY + this._deviceId, null);
    if (!kept || kept.revision !== snapshot.revision) return;
    this._draft = kept;
    this._banner = { kind: "info", text: "Your unsaved edits were restored." };
  }

  _edit() {
    this._draft = fromSnapshot(this._snapshot());
    this._banner = null;
    this._errors = [];
    this._renderHeader();
    this._render();
  }

  _leaveEdit() {
    this._draft = null;
    this._banner = null;
    this._errors = [];
    this._saving = false;
    store(DRAFT_KEY + this._deviceId, null);
    this._renderHeader();
    this._render();
  }

  _cancel() {
    if (this._dirty() && !globalThis.confirm?.("Discard your changes?")) return;
    this._leaveEdit();
  }

  async _done() {
    const snapshot = this._snapshot();
    const found = errorsOf(this._draft, snapshot.profile, snapshot.rules);
    if (found.length) return this._showErrors(found);
    this._saving = true;
    try {
      const result = await this._hass.callWS({
        type: "roundhouse/editor/save",
        device_id: this._deviceId,
        ...toSave(this._draft),
      });
      if (result.ok) return this._leaveEdit();
      this._saving = false;
      if (result.error === "conflict") {
        this._banner = {
          kind: "error",
          text: "These views were saved from another page in the meantime.",
          action: ["Discard my edits", () => this._leaveEdit()],
        };
        this._render();
      } else {
        this._showErrors(result.errors);
      }
    } catch (err) {
      this._saving = false;
      this._banner = { kind: "error", text: `Cannot save: ${err?.message ?? err}` };
      this._render();
    }
  }

  _showErrors(errors) {
    this._errors = errors;
    this._banner = { kind: "error", text: "The views cannot be saved yet:", list: errors.map((e) => this._describe(e)) };
    this._render();
  }

  _describe(error) {
    const view = error.view === null ? null : this._draft.views[error.view];
    const where = view ? `View "${view.title || "untitled"}"${error.tile === null ? "" : `, tile ${error.tile + 1}`}: ` : "";
    return `${where}${error.message}`;
  }

  _changed(draft) {
    this._draft = draft;
    this._errors = [];
    if (this._banner?.list) this._banner = null;
    this._renderHeader();
    this._render();
    this._scheduleDraftRender();
  }

  // Render the states of tiles the integration has not seen yet, and again when
  // their Home Assistant state changes while they are only in the draft.
  _scheduleDraftRender() {
    if (this._renderTimer || !this._draft || !this._snapshot()) return;
    this._renderTimer = setTimeout(() => {
      this._renderTimer = 0;
      this._renderDraft();
    }, RENDER_WAIT);
  }

  async _renderDraft() {
    const snapshot = this._snapshot();
    if (!this._draft || !snapshot || !this._hass) return;
    const saved = new Map();
    for (const view of snapshot.views) for (const t of view.tiles) saved.set(t.entity_id, t.icon ?? null);
    const wanted = {};
    for (const view of this._draft.views) {
      for (const t of view.tiles) {
        const unchanged = saved.has(t.entity_id) && saved.get(t.entity_id) === (t.icon ?? null);
        if (unchanged && t.entity_id in this._model.states) continue;
        const rendered = t.entity_id in this._drafted && this._drafted[t.entity_id] === this._hass.states[t.entity_id];
        if (!rendered) wanted[t.entity_id] = t.icon ?? null;
      }
    }
    const ids = Object.keys(wanted).slice(0, 64);
    if (!ids.length) return;
    for (const id of ids) this._drafted[id] = this._hass.states[id];
    await this._renderEntities(Object.fromEntries(ids.map((id) => [id, wanted[id]])));
  }

  async _renderEntities(entities) {
    try {
      const result = await this._hass.callWS({
        type: "roundhouse/editor/render",
        device_id: this._deviceId,
        entities,
      });
      this._model = mergeRender(this._model, result);
      this._schedule();
    } catch {
      // A tile without a rendered state shows an ellipsis; nothing else breaks.
    }
  }

  // --- drawing ----------------------------------------------------------------

  _render() {
    this._renderTabs();
    this._renderBanner();
    this._body.replaceChildren(this._content());
  }

  _content() {
    if (this._error) return h("p", { className: "error", textContent: `Cannot show the editor: ${this._error}` });
    if (!this._devices.length) return h("p", { className: "note", textContent: "No Roundhouse device is set up yet." });
    if (!this._snapshot()) return h("p", { className: "note", textContent: "Loading…" });
    const view = this._active();
    if (!view) return h("p", { className: "note", textContent: "This device has no views. Add one with +." });
    return this._stage(view);
  }

  _renderHeader() {
    const header = this._headerEl;
    const children = [];
    if (this._narrow) children.push(menuButton(this._hass, true));
    children.push(h("h1", { textContent: "Roundhouse" }));
    if (this._version) {
      const url = changelogUrl(this._version);
      children.push(
        url
          ? h("a", { className: "version", href: url, target: "_blank", rel: "noreferrer", textContent: this._version })
          : h("span", { className: "version", textContent: this._version }),
      );
    }
    if (this._devices.length > 1) {
      const select = h("select", { ariaLabel: "Device" });
      for (const device of this._devices) {
        select.append(h("option", { value: device.device_id, textContent: device.title, selected: device.device_id === this._deviceId }));
      }
      select.addEventListener("change", () => {
        if (this._dirty() && !globalThis.confirm?.("Discard your changes?")) {
          select.value = this._deviceId;
          return;
        }
        this._draft = null;
        this._banner = null;
        this._deviceId = select.value;
        this._subscribe();
        this._renderHeader();
      });
      children.push(select);
    }
    children.push(h("span", { className: "grow" }));
    if (this._draft) {
      children.push(
        h("button", { className: "text-button", type: "button", textContent: "Cancel", on: { click: () => this._cancel() } }),
        h("button", { className: "text-button primary", type: "button", textContent: "Done", on: { click: () => this._done() } }),
      );
    } else if (this._snapshot()) {
      children.push(iconButton("mdi:pencil", "✎", "Edit views", () => this._edit()));
    }
    header.replaceChildren(...children);
  }

  _renderTabs() {
    const views = this._views();
    const active = this._active();
    const nav = this._tabsEl;
    if (!views.length && !this._draft) {
      nav.replaceChildren();
      return;
    }
    const bad = new Set(this._errors.filter((e) => e.view !== null).map((e) => e.view));
    const tabs = views.map((view, index) => {
      const selected = active?.path === view.path;
      const tab = h("button", {
        className: `tab${bad.has(index) ? " bad" : ""}`,
        type: "button",
        role: "tab",
        draggable: Boolean(this._draft),
        textContent: view.title,
        attrs: { "aria-selected": String(selected) },
        on: { click: () => this._select(view.path) },
      });
      if (this._draft) this._dragTab(tab, index);
      if (!(this._draft && selected)) return tab;
      const pencil = iconButton("mdi:pencil", "✎", "Edit view", () => this._editView(view, index));
      return h("div", { className: "tabgroup" }, tab, pencil);
    });
    if (this._draft) {
      tabs.push(h("button", { className: "tab", type: "button", ariaLabel: "Add view", on: { click: () => this._addView() } }, icon("mdi:plus", "+")));
    }
    nav.replaceChildren(...tabs);
  }

  _dragTab(tab, index) {
    tab.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData("text/plain", String(index));
      tab.classList.add("dragging");
    });
    tab.addEventListener("dragend", () => tab.classList.remove("dragging"));
    tab.addEventListener("dragover", (event) => {
      event.preventDefault();
      tab.classList.add("over");
    });
    tab.addEventListener("dragleave", () => tab.classList.remove("over"));
    tab.addEventListener("drop", (event) => {
      event.preventDefault();
      tab.classList.remove("over");
      const from = Number(event.dataTransfer?.getData("text/plain"));
      if (Number.isInteger(from)) this._changed(moveView(this._draft, from, index));
    });
  }

  _renderBanner() {
    const banner = this._banner;
    if (!banner) {
      this._bannerEl.replaceChildren();
      return;
    }
    const list = banner.list ? h("ul", {}, banner.list.slice(0, 6).map((line) => h("li", { textContent: line }))) : null;
    const parts = [h("div", { className: "text" }, banner.text, list)];
    if (banner.action) {
      parts.push(h("button", { className: "text-button", type: "button", textContent: banner.action[0], on: { click: banner.action[1] } }));
    }
    this._bannerEl.replaceChildren(h("div", { className: banner.kind === "info" ? "banner info" : "banner", role: "alert" }, ...parts));
  }

  _select(path) {
    this._activePath = path;
    this._render();
  }

  _stage(view) {
    const profile = this._snapshot().profile;
    const states = this._hass?.states ?? {};
    const drawable = {
      key: view.path,
      title: view.title,
      layout: view.layout,
      tiles: view.tiles.map((t) => ({ ...t, label: tileLabel(t, states) })),
    };
    const slots = slotCount(profile, view);
    const layout = profile.layouts[layoutIndex(profile, view)];
    const canvas = document.createElement("canvas");
    canvas.width = profile.display.width;
    canvas.height = frameHeight(profile, view);
    const available = Math.max(240, Math.min(this.clientWidth || 960, 960) - 64);
    const scale = fitScale(canvas.width, available);
    canvas.style.width = `${Math.round(canvas.width * scale)}px`;
    canvas.style.height = `${Math.round(canvas.height * scale)}px`;
    const tabs = this._views().map((v) => ({ id: v.path, title: v.title }));
    drawView(canvas.getContext("2d"), profile, this._model, drawable, { drawIcon, tabs });

    const frame = h("div", { className: "frame" }, canvas);
    if (this._draft) frame.append(this._overlay(view, profile, scale, frame));
    const extra = view.tiles.length - slots;
    const meta = h("p", { className: "meta" });
    if (extra > 0) {
      meta.append(
        h("span", { className: "bad", textContent: `${view.tiles.length} / ${slots}: remove ${extra}.` }),
        " The device does not show this view while it does not fit.",
      );
    } else {
      meta.textContent = `${view.tiles.length} / ${slots} tiles, ${layout.columns} columns`;
    }
    return card({}, frame, meta);
  }

  // The edit controls over the canvas: one per slot, in the canvas's scale.
  _overlay(view, profile, scale, frame) {
    const overlay = h("div", { className: "overlay" });
    const rects = slotRects(profile, view);
    const index = layoutIndex(profile, view);
    const bad = new Set(
      this._errors.filter((e) => e.tile !== null && this._draft.views[e.view]?.path === view.path).map((e) => e.tile),
    );
    const slotEls = [];
    for (let i = 0; i < Math.max(rects.length, view.tiles.length); i++) {
      const rect = i < rects.length ? rects[i] : tileRect(profile, index, i);
      const tile = view.tiles[i];
      let el;
      if (tile) {
        el = this._tileControls(view, i, tile, bad.has(i) || i >= rects.length);
        el.addEventListener("click", () => this._editTile(view, i));
      } else if (i === view.tiles.length) {
        el = h("button", { className: "slot add", type: "button", ariaLabel: "Add tile", on: { click: () => this._addTile(view) } }, icon("mdi:plus", "+"));
      } else {
        el = h("div", { className: "slot empty" });
      }
      place(el, rect, scale);
      slotEls.push(el);
      overlay.append(el);
    }
    this._slotEls = slotEls;
    this._frameEl = frame;
    this._scale = scale;
    return overlay;
  }

  _tileControls(view, i, tile, isBad) {
    const missing = this._hass && !this._hass.states[tile.entity_id];
    const handle = iconButton("mdi:drag", "⠿", "Move tile", (event) => event.stopPropagation(), "handle");
    handle.addEventListener("pointerdown", (event) => this._beginDrag(event, view, i));
    const actions = h(
      "div",
      { className: "actions" },
      iconButton("mdi:pencil", "✎", "Edit tile", (event) => {
        event.stopPropagation();
        this._editTile(view, i);
      }),
      handle,
      iconButton("mdi:delete", "✕", "Remove tile", (event) => {
        event.stopPropagation();
        this._changed(removeTile(this._draft, view.path, i));
      }),
    );
    return h(
      "div",
      { className: isBad ? "slot tile bad" : "slot tile", role: "group", ariaLabel: tileLabel(tile, this._hass?.states ?? {}) },
      actions,
      missing ? h("span", { className: "warn", textContent: "Missing entity" }) : null,
    );
  }

  // --- editing ----------------------------------------------------------------

  _dialogContext(view) {
    const snapshot = this._snapshot();
    const profile = snapshot.profile;
    return {
      root: this.shadowRoot,
      hass: this._hass,
      profile,
      rules: snapshot.rules,
      model: () => this._model,
      render: (entities) => this._renderEntities(entities),
      drawIcon,
      slotRect: slotRects(profile, view)[0],
      snapshot: this._draft?.snapshot,
      sleeps: (profile.features ?? []).includes("sleep"),
    };
  }

  _addView() {
    const next = addView(this._draft, this._snapshot().profile);
    this._activePath = next.views[next.views.length - 1].path;
    this._changed(next);
  }

  _editView(view, index) {
    viewDialog(this._dialogContext(view), view, { index, count: this._draft.views.length }, (result) => {
      let draft = setTitle(this._draft, view.path, result.title);
      draft = setLayout(draft, view.path, result.layout, this._snapshot().profile).draft;
      if (result.snapshot !== (draft.snapshot === view.path)) draft = setSnapshot(draft, result.snapshot ? view.path : null);
      if (result.remove) draft = deleteView(draft, view.path);
      else if (result.move) draft = moveView(draft, index, index + result.move);
      this._changed(draft);
    });
  }

  _addTile(view) {
    tileDialog(this._dialogContext(view), null, (tile) => {
      this._changed(addTile(this._draft, view.path, tile, this._snapshot().profile).draft);
    });
  }

  _editTile(view, i) {
    tileDialog(this._dialogContext(view), view.tiles[i], (tile) => this._changed(replaceTile(this._draft, view.path, i, tile)));
  }

  // Drag a tile to another slot with the pointer, on a mouse or a finger.
  _beginDrag(event, view, from) {
    event.stopPropagation();
    const handle = event.currentTarget;
    handle.setPointerCapture?.(event.pointerId);
    const profile = this._snapshot().profile;
    const target = (e) => {
      const box = this._frameEl.getBoundingClientRect();
      const at = slotAt(profile, view, (e.clientX - box.left) / this._scale, (e.clientY - box.top) / this._scale);
      return Math.min(at, view.tiles.length - 1);
    };
    const mark = (e) => this._slotEls.forEach((el, i) => el.classList.toggle("drop", i === target(e) && i !== from));
    const finish = (e) => {
      handle.removeEventListener("pointermove", mark);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      handle.releasePointerCapture?.(e.pointerId);
      const to = target(e);
      this._slotEls.forEach((el) => el.classList.remove("drop"));
      if (e.type === "pointerup" && to >= 0 && to !== from) this._changed(moveTile(this._draft, view.path, from, to));
    };
    handle.addEventListener("pointermove", mark);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }
}

customElements.define("roundhouse-panel", RoundhousePanel);
