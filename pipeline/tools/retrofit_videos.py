#!/usr/bin/env python3
"""retrofit_videos.py — scrape EPROLO product video(s) and attach to the
Shopify carousel for existing live products.

For each product:
  1. Read custom.source metafield → EPROLO URL
  2. Open page (Playwright + storage_state), find <video> mp4 src
  3. Skip if product already has a VIDEO media item
  4. Download mp4 → stagedUploadsCreate(VIDEO) → POST → productCreateMedia(VIDEO)

USAGE:
  python pipeline/tools/retrofit_videos.py                # all live products
  python pipeline/tools/retrofit_videos.py --pid 8896...  # one product
  python pipeline/tools/retrofit_videos.py --dry-run      # preview
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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
                      timeout=60)
    r.raise_for_status()
    return r.json()


async def scrape_video(page, url: str) -> Optional[str]:
    """Return the first product mp4 URL (cleaned of ?x-oss-process), or None."""
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    if "/app/product/" not in (page.url or ""):
        return None
    await page.wait_for_timeout(3000)
    for v in await page.query_selector_all('video[src], video source'):
        src = await v.get_attribute("src") or ""
        if ".mp4" in src.lower():
            return src.split("?")[0]
    # regex fallback over HTML
    import re
    html = await page.content()
    m = re.search(r'https?://[^\s"\'<>\)]+/attached/video/[^\s"\'<>\)]+\.mp4', html)
    return m.group(0).split("?")[0] if m else None


def product_has_video(store: str, token: str, product_id: str) -> bool:
    r = gql(store, token,
            'query($id:ID!){product(id:$id){media(first:50){nodes{mediaContentType}}}}',
            {"id": product_id})
    nodes = (((r.get("data") or {}).get("product") or {}).get("media") or {}).get("nodes", [])
    return any(n.get("mediaContentType") == "VIDEO" for n in nodes)


def attach_video(store: str, token: str, product_id: str, mp4_url: str,
                 alt: str) -> bool:
    """Download mp4 → stagedUploadsCreate(VIDEO) → POST → productCreateMedia(VIDEO)."""
    clean = mp4_url.split("?")[0]
    vr = requests.get(clean, timeout=120)
    if vr.status_code != 200 or len(vr.content) < 1000:
        print(f"      download failed: HTTP {vr.status_code}")
        return False
    vbytes = vr.content
    if len(vbytes) > 100 * 1024 * 1024:
        print(f"      too large ({len(vbytes)//1024//1024} MB) — skip")
        return False
    fname = clean.rsplit("/", 1)[-1] or "product-video.mp4"

    # stagedUploadsCreate VIDEO
    q1 = ("mutation($i:[StagedUploadInput!]!){stagedUploadsCreate(input:$i){"
          "stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}}")
    r1 = gql(store, token, q1, {"i": [{
        "resource": "VIDEO", "filename": fname, "mimeType": "video/mp4",
        "fileSize": str(len(vbytes)), "httpMethod": "POST",
    }]})
    targets = (((r1.get("data") or {}).get("stagedUploadsCreate") or {}).get("stagedTargets") or [])
    if not targets:
        print(f"      stagedUploadsCreate failed: {(((r1.get('data') or {}).get('stagedUploadsCreate') or {}).get('userErrors'))}")
        return False
    t = targets[0]
    params = {p["name"]: p["value"] for p in t["parameters"]}
    files = {"file": (fname, vbytes, "video/mp4")}
    up = requests.post(t["url"], data=params, files=files, timeout=300)
    if up.status_code not in (200, 201, 204):
        print(f"      staged POST failed: {up.status_code} {up.text[:150]}")
        return False

    # productCreateMedia VIDEO
    q2 = ("mutation($pid:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$pid,media:$m){"
          "media{id status} mediaUserErrors{field message}}}")
    r2 = gql(store, token, q2, {"pid": product_id, "m": [{
        "originalSource": t["resourceUrl"], "mediaContentType": "VIDEO", "alt": alt,
    }]})
    errs = (((r2.get("data") or {}).get("productCreateMedia") or {}).get("mediaUserErrors") or [])
    if errs:
        print(f"      productCreateMedia(VIDEO) errors: {errs[:2]}")
        return False
    return True


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
        print("ERR: EPROLO_STATE_FILE not set/missing", file=sys.stderr)
        return 1

    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} nodes{id}}}',
                    {"c": cursor})
            pg = r["data"]["products"]
            pids.extend(n["id"] for n in pg["nodes"])
            if not pg["pageInfo"]["hasNextPage"]:
                break
            cursor = pg["pageInfo"]["endCursor"]
    if args.limit:
        pids = pids[:args.limit]
    print(f"Scanning {len(pids)} products for EPROLO videos...\n")

    n_added = n_already = n_no_video = n_no_source = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=state_file)
        page = await ctx.new_page()
        for i, pid in enumerate(pids, 1):
            r = gql(store, token,
                    'query($id:ID!){product(id:$id){handle title '
                    'metafield(namespace:"custom",key:"source"){value}}}',
                    {"id": pid})
            p = r["data"]["product"]
            handle = p["handle"]
            mf = p.get("metafield")
            if not mf or not mf.get("value"):
                n_no_source += 1
                continue
            try:
                url = json.loads(mf["value"]).get("url")
            except Exception:
                n_no_source += 1
                continue
            if not url or "eprolo.com" not in url:
                n_no_source += 1
                continue
            if product_has_video(store, token, pid):
                n_already += 1
                print(f"  [{i:3d}] SKIP {handle[:50]:50s} already has video")
                continue
            print(f"  [{i:3d}] PROBE {handle[:50]:50s}", end=" ", flush=True)
            try:
                mp4 = await scrape_video(page, url)
            except Exception as e:
                print(f"scrape err: {str(e)[:40]}")
                continue
            if not mp4:
                n_no_video += 1
                print("no video")
                continue
            print(f"VIDEO {mp4.rsplit('/',1)[-1]}")
            if args.dry_run:
                print(f"      [dry-run] would download + attach")
                continue
            if attach_video(store, token, pid, mp4, alt=f"{p['title'][:60]} video"):
                n_added += 1
                print(f"      ✓ attached to carousel")
        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"  Videos attached: {n_added}")
    print(f"  Already had video: {n_already}")
    print(f"  No video on EPROLO: {n_no_video}")
    print(f"  No source metafield: {n_no_source}")
    if args.dry_run:
        print("\n  [dry-run] no Shopify writes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
