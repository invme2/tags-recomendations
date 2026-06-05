#!/usr/bin/env python3
"""Discover per-variant photos on EPROLO product pages.

EPROLO Element-UI variant tables: each .el-table__row is clickable. When
clicked, the main image area swaps to show that variant's photos. This tool
clicks each variant row in turn, captures the gallery image src list, and
prints the per-variant mapping.

Goal: prove the click + photo-swap mechanism so we can build a scraper that
extracts per-variant photo sets for Shopify upload.
"""
import asyncio, os, sys, json, re
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except: pass
from dotenv import load_dotenv
from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=True)
STATE = os.environ.get("EPROLO_STATE_FILE")


async def collect_gallery_images(page) -> list[str]:
    """Return current set of EPROLO CDN image URLs visible on the page.
    Filter to product images (oss-accelerate / oss-us-west-1 / etc) and
    drop tiny thumbnails (URLs with size hints we know are previews)."""
    urls = await page.evaluate(
        '() => [...document.querySelectorAll("img")].map(i => i.src || i.dataset.src).filter(u => u)'
    )
    out = []
    for u in urls or []:
        if "shopifyfile." in u and "aliyuncs.com/attached" in u:
            if u not in out:
                out.append(u)
    return out


async def main_async(url: str) -> int:
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        c = await b.new_context(storage_state=STATE)
        page = await c.new_page()
        print(f"Loading {url}...")
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(3000)

        # Find the variant table (first .el-form-item with multiple .el-table__row)
        form_items = await page.query_selector_all('.el-form-item')
        variant_fi = None
        variant_label = ""
        for fi in form_items:
            lbl = await fi.query_selector('.el-form-item__label')
            if not lbl: continue
            rows = await fi.query_selector_all('.el-table__row')
            if len(rows) >= 2:
                variant_fi = fi
                variant_label = (await lbl.inner_text()).strip()
                break
        if not variant_fi:
            print("No multi-variant table found.")
            return 0

        rows = await variant_fi.query_selector_all('.el-table__row')
        print(f"Found {len(rows)} variant rows under axis '{variant_label}'\n")

        # Capture INITIAL gallery
        initial_urls = await collect_gallery_images(page)
        print(f"Initial gallery: {len(initial_urls)} images")
        for u in initial_urls[:3]: print(f"  init: ...{u[-60:]}")
        print()

        # Click each variant row, wait, capture
        per_variant: dict[str, list[str]] = {}
        for i, row in enumerate(rows):
            try:
                cells = await row.query_selector_all('td')
                if not cells: continue
                name = (await cells[0].inner_text()).strip()
                if not name: continue
                print(f"--- Variant {i+1}: '{name}' ---")
                # Try clicking the row itself
                await row.scroll_into_view_if_needed()
                await row.click(timeout=5000)
                await page.wait_for_timeout(1200)  # let images load
                urls = await collect_gallery_images(page)
                per_variant[name] = urls
                diff = [u for u in urls if u not in initial_urls]
                print(f"  total imgs: {len(urls)}  new vs initial: {len(diff)}")
                for u in urls[:3]: print(f"    ...{u[-70:]}")
            except Exception as e:
                print(f"  click err: {str(e)[:80]}")
        await b.close()

        # Summary
        print("\n=== SUMMARY ===")
        unique_sets = []
        for name, urls in per_variant.items():
            key = tuple(sorted(urls))
            if key not in unique_sets:
                unique_sets.append(key)
        print(f"Total variants: {len(per_variant)}")
        print(f"Unique photo sets: {len(unique_sets)}")
        if len(unique_sets) == 1:
            print("→ All variants share THE SAME photo set (no per-variant images on this product)")
        else:
            print("→ Variants HAVE per-variant photo sets — worth scraping per variant")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(sys.argv[1])))
