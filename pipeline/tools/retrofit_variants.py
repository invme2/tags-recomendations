#!/usr/bin/env python3
"""retrofit_variants.py — re-scrape EPROLO source page for existing live
products and add Shopify variants if any are found.

Use case: pipeline created products before the Element-UI variant scraper
patch (2026-05-28). Those products in Shopify have 1 default variant even
if EPROLO had multiple (color/size/NET WT). This tool:

  1. Reads custom.source metafield for each product → gets EPROLO URL
  2. Re-opens that URL via Playwright (using EPROLO storage_state)
  3. Extracts variants via .el-form-item > .el-table parser
  4. If variants found AND Shopify product has only 1 variant:
       - productOptionsCreate(name, values)
       - productVariantsBulkUpdate per-variant prices (using calc_price)
       - leave inventory tracked=False + CONTINUE (matches new defaults)

USAGE:
  python pipeline/tools/retrofit_variants.py                # all live
  python pipeline/tools/retrofit_variants.py --pid 8892...  # one
  python pipeline/tools/retrofit_variants.py --dry-run      # preview
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
API_VERSION = "2024-10"

# Markup (must match pipeline Cell 1 defaults; env overrides take priority)
RETAIL_MARKUP = float(os.environ.get("RETAIL_MARKUP", "10.0"))
COMPARE_AT_MARKUP = float(os.environ.get("COMPARE_AT_MARKUP", "15.0"))


def load_env() -> None:
    load_dotenv(ENV_FILE, override=True)


def get_token() -> tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"},
        timeout=15,
    )
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers,
                      json={"query": query, "variables": variables or {}},
                      timeout=30)
    r.raise_for_status()
    return r.json()


def calc_price(cost: float) -> float:
    raw = cost * RETAIL_MARKUP
    if raw < 7.9:
        return 7.90
    if raw < 30:
        return round((round(raw / 5) * 5) - 0.10, 2)
    return round((round(raw / 10) * 10) - 0.10, 2)


def calc_compare(cost: float) -> float:
    return round(round((cost * COMPARE_AT_MARKUP) / 10) * 10, 2)


async def scrape_variants(page, url: str) -> list[dict]:
    """Open EPROLO URL, parse .el-form-item > .el-table for variants.
    Returns list of {option_name, values:[str], _value_prices:{name:float}}.

    Important: Element-UI el-table can have virtual scroll + lazy render.
    We scroll the table container to bottom to materialise all rows."""
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    if "/app/product/" not in (page.url or ""):
        return []
    await page.wait_for_timeout(2500)
    variants: list[dict] = []
    form_items = await page.query_selector_all('.el-form-item')
    for fi in form_items:
        try:
            lbl_el = await fi.query_selector('.el-form-item__label')
            if not lbl_el:
                continue
            label_text = (await lbl_el.inner_text()).strip().rstrip(':')
            if not label_text:
                continue
            # Force-render all rows: scroll the table body to bottom + tick
            try:
                body_wrapper = await fi.query_selector('.el-table__body-wrapper')
                if body_wrapper:
                    # JS scroll to bottom, wait, scroll back
                    await body_wrapper.evaluate("el => el.scrollTo({top: el.scrollHeight, behavior: 'instant'})")
                    await page.wait_for_timeout(400)
                    await body_wrapper.evaluate("el => el.scrollTo({top: 0, behavior: 'instant'})")
                    await page.wait_for_timeout(200)
            except Exception:
                pass
            rows = await fi.query_selector_all('.el-table__row')
            if not rows:
                continue
            values = []
            value_prices: dict[str, float] = {}
            for row in rows:
                cells = await row.query_selector_all('td')
                if not cells:
                    continue
                name = (await cells[0].inner_text()).strip()
                if not name or len(name) > 60 or name in values:
                    continue
                values.append(name)
                if len(cells) > 1:
                    ptxt = (await cells[1].inner_text()).strip()
                    pm = re.search(r"(?:USD|\$)\s*(\d+(?:\.\d+)?)", ptxt)
                    if pm:
                        try:
                            pv = float(pm.group(1))
                            if 0.5 <= pv <= 5000:
                                value_prices[name] = pv
                        except ValueError:
                            pass
            if len(values) <= 1:
                continue
            if values:
                variants.append({
                    "option_name": label_text,
                    "values": values,
                    "_value_prices": value_prices,
                })
        except Exception:
            continue
    return variants[:3]  # Shopify max 3 option axes


def push_variants(store: str, token: str, product_id: str,
                  variants_data: list[dict], dry_run: bool) -> int:
    """Create options + ALL variant combinations, then set per-variant prices.

    Shopify gotcha: productOptionsCreate alone (variantStrategy default =
    LEAVE_AS_IS) only renames the single existing standalone variant — it
    does NOT materialise a variant per option value. Pass
    variantStrategy: CREATE so Shopify creates one variant per value.
    For multi-axis it creates the cartesian product.
    """
    if dry_run:
        # cartesian product size for multi-axis, else sum of single axis
        n = 1
        for v in variants_data:
            n *= max(1, len(v["values"]))
        return n

    # Step 1: productOptionsCreate WITH variantStrategy CREATE
    option_inputs = [{
        "name": v["option_name"],
        "values": [{"name": vv} for vv in v["values"]]
    } for v in variants_data]
    q1 = """
    mutation($pid: ID!, $opts: [OptionCreateInput!]!) {
      productOptionsCreate(productId: $pid, options: $opts, variantStrategy: CREATE) {
        product { id options { id name optionValues { name } } variantsCount { count } }
        userErrors { field message code }
      }
    }
    """
    r1 = gql(store, token, q1, {"pid": product_id, "opts": option_inputs})
    data1 = (r1.get("data") or {}).get("productOptionsCreate") or {}
    errs = data1.get("userErrors", []) or []
    if errs:
        real = [e for e in errs if "already exists" not in (e.get("message") or "").lower()]
        for e in errs:
            print(f"    productOptionsCreate: {e.get('code')}: {e.get('message')}")
        if real:
            return 0
    time.sleep(0.8)

    # Step 2: fetch all variants now present (should be N after CREATE)
    r2 = gql(store, token,
             'query($id: ID!) { product(id: $id) { variants(first: 100) { nodes { id title selectedOptions { name value } } } } }',
             {"id": product_id})
    all_vars = (((r2.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes", [])

    # name -> per-variant cost lookup (lowercased value names from EPROLO)
    name_to_cost: dict[str, float] = {}
    for v in variants_data:
        for name, cost in (v.get("_value_prices") or {}).items():
            name_to_cost[name.lower()] = cost

    batch = []
    for v in all_vars:
        # Build a match string from selectedOptions values (most reliable)
        sel_values = [so.get("value", "") for so in (v.get("selectedOptions") or [])]
        match_str = " ".join(sel_values).lower() or (v.get("title") or "").lower()
        cost = None
        for n, c in name_to_cost.items():
            if n and (n in match_str or match_str in n):
                cost = c
                break
        if cost is None and name_to_cost:
            cost = min(name_to_cost.values())  # fallback to cheapest
        if cost is not None and cost > 0:
            batch.append({
                "id": v["id"],
                "price": f"{calc_price(cost):.2f}",
                "compareAtPrice": f"{calc_compare(cost):.2f}",
                "inventoryPolicy": "CONTINUE",
            })

    if batch:
        q3 = """
        mutation($pid: ID!, $v: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $pid, variants: $v) {
            productVariants { id } userErrors { field message code }
          }
        }
        """
        for i in range(0, len(batch), 50):
            chunk = batch[i:i + 50]
            r3 = gql(store, token, q3, {"pid": product_id, "v": chunk})
            errs = (((r3.get("data") or {}).get("productVariantsBulkUpdate") or {}).get("userErrors") or [])
            if errs:
                print(f"    variant price update errs: {errs[:3]}")
            time.sleep(0.3)
    return len(all_vars)


async def main_async() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_env()
    store, token = get_token()
    state_file = os.environ.get("EPROLO_STATE_FILE")
    if not state_file or not Path(state_file).exists():
        print("ERR: EPROLO_STATE_FILE not set or missing", file=sys.stderr)
        return 1

    # Discover products to process
    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} nodes{id}}}',
                    {"c": cursor})
            page = r["data"]["products"]
            pids.extend(n["id"] for n in page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
    if args.limit:
        pids = pids[:args.limit]
    print(f"Scanning {len(pids)} products for retrofit-able variants...\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=state_file)
        page = await ctx.new_page()

        n_skip_singlevariant = 0
        n_skip_no_source = 0
        n_skip_already_multi = 0
        n_added = 0
        for i, pid in enumerate(pids, 1):
            # Get current variant count + source URL
            r = gql(store, token,
                    'query($id:ID!){product(id:$id){handle variantsCount{count} '
                    'metafield(namespace:"custom", key:"source"){value}}}',
                    {"id": pid})
            p = r["data"]["product"]
            handle = p["handle"]
            n_existing = p["variantsCount"]["count"]
            mf = p.get("metafield")
            if not mf or not mf.get("value"):
                n_skip_no_source += 1
                continue
            try:
                src = json.loads(mf["value"])
            except json.JSONDecodeError:
                n_skip_no_source += 1
                continue
            url = src.get("url")
            if not url or "eprolo.com" not in url:
                n_skip_no_source += 1
                continue
            if n_existing > 1:
                n_skip_already_multi += 1
                print(f"  [{i:3d}] SKIP {handle[:50]:50s} already has {n_existing} variants")
                continue

            print(f"  [{i:3d}] PROBE {handle[:50]:50s}", end=" ", flush=True)
            try:
                variants = await scrape_variants(page, url)
            except Exception as e:
                print(f"scrape err: {str(e)[:40]}")
                continue
            if not variants:
                n_skip_singlevariant += 1
                print(f"no variants on EPROLO")
                continue

            total_vals = sum(len(v["values"]) for v in variants)
            axes = ", ".join(f'{v["option_name"]}({len(v["values"])})' for v in variants)
            print(f"FOUND axes={axes} total={total_vals}")
            if args.dry_run:
                print(f"    [dry-run] would create {total_vals} variants")
                continue
            n_pushed = push_variants(store, token, pid, variants, dry_run=False)
            n_added += n_pushed
            print(f"    pushed {n_pushed} variants")
            await asyncio.sleep(0.5)

        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"  Variants added: {n_added}")
    print(f"  Already multi-variant: {n_skip_already_multi}")
    print(f"  Single-variant on EPROLO: {n_skip_singlevariant}")
    print(f"  Skipped (no source metafield): {n_skip_no_source}")
    if args.dry_run:
        print("\n  [dry-run] no Shopify writes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
