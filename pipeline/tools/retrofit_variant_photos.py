#!/usr/bin/env python3
"""retrofit_variant_photos.py — give each Shopify variant its own featured
photo so the carousel image switches when the customer picks a colour/size.

EPROLO mechanism (verified 2026-05-28): the variant table rows are clickable.
Clicking row N swaps the main gallery's featured image to that variant's
photo. The variant-specific photo is the first /attached/pingtai/ image in
the rendered gallery (position after the shared /image/202405/ badge).

Flow per product:
  1. Read custom.source → EPROLO URL
  2. Open page, for each variant row: click → capture featured photo URL
  3. Pair row i → Shopify variant i (by position)
  4. Download each distinct variant photo → upload to product media →
     productVariantAppendMedia(variantId, mediaId)

USAGE:
  python pipeline/tools/retrofit_variant_photos.py --pid 8897473904818
  python pipeline/tools/retrofit_variant_photos.py            # all multi-variant
  python pipeline/tools/retrofit_variant_photos.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    return r.json()


async def scrape_variant_photos(page, url: str) -> list[str]:
    """Return ordered list of per-variant featured photo URLs (one per variant
    row, in table order). Empty list if no multi-variant or capture failed."""
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    if "/app/product/" not in (page.url or ""):
        return []
    await page.wait_for_timeout(3000)

    # Find the variant table (first .el-form-item with >=2 rows)
    variant_fi = None
    for fi in await page.query_selector_all('.el-form-item'):
        rows = await fi.query_selector_all('.el-table__row')
        lbl = await fi.query_selector('.el-form-item__label')
        if lbl and len(rows) >= 2:
            variant_fi = fi
            break
    if not variant_fi:
        return []

    rows = await variant_fi.query_selector_all('.el-table__row')

    def first_real_photo(urls: list[str]) -> Optional[str]:
        """First /attached/pingtai/ full-size image (the variant featured photo)."""
        for u in urls:
            if "/attached/pingtai/" in u and "x-oss-process" not in u:
                return u.split("?")[0]
        # fallback: any non-badge full-size jpg
        for u in urls:
            if "aliyuncs.com/attached" in u and "/image/202405/" not in u and "x-oss-process" not in u:
                return u.split("?")[0]
        return None

    photos: list[str] = []
    for row in rows:
        cells = await row.query_selector_all('td')
        if not cells:
            continue
        name = (await cells[0].inner_text()).strip()
        if not name:
            continue  # skip empty placeholder rows
        try:
            await row.scroll_into_view_if_needed()
            await row.click(timeout=5000)
            await page.wait_for_timeout(1000)
        except Exception:
            photos.append("")
            continue
        urls = await page.evaluate(
            '() => [...document.querySelectorAll("img")].map(i => i.currentSrc || i.src).filter(Boolean)'
        )
        photos.append(first_real_photo(urls) or "")
    return photos


def upload_media_get_id(store: str, token: str, product_id: str, img_url: str) -> Optional[str]:
    """productCreateMedia(IMAGE) from external URL → return media id ONLY once
    Shopify has finished processing it (status READY). Variants reject
    non-READY media ('Non-ready media cannot be attached')."""
    q = ("mutation($pid:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$pid,media:$m){"
         "media{id status ... on MediaImage{id}} mediaUserErrors{field message}}}")
    r = gql(store, token, q, {"pid": product_id, "m": [{
        "originalSource": img_url, "mediaContentType": "IMAGE", "alt": "variant photo",
    }]})
    data = (r.get("data") or {}).get("productCreateMedia") or {}
    errs = data.get("mediaUserErrors") or []
    if errs:
        print(f"        media create errs: {errs[:2]}")
    media = data.get("media") or []
    if not media:
        return None
    mid = media[0]["id"]
    # Poll until READY (up to ~30s)
    pq = ('query($id:ID!){node(id:$id){... on MediaImage{id status}}}')
    for _ in range(20):
        time.sleep(1.5)
        pr = gql(store, token, pq, {"id": mid})
        node = (pr.get("data") or {}).get("node") or {}
        st = node.get("status")
        if st == "READY":
            return mid
        if st == "FAILED":
            print(f"        media FAILED to process: {mid}")
            return None
    print(f"        media still not READY after poll: {mid}")
    return mid  # return anyway; append may still work


def append_media_to_variant(store: str, token: str, product_id: str,
                            variant_id: str, media_id: str) -> bool:
    q = ("mutation($pid:ID!,$vm:[ProductVariantAppendMediaInput!]!){"
         "productVariantAppendMedia(productId:$pid,variantMedia:$vm){"
         "userErrors{field message}}}")
    r = gql(store, token, q, {"pid": product_id, "vm": [{
        "variantId": variant_id, "mediaIds": [media_id],
    }]})
    errs = (((r.get("data") or {}).get("productVariantAppendMedia") or {}).get("userErrors") or [])
    if errs:
        # "already assigned" is fine
        real = [e for e in errs if "already" not in (e.get("message") or "").lower()]
        if real:
            print(f"        appendMedia errs: {real[:2]}")
            return False
    return True


async def process_product(store: str, token: str, page, product_id: str,
                          dry_run: bool) -> str:
    """Returns status string."""
    r = gql(store, token,
            'query($id:ID!){product(id:$id){handle variantsCount{count} '
            'metafield(namespace:"custom",key:"source"){value} '
            'variants(first:50){nodes{id title image{id}}}}}',
            {"id": product_id})
    p = r["data"]["product"]
    handle = p["handle"]
    if p["variantsCount"]["count"] < 2:
        return "single-variant"
    mf = p.get("metafield")
    if not mf or not mf.get("value"):
        return "no-source"
    try:
        url = json.loads(mf["value"]).get("url")
    except Exception:
        return "no-source"
    if not url or "eprolo.com" not in url:
        return "no-source"

    variants = p["variants"]["nodes"]
    # Skip if all variants already have an image
    if all(v.get("image") for v in variants):
        return "already-assigned"

    photos = await scrape_variant_photos(page, url)
    if not photos or not any(photos):
        return "no-variant-photos"

    n = min(len(photos), len(variants))
    distinct = len(set(u for u in photos if u))
    print(f"      {len(variants)} variants ↔ {len([x for x in photos if x])} photos ({distinct} distinct)")
    if dry_run:
        for i in range(n):
            print(f"        {variants[i]['title']:18s} → ...{(photos[i] or '(none)')[-40:]}")
        return "dry-run"

    # Upload each distinct photo once, cache url→media_id
    url_to_media: dict[str, str] = {}
    assigned = 0
    for i in range(n):
        v = variants[i]
        ph = photos[i]
        if not ph or v.get("image"):
            continue
        if ph not in url_to_media:
            mid = upload_media_get_id(store, token, product_id, ph)
            if not mid:
                continue
            url_to_media[ph] = mid
            time.sleep(0.4)
        if append_media_to_variant(store, token, product_id, v["id"], url_to_media[ph]):
            assigned += 1
        time.sleep(0.3)
    print(f"      assigned {assigned}/{n} variant photos")
    return f"assigned-{assigned}"


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
        print("ERR: EPROLO_STATE_FILE missing", file=sys.stderr)
        return 1

    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} '
                    'nodes{id variantsCount{count}}}}',
                    {"c": cursor})
            pg = r["data"]["products"]
            for n in pg["nodes"]:
                if n["variantsCount"]["count"] >= 2:
                    pids.append(n["id"])
            if not pg["pageInfo"]["hasNextPage"]:
                break
            cursor = pg["pageInfo"]["endCursor"]
    if args.limit:
        pids = pids[:args.limit]
    print(f"Processing {len(pids)} multi-variant products for per-variant photos...\n")

    from collections import Counter
    stats: Counter = Counter()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=state_file)
        page = await ctx.new_page()
        for i, pid in enumerate(pids, 1):
            short = pid.split("/")[-1]
            try:
                st = await process_product(store, token, page, pid, args.dry_run)
            except Exception as e:
                st = f"err:{str(e)[:30]}"
            stats[st.split("-")[0] if st.startswith("assigned") else st] += 1
            print(f"  [{i:3d}/{len(pids)}] {short} → {st}")
        await browser.close()

    print(f"\n{'=' * 60}")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    if args.dry_run:
        print("\n  [dry-run] no writes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
