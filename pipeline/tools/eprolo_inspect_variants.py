#!/usr/bin/env python3
"""eprolo_inspect_variants.py — diagnostic dump of an EPROLO product page.

Opens the page with logged-in storage state, then prints:
  • All <select>, <button>, <li> groups that look like option pickers
  • All elements with class containing 'option', 'variant', 'sku', 'spec', etc
  • All inline JSON containing 'variants', 'skus', 'options', 'attribute'
  • <img alt=""> grouped near option selectors (color swatches)

Goal: identify the exact DOM pattern so we can write a correct scraper.

USAGE:
  python pipeline/tools/eprolo_inspect_variants.py <eprolo_url>
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv
from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=True)

STATE_FILE = os.environ.get("EPROLO_STATE_FILE", "")


async def inspect(url: str) -> int:
    if not STATE_FILE or not Path(STATE_FILE).exists():
        print(f"ERR: EPROLO_STATE_FILE not found ({STATE_FILE})", file=sys.stderr)
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=STATE_FILE)
        page = await ctx.new_page()
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(3000)

        if "/app/product/" not in (page.url or ""):
            print(f"REDIRECT to {page.url} — login expired?", file=sys.stderr)
            await browser.close()
            return 2

        title = await page.title()
        print(f"Title: {title[:100]}\n")

        # ─── 1. Inline JSON with variant data ───
        html = await page.content()
        print("=" * 60)
        print("1. INLINE JSON containing variant/sku/option/attribute")
        print("=" * 60)
        for pat_name, pat in [
            ("variants[]", r'"variants"\s*:\s*\[(.{20,800}?)\]'),
            ("skus[]", r'"skus"\s*:\s*\[(.{20,800}?)\]'),
            ("specs[]", r'"specs"\s*:\s*\[(.{20,800}?)\]'),
            ("attributes[]", r'"attributes"\s*:\s*\[(.{20,800}?)\]'),
            ("attribute_list", r'"attribute_list"\s*:\s*\[(.{20,800}?)\]'),
            ("sku_list", r'"sku_list"\s*:\s*\[(.{20,800}?)\]'),
            ("propertyArr", r'"propertyArr"\s*:\s*\[(.{20,800}?)\]'),
            ("propertys", r'"propertys"\s*:\s*\[(.{20,800}?)\]'),
            ("singleSpec", r'"singleSpec"\s*:\s*\[(.{20,800}?)\]'),
            ("specName", r'"specName"\s*:\s*"([^"]{1,50})"'),
            ("color_list", r'"colors?"\s*:\s*\[(.{10,400}?)\]'),
            ("size_list", r'"sizes?"\s*:\s*\[(.{10,400}?)\]'),
        ]:
            m = re.search(pat, html, re.DOTALL)
            if m:
                snippet = m.group(0)[:300]
                print(f"\n  [{pat_name}] FOUND:")
                print(f"    {snippet}")

        # ─── 2. Class selectors that might be option pickers ───
        print("\n" + "=" * 60)
        print("2. ELEMENTS with class hinting at options/variants")
        print("=" * 60)
        selectors = [
            '.spec-item', '.option-item', '.variant-item', '.sku-item',
            '.attr-item', '.attribute-item', '.product-attr', '.spec-list',
            '[class*="sku"]', '[class*="spec"]', '[class*="prop"]',
            '[class*="option"]', '[class*="variant"]', '[class*="attribute"]',
            '[class*="select-color"]', '[class*="select-size"]',
            '.color-item', '.size-item', '.option-block',
        ]
        seen_classes: set[str] = set()
        for sel in selectors:
            els = await page.query_selector_all(sel)
            if not els:
                continue
            print(f"\n  '{sel}' → {len(els)} matches")
            for i, el in enumerate(els[:3]):
                try:
                    cls = await el.get_attribute('class')
                    txt = (await el.inner_text())[:60].replace('\n', ' / ')
                    if cls and cls not in seen_classes:
                        seen_classes.add(cls)
                        print(f"    [{i}] class='{cls[:80]}' text='{txt}'")
                except Exception:
                    pass

        # ─── 3. Look for the option labels (Color: / Size: / etc) ───
        print("\n" + "=" * 60)
        print("3. LABEL-like text near option pickers")
        print("=" * 60)
        for kw in ["color", "colour", "size", "style", "scent", "flavor", "type"]:
            els = await page.query_selector_all(f'text=/^{kw}\\s*:?/i')
            if els:
                for el in els[:3]:
                    try:
                        # Get parent + sibling text
                        parent_html = await el.evaluate("e => e.parentElement?.outerHTML?.slice(0, 400)")
                        print(f"\n  Near '{kw}' label:")
                        print(f"    {parent_html}")
                    except Exception:
                        pass

        # ─── 4. <select> + <option> elements ───
        print("\n" + "=" * 60)
        print("4. NATIVE <select> elements")
        print("=" * 60)
        selects = await page.query_selector_all('select')
        print(f"  Found {len(selects)} <select>")
        for i, s in enumerate(selects[:5]):
            try:
                name = await s.get_attribute('name') or ''
                opts = await s.query_selector_all('option')
                vals = []
                for o in opts[:10]:
                    vals.append((await o.inner_text()).strip())
                print(f"    [{i}] name='{name}' options={vals}")
            except Exception:
                pass

        # ─── 5. Image alts grouped by class containing "spec/option" ───
        print("\n" + "=" * 60)
        print("5. IMAGE ALTS in spec/option containers (color swatches?)")
        print("=" * 60)
        for container_sel in ['.spec-item', '[class*="spec"]', '[class*="option"]', '[class*="variant"]']:
            containers = await page.query_selector_all(container_sel)
            for c in containers[:3]:
                imgs = await c.query_selector_all('img')
                alts = []
                for img in imgs[:8]:
                    alt = await img.get_attribute('alt') or ''
                    title = await img.get_attribute('title') or ''
                    if alt or title:
                        alts.append((alt or title)[:30])
                if alts:
                    cls = await c.get_attribute('class') or ''
                    print(f"\n  container.{cls[:50]} → image alts: {alts[:10]}")

        await browser.close()
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python eprolo_inspect_variants.py <eprolo_product_url>",
              file=sys.stderr)
        return 1
    url = sys.argv[1]
    return asyncio.run(inspect(url))


if __name__ == "__main__":
    sys.exit(main())
