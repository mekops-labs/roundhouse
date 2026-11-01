import { readFileSync } from "node:fs";

const here = new URL(".", import.meta.url);

export function vector(name) {
  const path = new URL(`../../contract/vectors/v1.0/announce/${name}.json`, here);
  return JSON.parse(readFileSync(path, "utf8")).payload;
}

export function golden() {
  return JSON.parse(readFileSync(new URL("../golden/rendering.json", here), "utf8"));
}

// A canvas context that records what is drawn, with a fixed-width font.
export function recorder() {
  const calls = [];
  const props = {};
  const ctx = new Proxy(
    {},
    {
      get(_t, name) {
        if (name === "measureText") return (text) => ({ width: String(text).length * 10 });
        if (name in props) return props[name];
        return (...args) => {
          calls.push({ name, args, style: { ...props } });
        };
      },
      set(_t, name, value) {
        props[name] = value;
        return true;
      },
    },
  );
  return { ctx, calls, props };
}

export function nibbleBase64(rows) {
  const size = rows.length;
  const stride = Math.ceil(size / 2);
  const bytes = Buffer.alloc(stride * size);
  rows.forEach((row, y) =>
    row.forEach((v, x) => {
      bytes[y * stride + (x >> 1)] |= x % 2 === 0 ? v << 4 : v;
    }),
  );
  return bytes.toString("base64");
}
