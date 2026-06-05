#!/usr/bin/env python3
"""retrofit_gallery.py — re-scrape EPROLO product images and attach to
Shopify carousel for products that ended up with too few photos.

Targets products with < MIN_MEDIA images (default 3). Re-scrapes the EPROLO
source page with the WIDENED CDN filter (oss-accelerate + oss-us-west-1 +
any shopifyfile.*aliyuncs.com/attached) — fixes the case where the original
run dropped photos because they came from a non-accelerate regional CDN.

USAGE:
  python pipeline/tools/retrofit_gallery.py               # auto-find low-media
  python pipeline/tools/retrofit_gallery.py --pid 8896... # one product
  python pipeline/tools/retrofit_gallery.py --min-media 3 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import struct
import sys
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
MIN_WIDTH = 300  # skip icon/badge images smaller than this


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


def _img_width(data: bytes) -> int:
    """Read pixel width from PNG/JPEG/WEBP header bytes (no PIL dependency)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            return struct.unpack(">I", data[16:20])[0]
        except Exception:
            return 0
    if data[:2] == b"\xff\xd8":  # JPEG — scan SOF markers
        i = 2
        n = len(data)
        while i < n - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3):
                try:
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w
                except Exception:
                    return 0
            try:
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
            except Exception:
                break
        return 0
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return 9999  # assume full-size (WEBP header parse skipped)
    return 0


async def scrape_images(page, url: str) -> list[str]:
    """Return REAL product image URLs only — full-size (>= MIN_WIDTH px),
    deduped, regional CDNs allowed. Filters out tiny icon/badge images
    (e.g. 56x30 EPROLO UI badges) by downloading the header and checking
    pixel width. Pulls from DOM-rendered <img> AND static HTML."""
    import requests as _rq
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    if "/app/product/" not in (page.url or ""):
        return []
    await page.wait_for_timeout(3000)
    # DOM-rendered img src (Vue lazy-loads real photos into <img>)
    dom_srcs = await page.evaluate(
        '() => [...document.querySelectorAll("img")].map(i => i.currentSrc || i.src || i.dataset.src).filter(Boolean)'
    )
    html = await page.content()
    html_urls = re.findall(r'https?://[^\s"\'<>\)]+\.(?:jpg|jpeg|png|webp)', html, re.I)
    candidates = []
    seen = set()
    for u in (dom_srcs or []) + html_urls:
        if "shopifyfile." not in u or "aliyuncs.com/attached" not in u:
            continue
        clean = u.split("?")[0]
        if clean in seen:
            continue
        seen.add(clean)
        candidates.append(clean)
    # Filter by real pixel width (skip icons/badges)
    out = []
    for u in candidates[:40]:
        try:
            r = _rq.get(u, timeout=15)
            if r.status_code == 200 and _img_width(r.content) >= MIN_WIDTH:
                out.append(u)
        except Exception:
            continue
    return out


def current_image_count(store: str, token: str, product_id: str) -> int:
    r = gql(store, token,
            'query($id:ID!){product(id:$id){media(first:50){nodes{mediaContentType}}}}',
            {"id": product_id})
    nodes = (((r.get("data") or {}).get("product") or {}).get("media") or {}).get("nodes", [])
    return sum(1 for n in nodes if n.get("mediaContentType") == "IMAGE")


def attach_images(store: str, token: str, product_id: str, urls: list[str]) -> int:
    """productCreateMedia with IMAGE type — Shopify fetches external URLs directly."""
    media = [{"originalSource": u, "mediaContentType": "IMAGE",
              "alt": f"Product image {i+1}"} for i, u in enumerate(urls)]
    if not media:
        return 0
    q = ("mutation($pid:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$pid,media:$m){"
         "media{id status} mediaUserErrors{field message}}}")
    r = gql(store, token, q, {"pid": product_id, "m": media})
    errs = (((r.get("data") or {}).get("productCreateMedia") or {}).get("mediaUserErrors") or [])
    if errs:
        print(f"      productCreateMedia errs: {errs[:2]}")
    created = (((r.get("data") or {}).get("productCreateMedia") or {}).get("media") or [])
    return len(created)


async def main_async() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None)
    parser.add_argument("--min-media", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    store, token = get_token()
    state_file = os.environ.get("EPROLO_STATE_FILE")
    if not state_file or not Path(state_file).exists():
        print("ERR: EPROLO_STATE_FILE missing", file=sys.stderr)
        return 1

    # Discover products
    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} '
                    'nodes{id media(first:50){nodes{mediaContentType}}}}}',
                    {"c": cursor})
            pg = r["data"]["products"]
            for n in pg["nodes"]:
                imgs = sum(1 for m in n["media"]["nodes"] if m["mediaContentType"] == "IMAGE")
                if imgs < args.min_media:
                    pids.append(n["id"])
            if not pg["pageInfo"]["hasNextPage"]:
                break
            cursor = pg["pageInfo"]["endCursor"]
    print(f"Found {len(pids)} products with < {args.min_media} images\n")

    n_fixed = n_still_empty = n_no_source = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=state_file)
        page = await ctx.new_page()
        for i, pid in enumerate(pids, 1):
            r = gql(store, token,
                    'query($id:ID!){product(id:$id){handle '
                    'metafield(namespace:"custom",key:"source"){value}}}',
                    {"id": pid})
            p = r["data"]["product"]
            handle = p["handle"]
            mf = p.get("metafield")
            url = None
            if mf and mf.get("value"):
                try:
                    url = json.loads(mf["value"]).get("url")
                except Exception:
                    pass
            if not url or "eprolo.com" not in url:
                n_no_source += 1
                print(f"  [{i:3d}] SKIP {handle[:48]:48s} no source URL")
                continue
            cur = current_image_count(store, token, pid)
            print(f"  [{i:3d}] {handle[:48]:48s} (has {cur} imgs)", end=" ", flush=True)
            try:
                imgs = await scrape_images(page, url)
            except Exception as e:
                print(f"scrape err: {str(e)[:40]}")
                continue
            if not imgs:
                n_still_empty += 1
                print("EPROLO returned 0 images")
                continue
            # Only attach up to ~8 to keep carousel sane; skip if already enough
            to_add = imgs[: max(0, 8 - cur)]
            print(f"→ EPROLO has {len(imgs)}, attaching {len(to_add)}")
            if args.dry_run:
                continue
            n = attach_images(store, token, pid, to_add)
            if n:
                n_fixed += 1
                print(f"      ✓ attached {n} images")
        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"  Products fixed: {n_fixed}")
    print(f"  Still empty (EPROLO 0 imgs): {n_still_empty}")
    print(f"  No source URL: {n_no_source}")
    if args.dry_run:
        print("\n  [dry-run] no writes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
