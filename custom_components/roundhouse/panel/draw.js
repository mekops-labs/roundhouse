// Draw a view the way the device will: chrome, layout, tiles, and the overflow.

import { capacity, frameHeight, layoutIndex, overflowTop, tileRect } from "./geometry.js";
import { decodeMask, tint } from "./mask.js";

const RED = "#d32f2f";
const AMBER = [255, 193, 7];

// Colors by display format and tile state. On a gray display the mask is tinted
// in gray; on a color display in the state color.
export function tileColors(profile, state) {
  const gray = profile.display.format === "gray4";
  const on = Boolean(state?.on);
  const available = state ? state.available : false;
  if (gray) {
    return on
      ? { bg: "#000", fg: "#fff", border: "#000", icon: [255, 255, 255] }
      : { bg: "#fff", fg: available ? "#000" : "#777", border: "#000", icon: available ? [0, 0, 0] : [119, 119, 119] };
  }
  return on
    ? { bg: "#2f343a", fg: "#fff", border: "#2f343a", icon: state.color ?? AMBER }
    : { bg: "#f3f4f6", fg: available ? "#1f2328" : "#8a8f98", border: "#c9ced6", icon: [110, 118, 129] };
}

// Shorten `text` with an ellipsis until it fits `maxWidth`.
export function fitText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let cut = text.length;
  while (cut > 1 && ctx.measureText(`${text.slice(0, cut)}…`).width > maxWidth) cut--;
  return `${text.slice(0, cut)}…`;
}

function drawHatched(ctx, rect, label) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(rect.x, rect.y, rect.w, rect.h);
  ctx.clip();
  ctx.fillStyle = "#fff";
  ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  ctx.strokeStyle = RED;
  ctx.lineWidth = 3;
  ctx.beginPath();
  for (let d = -rect.h; d < rect.w; d += 14) {
    ctx.moveTo(rect.x + d, rect.y + rect.h);
    ctx.lineTo(rect.x + d + rect.h, rect.y);
  }
  ctx.stroke();
  ctx.restore();
  ctx.strokeStyle = RED;
  ctx.lineWidth = 3;
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  const size = Math.max(16, Math.round(rect.h * 0.16));
  ctx.font = `bold ${size}px sans-serif`;
  const width = ctx.measureText(label).width + 16;
  ctx.fillRect(rect.x + rect.w / 2 - width / 2, rect.y + rect.h / 2 - size, width, size * 1.8);
  ctx.fillStyle = RED;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, rect.x + rect.w / 2, rect.y + rect.h / 2);
}

function drawTile(ctx, profile, model, tile, rect, deps) {
  const state = model.states[tile.entity_id] ?? null;
  const colors = tileColors(profile, state);
  ctx.fillStyle = colors.bg;
  ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  ctx.strokeStyle = colors.border;
  ctx.lineWidth = 2;
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

  const size = profile.icon_px;
  const mask = state && model.icons[state.icon];
  if (mask) {
    const rgba = tint(decodeMask(mask, size), colors.icon);
    deps.drawIcon(ctx, rgba, size, Math.round(rect.x + (rect.w - size) / 2), Math.round(rect.y + rect.h * 0.12));
  }
  const nameSize = Math.max(14, Math.round(rect.h * 0.115));
  const textWidth = rect.w - 16;
  ctx.fillStyle = colors.fg;
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.font = `bold ${nameSize}px sans-serif`;
  ctx.fillText(fitText(ctx, tile.name, textWidth), rect.x + rect.w / 2, rect.y + rect.h * 0.12 + size + nameSize + 8);
  ctx.font = `${Math.round(nameSize * 0.9)}px sans-serif`;
  ctx.fillText(
    fitText(ctx, state ? state.text : "…", textWidth),
    rect.x + rect.w / 2,
    rect.y + rect.h * 0.12 + size + nameSize * 2.2 + 8,
  );
}

function drawChrome(ctx, profile, snapshot, current) {
  const { header, tabs } = profile.chrome;
  const gray = profile.display.format === "gray4";
  ctx.fillStyle = gray ? "#fff" : "#1f2328";
  ctx.fillRect(header[0], header[1], header[2], header[3]);
  ctx.strokeStyle = gray ? "#000" : "#1f2328";
  ctx.lineWidth = 2;
  ctx.strokeRect(header[0], header[1], header[2], header[3]);
  ctx.fillStyle = gray ? "#000" : "#fff";
  ctx.font = `bold ${Math.round(header[3] * 0.4)}px sans-serif`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(current.title, header[0] + 16, header[1] + header[3] / 2);

  const views = snapshot.views;
  if (views.length < 2) return;
  const width = tabs[2] / views.length;
  views.forEach((view, i) => {
    const active = view.path === current.path;
    const x = tabs[0] + i * width;
    ctx.fillStyle = active ? (gray ? "#000" : "#2f343a") : "#fff";
    ctx.fillRect(x, tabs[1], width, tabs[3]);
    ctx.strokeStyle = "#000";
    ctx.strokeRect(x, tabs[1], width, tabs[3]);
    ctx.fillStyle = active ? "#fff" : "#000";
    ctx.font = `${Math.round(tabs[3] * 0.32)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText(fitText(ctx, view.title, width - 12), x + width / 2, tabs[1] + tabs[3] / 2);
  });
}

// Draw one view at the device's own resolution. `deps.drawIcon(ctx, rgba, size, x, y)`
// puts a tinted mask on the canvas. Returns the height of the drawing.
export function drawView(ctx, profile, model, view, deps) {
  const snapshot = model.snapshot;
  const height = frameHeight(profile, view);
  const width = profile.display.width;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  drawChrome(ctx, profile, snapshot, view);

  const index = layoutIndex(profile, view);
  const cap = capacity(profile);
  view.tiles.forEach((tile, i) => {
    const rect = tileRect(profile, index, i);
    if (i >= cap) drawHatched(ctx, rect, `${i + 1} / ${cap}`);
    else drawTile(ctx, profile, model, tile, rect, deps);
  });

  if (view.tiles.length > cap) {
    const top = overflowTop(profile);
    ctx.strokeStyle = RED;
    ctx.lineWidth = 2;
    ctx.setLineDash?.([10, 8]);
    ctx.beginPath();
    ctx.moveTo(0, top + 6);
    ctx.lineTo(width, top + 6);
    ctx.stroke();
    ctx.setLineDash?.([]);
    ctx.fillStyle = RED;
    ctx.font = "bold 20px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(`Does not fit: remove ${view.tiles.length - cap} tile(s)`, 12, top + 34);
  }
  return height;
}
