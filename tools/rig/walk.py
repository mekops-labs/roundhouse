"""Walk the editor page in a browser: dialogs, layout rules, drag, and Done.

Runs inside Playwright's container (`rig.py walk`). It prints one line per check
and exits non-zero when one fails. The page must show a device with a saved view
`home` of nine tiles in the 3-column layout, and the entity `climate.heatpump`
with HVAC modes and presets (`rig.py walk` sets both up).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

FIND = """(() => { const find = (root) => { const el = root.querySelector('roundhouse-panel'); if (el) return el;
  for (const n of root.querySelectorAll('*')) { if (n.shadowRoot) { const f = find(n.shadowRoot); if (f) return f; } }
  return null; }; return find(document); })()"""

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail != "" else ""))
    if not ok:
        failures.append(name)


async def panel(page: Page, expr: str) -> object:
    return await page.evaluate(f"() => {{ const panel = {FIND}; return {expr}; }}")


async def settle(page: Page, ms: int = 400) -> None:
    await page.wait_for_timeout(ms)


async def pick_entity(page: Page, query: str) -> None:
    dialog = page.locator("dialog[open]")
    await dialog.locator('input[type="search"]').fill(query)
    await dialog.locator(".results button").first.click()
    await settle(page, 600)


async def save_dialog(page: Page) -> None:
    await page.locator('dialog[open] button:has-text("Save")').click()
    await page.locator("dialog[open]").wait_for(state="detached")
    await settle(page)


async def tiles(page: Page, view: int = 0) -> list[str]:
    return await panel(page, f"panel._draft.views[{view}].tiles.map(t => t.entity_id)")  # type: ignore[return-value]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18123")
    parser.add_argument("--out", default="/rig")
    parser.add_argument("--wait", type=int, default=7000)
    args = parser.parse_args()
    out = Path(args.out)
    stored = json.loads((out / "browser-tokens.json").read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1700, "height": 1300})
        await context.add_init_script(
            f"window.localStorage.setItem('hassTokens', {json.dumps(json.dumps(stored))});"
        )
        page = await context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        await page.goto(f"{args.base}/roundhouse", wait_until="load")
        await page.wait_for_timeout(args.wait)

        await page.locator('button[aria-label="Edit views"]').click()
        await settle(page)
        start = await tiles(page)
        check("edit mode starts with the saved tiles", len(start) == 9, len(start))
        check(
            "one free slot has a plus",
            await page.locator('button[aria-label="Add tile"]').count() == 1,
        )

        # Add a tile through the dialog.
        await page.locator('button[aria-label="Add tile"]').click()
        await page.locator("dialog[open]").wait_for()
        check(
            "a new tile has no entity, so Save is disabled",
            await page.locator('dialog[open] button:has-text("Save")').is_disabled(),
        )
        await pick_entity(page, "Extra 1")
        check(
            "a picked entity enables Save",
            not await page.locator(
                'dialog[open] button:has-text("Save")'
            ).is_disabled(),
        )
        await page.screenshot(path=str(out / "walk-tile-dialog.png"))
        await save_dialog(page)
        added = await tiles(page)
        check(
            "the tile is added in the first free slot",
            len(added) == 10 and added[-1] == "light.extra1",
            added[-1],
        )

        # Edit it: a name and an icon.
        await page.locator('button[aria-label="Edit tile"]').nth(9).click()
        await page.locator("dialog[open]").wait_for()
        await page.locator('dialog[open] label:has-text("Name") input').fill(
            "Porch light"
        )
        await page.locator('dialog[open] label:has-text("Icon") input').fill("mdi:star")
        await page.locator('dialog[open] label:has-text("Icon") input').dispatch_event(
            "change"
        )
        await settle(page, 800)
        await save_dialog(page)
        tile = await panel(page, "panel._draft.views[0].tiles[9]")
        check(
            "name and icon overrides are kept",
            tile
            == {"entity_id": "light.extra1", "name": "Porch light", "icon": "mdi:star"},
            tile,
        )

        # A climate tile with some modes switched off (R8).
        await page.locator('button[aria-label="Add tile"]').click()
        await page.locator("dialog[open]").wait_for()
        await pick_entity(page, "Heat pump")
        modes = page.locator("dialog[open] fieldset .modes input")
        check(
            "the heat pump offers its modes",
            await modes.count() >= 4,
            await modes.count(),
        )
        for value in ("cool", "away"):
            await page.locator(
                f'dialog[open] .modes label:has-text("{value}") input'
            ).uncheck()
        await page.screenshot(path=str(out / "walk-controls.png"))
        await save_dialog(page)
        controls = await panel(page, "panel._draft.views[0].tiles[10].controls")
        by_type = {c["type"]: c.get("values") for c in controls}  # type: ignore[union-attr,attr-defined]
        check(
            "hvac and preset modes are limited",
            by_type.get("hvac_mode") == ["heat", "off"]
            and by_type.get("preset_mode") == ["eco", "comfort"],
            by_type,
        )

        # The last mode cannot be switched off.
        await page.locator('button[aria-label="Edit tile"]').nth(10).click()
        await page.locator("dialog[open]").wait_for()
        await page.locator('dialog[open] .modes label:has-text("heat") input').uncheck()
        last = page.locator('dialog[open] .modes label:has-text("off") input')
        await (
            last.click()
        )  # refused: `uncheck` would fail when the state does not change
        check("the last mode stays on", await last.is_checked())
        await page.locator('dialog[open] button:has-text("Cancel")').click()
        await settle(page)

        # Fill the layout; the plus goes away. Then a smaller layout is refused.
        while await page.locator('button[aria-label="Add tile"]').count():
            await page.locator('button[aria-label="Add tile"]').click()
            await page.locator("dialog[open]").wait_for()
            await pick_entity(page, "Ceiling")
            await save_dialog(page)
        check(
            "a full view has no plus",
            len(await tiles(page)) == 15
            and await page.locator('button[aria-label="Add tile"]').count() == 0,
            len(await tiles(page)),
        )
        await page.locator('nav.tabs button[aria-label="Edit view"]').click()
        await page.locator("dialog[open]").wait_for()
        options = page.locator("dialog[open] select option")
        disabled = await options.evaluate_all("els => els.map(o => o.disabled)")
        check(
            "a layout too small for the tiles cannot be chosen",
            disabled == [True, False],
            disabled,
        )
        await page.locator('dialog[open] button:has-text("Cancel")').click()
        await settle(page)

        # Drag the first tile into the third slot.
        before = await tiles(page)
        handle = (
            await page.locator('button[aria-label="Move tile"]').nth(0).bounding_box()
        )
        target = await page.locator(".slot.tile").nth(2).bounding_box()
        assert handle and target
        await page.mouse.move(
            handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2
        )
        await page.mouse.down()
        await page.mouse.move(
            target["x"] + target["width"] / 2,
            target["y"] + target["height"] / 2,
            steps=8,
        )
        await page.mouse.up()
        await settle(page)
        after = await tiles(page)
        check(
            "dragging a tile reorders it",
            after[:3] == [before[1], before[2], before[0]],
            after[:3],
        )

        # A second view with the smaller layout.
        await page.locator('button[aria-label="Add view"]').click()
        await settle(page)
        await page.locator('nav.tabs button[aria-label="Edit view"]').click()
        await page.locator("dialog[open]").wait_for()
        await page.locator('dialog[open] label:has-text("Title") input').fill("Second")
        await page.locator("dialog[open] select").select_option(index=0)
        await save_dialog(page)
        titles = await panel(page, "panel._draft.views.map(v => [v.title, v.layout])")
        check(
            "a view is added with a chosen layout",
            titles == [["Home", 1], ["Second", 0]],
            titles,
        )
        for _ in range(3):
            await page.locator('button[aria-label="Add tile"]').click()
            await page.locator("dialog[open]").wait_for()
            await pick_entity(page, "Desk")
            await save_dialog(page)
        await page.screenshot(path=str(out / "walk-two-views.png"))

        # An empty title is caught before the server is asked.
        await page.locator('nav.tabs button[aria-label="Edit view"]').click()
        await page.locator("dialog[open]").wait_for()
        await page.locator('dialog[open] label:has-text("Title") input').fill("")
        await save_dialog(page)
        await page.locator('header.bar button:has-text("Done")').click()
        await settle(page)
        banner = await panel(page, "panel._banner && panel._banner.list")
        check(
            "a broken draft is refused with the reason",
            bool(banner) and "title" in str(banner),
            banner,
        )
        check(
            "and stays in edit mode", await panel(page, "panel._draft !== null") is True
        )
        await page.screenshot(path=str(out / "walk-error.png"))

        # Fix it and save.
        await page.locator('nav.tabs button[aria-label="Edit view"]').click()
        await page.locator("dialog[open]").wait_for()
        await page.locator('dialog[open] label:has-text("Title") input').fill("Second")
        await save_dialog(page)
        await page.locator('header.bar button:has-text("Done")').click()
        await settle(page, 1500)
        check(
            "Done leaves edit mode", await panel(page, "panel._draft === null") is True
        )
        views = await panel(
            page, "panel._snapshot().views.map(v => [v.title, v.tiles.length])"
        )
        check(
            "the saved views come back in the snapshot",
            views == [["Home", 15], ["Second", 3]],
            views,
        )
        await page.screenshot(path=str(out / "walk-saved.png"))

        check("the page raised no error", not errors, errors[:3])
        await browser.close()
    sys.exit(1 if failures else 0)


asyncio.run(main())
