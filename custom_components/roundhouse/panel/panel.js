// The Roundhouse sidebar panel: each view of a device drawn as the device will draw it.

import { drawView } from "./draw.js";
import { fitScale, frameHeight, overflowCount } from "./geometry.js";
import { emptyModel, reduce } from "./state.js";

const STYLE = `
  :host { display: block; padding: 16px; box-sizing: border-box; color: var(--primary-text-color); }
  header { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
  h1 { font-size: 20px; margin: 0; font-weight: 500; }
  select { font: inherit; padding: 4px 8px; }
  .views { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }
  section { background: var(--card-background-color, #fff); border-radius: 8px; padding: 12px; box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.2)); }
  section h2 { font-size: 16px; margin: 0 0 4px; font-weight: 500; }
  .meta { font-size: 13px; color: var(--secondary-text-color); margin: 0 0 8px; }
  .meta .bad { color: #d32f2f; font-weight: 500; }
  canvas { display: block; border: 1px solid var(--divider-color, #ccc); }
  .note { color: var(--secondary-text-color); }
  .error { color: #d32f2f; }
`;

function drawIcon(ctx, rgba, size, x, y) {
  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = size;
  scratch.getContext("2d").putImageData(new ImageData(rgba, size, size), 0, 0);
  ctx.drawImage(scratch, x, y);
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
    const root = this.attachShadow({ mode: "open" });
    // The header is built once per device list, so a state frame never resets an
    // open device picker; each render replaces only the body.
    const style = document.createElement("style");
    style.textContent = STYLE;
    this._headerEl = document.createElement("header");
    this._body = document.createElement("div");
    root.append(style, this._headerEl, this._body);
    this._renderHeader();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._start();
  }

  set narrow(_value) {}
  set route(_value) {}
  set panel(_value) {}

  connectedCallback() {
    this._render();
    // Re-attached after a navigation: follow the device again.
    if (this._hass && this._deviceId && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    this._stop();
  }

  async _start() {
    try {
      this._devices = await this._hass.callWS({ type: "roundhouse/preview/devices" });
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
          this._model = reduce(this._model, message);
          this._schedule();
        },
        { type: "roundhouse/preview/subscribe", device_id: deviceId },
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

  _render() {
    this._body.replaceChildren(this._content());
  }

  _content() {
    if (this._error) return this._text("p", `Cannot show the preview: ${this._error}`, "error");
    if (!this._devices.length) return this._text("p", "No Roundhouse device is set up yet.", "note");
    const snapshot = this._model.snapshot;
    if (!snapshot) return this._text("p", "Loading…", "note");
    return this._views(snapshot);
  }

  _text(tag, text, cls) {
    const el = document.createElement(tag);
    el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  _renderHeader() {
    const header = this._headerEl;
    header.replaceChildren(this._text("h1", "Roundhouse"));
    if (this._devices.length > 1) {
      const select = document.createElement("select");
      for (const device of this._devices) {
        const option = document.createElement("option");
        option.value = device.device_id;
        option.textContent = device.title;
        option.selected = device.device_id === this._deviceId;
        select.append(option);
      }
      select.addEventListener("change", () => {
        this._deviceId = select.value;
        this._subscribe();
      });
      header.append(select);
    }
  }

  _views(snapshot) {
    const wrap = document.createElement("div");
    wrap.className = "views";
    if (snapshot.dashboard !== "config") {
      const why =
        snapshot.dashboard === "strategy"
          ? "The dashboard is auto-generated. Take control of it to add cards."
          : "The dashboard does not exist.";
      wrap.append(this._text("p", why, "note"));
      return wrap;
    }
    const profile = snapshot.profile;
    for (const view of snapshot.views) wrap.append(this._section(profile, view));
    if (!snapshot.views.length) wrap.append(this._text("p", "The dashboard has no views.", "note"));
    return wrap;
  }

  _section(profile, view) {
    const section = document.createElement("section");
    section.append(this._text("h2", view.title));
    const meta = document.createElement("p");
    meta.className = "meta";
    const extra = overflowCount(profile, view);
    if (extra > 0) {
      const bad = document.createElement("span");
      bad.className = "bad";
      bad.textContent = `${view.count} / ${view.capacity}: remove ${extra}. ${
        view.published ? "The device keeps the last version that fitted." : "Not shown on the device."
      }`;
      meta.append(bad);
    } else {
      const columns = profile.layouts[view.layout].columns;
      meta.textContent = `${view.count} / ${view.capacity} tiles, ${columns} columns`;
    }
    section.append(meta);

    const canvas = document.createElement("canvas");
    canvas.width = profile.display.width;
    canvas.height = frameHeight(profile, view);
    const available = Math.max(240, (this.clientWidth || 1200) / 2 - 80);
    const scale = fitScale(canvas.width, available);
    canvas.style.width = `${Math.round(canvas.width * scale)}px`;
    canvas.style.height = `${Math.round(canvas.height * scale)}px`;
    drawView(canvas.getContext("2d"), profile, this._model, view, { drawIcon });
    section.append(canvas);
    return section;
  }
}

customElements.define("roundhouse-panel", RoundhousePanel);
