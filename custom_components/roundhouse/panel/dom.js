// Small DOM helpers. The page uses only the elements Home Assistant's main bundle
// always defines (`ha-card`, `ha-icon`, `ha-menu-button`), each with a plain
// fallback, so a renamed element costs polish and not function.

// Build an element: `props` become properties, `attrs` become attributes.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  const { attrs, on, ...rest } = props;
  Object.assign(el, rest);
  for (const [name, value] of Object.entries(attrs ?? {})) el.setAttribute(name, value);
  for (const [name, handler] of Object.entries(on ?? {})) el.addEventListener(name, handler);
  el.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

const defined = (name) => typeof customElements !== "undefined" && Boolean(customElements.get(name));

// A card: `ha-card` when Home Assistant defines it, else a styled `div`.
export function card(props = {}, ...children) {
  const el = h(defined("ha-card") ? "ha-card" : "div", props, ...children);
  el.classList?.add("card");
  return el;
}

// An mdi icon: `ha-icon` when defined, else the fallback glyph.
export function icon(name, glyph) {
  if (defined("ha-icon")) {
    const el = document.createElement("ha-icon");
    el.setAttribute("icon", name);
    return el;
  }
  return h("span", { textContent: glyph, className: "glyph", ariaHidden: "true" });
}

// A button that shows an icon and has an accessible name.
export function iconButton(name, glyph, label, onClick, extra = "") {
  return h(
    "button",
    { className: `icon-button ${extra}`.trim(), type: "button", title: label, ariaLabel: label, on: { click: onClick } },
    icon(name, glyph),
  );
}

// The button that opens Home Assistant's sidebar on a narrow screen.
export function menuButton(hass, narrow) {
  if (defined("ha-menu-button")) {
    const el = document.createElement("ha-menu-button");
    el.hass = hass;
    el.narrow = narrow;
    return el;
  }
  return iconButton("mdi:menu", "☰", "Open the sidebar", (event) =>
    event.currentTarget.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })),
  );
}

// Run `fn` for each animation frame request at most once at a time.
export function once(fn) {
  let pending = 0;
  return () => {
    if (pending) return;
    pending = requestAnimationFrame(() => {
      pending = 0;
      fn();
    });
  };
}
