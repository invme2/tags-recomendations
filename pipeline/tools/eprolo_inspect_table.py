#!/usr/bin/env python3
"""Deeper inspection of EPROLO's Element-UI variant table."""
import asyncio, os, sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except: pass
from dotenv import load_dotenv
from playwright.async_api import async_playwright
REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=True)
STATE = os.environ.get("EPROLO_STATE_FILE")

async def go(url):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        c = await b.new_context(storage_state=STATE)
        page = await c.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(3000)

        # Find all el-form-items + extract label + table rows
        items = await page.query_selector_all('.el-form-item')
        print(f"Found {len(items)} el-form-item containers\n")
        for i, item in enumerate(items):
            try:
                lbl_el = await item.query_selector('.el-form-item__label')
                if not lbl_el: continue
                lbl = (await lbl_el.inner_text()).strip()
                if not lbl: continue

                # Try to extract table data
                rows = await item.query_selector_all('.el-table__row')
                if not rows:
                    rows = await item.query_selector_all('tr')
                if not rows: continue

                print(f"--- ITEM {i}: label='{lbl}' ({len(rows)} rows) ---")
                for ri, r in enumerate(rows[:5]):
                    cells = await r.query_selector_all('td')
                    cell_texts = []
                    for cell in cells:
                        t = (await cell.inner_text()).strip()
                        cell_texts.append(t[:30])
                    # Also collect images
                    imgs = await r.query_selector_all('img')
                    alts = [(await img.get_attribute('alt') or await img.get_attribute('title') or '')[:30] for img in imgs]
                    alts = [a for a in alts if a]
                    print(f"  row[{ri}] cells={cell_texts} imgs_alt={alts}")
                print()
            except Exception as e:
                print(f"  err on item {i}: {e}")

        # ALSO try to grab the cost-text cells separately + their parent row context
        print("\n=== cost-text cells in context ===")
        cost_cells = await page.query_selector_all('.cost-text')
        print(f"Found {len(cost_cells)} .cost-text cells")
        for i, c in enumerate(cost_cells[:10]):
            try:
                txt = (await c.inner_text()).strip()[:50]
                # Get sibling cells in the same row
                row = await c.evaluate_handle("e => e.closest('tr')")
                if row:
                    row_cells = await row.evaluate("r => [...r.querySelectorAll('td')].map(td => td.innerText.trim().slice(0,30))")
                    print(f"  [{i}] '{txt}'  full row: {row_cells}")
            except Exception as e:
                print(f"  err: {e}")

        await b.close()

asyncio.run(go(sys.argv[1]))
