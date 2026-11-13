"""Open the Roundhouse panel in a browser and take a screenshot.

Runs inside Playwright's container (see rig.py), with the rig directory mounted at /rig.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

COUNT = """() => {
  const find = (root, sel) => { const el = root.querySelector(sel); if (el) return el;
    for (const n of root.querySelectorAll('*')) { if (n.shadowRoot) { const f = find(n.shadowRoot, sel); if (f) return f; } }
    return null; };
  const panel = find(document, 'roundhouse-panel');
  if (!panel) return {panel: false};
  const root = panel.shadowRoot;
  return {panel: true, canvases: root.querySelectorAll('canvas').length,
          sections: [...root.querySelectorAll('.tab, .meta')].map(s => s.innerText.replace(/\\n/g, ' | ').slice(0, 120)),
          text: root.textContent.slice(0, 160)};
}"""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/rig/panel.png")
    parser.add_argument("--base", default="http://127.0.0.1:18123")
    parser.add_argument("--wait", type=int, default=7000)
    parser.add_argument("--width", type=int, default=1700)
    parser.add_argument("--height", type=int, default=1300)
    parser.add_argument(
        "--device", default="", help="device ID to pick in the panel's selector"
    )
    parser.add_argument(
        "--poke",
        default="",
        help="JSON list of {entity, state, attributes} set after the first shot",
    )
    parser.add_argument(
        "--after", type=int, default=500, help="ms to wait after the poke"
    )
    args = parser.parse_args()
    stored = json.loads(Path("/rig/browser-tokens.json").read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": args.width, "height": args.height}
        )
        await context.add_init_script(
            f"window.localStorage.setItem('hassTokens', {json.dumps(json.dumps(stored))});"
        )
        page = await context.new_page()
        messages: list[str] = []
        page.on("console", lambda m: messages.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: messages.append(f"pageerror: {e}"))
        await page.goto(f"{args.base}/roundhouse", wait_until="load")
        await page.wait_for_timeout(args.wait)
        if args.device:
            await page.evaluate(
                "(id) => { const find = (root) => { const el = root.querySelector('roundhouse-panel'); if (el) return el;"
                " for (const n of root.querySelectorAll('*')) { if (n.shadowRoot) { const f = find(n.shadowRoot); if (f) return f; } }"
                " return null; }; const sel = find(document).shadowRoot.querySelector('select');"
                " sel.value = id; sel.dispatchEvent(new Event('change')); }",
                args.device,
            )
            await page.wait_for_timeout(2500)
        await page.screenshot(path=args.out)
        print(json.dumps(await page.evaluate(COUNT), indent=1))
        if args.poke:
            started = await page.evaluate("() => performance.now()")
            for item in json.loads(args.poke):
                if "save" in item:  # a views save through the frontend's own connection
                    await page.evaluate(
                        "async (save) => { await document.querySelector('home-assistant').hass.callWS("
                        "{type: 'roundhouse/editor/save', ...save}); }",
                        item["save"],
                    )
                    continue
                await page.evaluate(
                    "async ([token, item]) => { await fetch('/api/states/' + item.entity, {method: 'POST',"
                    " headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/json'},"
                    " body: JSON.stringify({state: item.state, attributes: item.attributes || {}})}); }",
                    [stored["access_token"], item],
                )
            before = json.dumps((await page.evaluate(COUNT)).get("sections"))
            changed = None
            for _ in range(int(args.after / 50)):
                await page.wait_for_timeout(50)
                if json.dumps((await page.evaluate(COUNT)).get("sections")) != before:
                    changed = round(
                        await page.evaluate("() => performance.now()") - started
                    )
                    break
            print("panel redrawn after:", changed, "ms")
            await page.wait_for_timeout(300)
            await page.screenshot(path=args.out.replace(".png", "-after.png"))
            print(
                "after the poke:",
                round(await page.evaluate("() => performance.now()") - started),
                "ms",
            )
        for line in [m for m in messages if m.startswith(("error", "pageerror"))][-10:]:
            print(line)
        await browser.close()


asyncio.run(main())
