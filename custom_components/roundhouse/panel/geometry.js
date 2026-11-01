// Geometry of a device screen, taken from the device's own profile.

const OVERFLOW_MARGIN = 48;
const FALLBACK_GAP = 12;

export function capacity(profile) {
  return profile.layouts[profile.layouts.length - 1].slots.length;
}

// The layout a view is drawn in: its chosen one, or the densest when it overflows.
export function layoutIndex(profile, view) {
  return view.layout ?? profile.layouts.length - 1;
}

function toRect([x, y, w, h]) {
  return { x, y, w, h };
}

function pitches(layout) {
  const { columns, slots } = layout;
  const [x0, y0, w0, h0] = slots[0];
  const colPitch = columns > 1 ? slots[1][0] - x0 : w0 + FALLBACK_GAP;
  const rowPitch = slots.length > columns ? slots[columns][1] - y0 : h0 + FALLBACK_GAP;
  return { colPitch, rowPitch };
}

// The rectangle of tile `i`. Tiles past the last slot continue the grid in a strip
// below the screen, so the excess is visible without overlapping the chrome.
export function tileRect(profile, index, i) {
  const layout = profile.layouts[index];
  if (i < layout.slots.length) return toRect(layout.slots[i]);
  const { columns, slots } = layout;
  const { colPitch, rowPitch } = pitches(layout);
  const [x0, , w, h] = slots[0];
  const k = i - slots.length;
  return {
    x: x0 + (k % columns) * colPitch,
    y: profile.display.height + OVERFLOW_MARGIN + Math.floor(k / columns) * rowPitch,
    w,
    h,
  };
}

export function overflowCount(profile, view) {
  return Math.max(0, view.tiles.length - capacity(profile));
}

// The height of the drawing: the screen, plus the overflow strip when needed.
export function frameHeight(profile, view) {
  const extra = overflowCount(profile, view);
  if (extra === 0) return profile.display.height;
  const index = layoutIndex(profile, view);
  const last = tileRect(profile, index, capacity(profile) + extra - 1);
  return last.y + last.h + OVERFLOW_MARGIN / 2;
}

export function overflowTop(profile) {
  return profile.display.height;
}

export function fitScale(width, available) {
  return available > 0 && width > available ? available / width : 1;
}
