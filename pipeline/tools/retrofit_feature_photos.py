#!/usr/bin/env python3
"""retrofit_feature_photos.py — inject distinct product photos into each
features-section card (Oura-style image cards) for existing products.

No Anthropic / no EPROLO re-scrape — reuses the IMAGE media already on the
Shopify product. Picks N distinct full-size images (skips the hero/first,
skips variant swatches, skips icons), assigns one per feature item's
image_url, and writes the updated metafield back.

USAGE:
  python pipeline/tools/retrofit_feature_photos.py            # all products
  python pipeline/tools/retrofit_feature_photos.py --pid 8892...
  python pipeline/tools/retrofit_feature_photos.py --dry-run
"""
from __future__ import annotations

import argparse
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

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
API_VERSION = "2024-10"
MIN_WIDTH = 300


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    store, token = get_token()

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
    print(f"Scanning {len(pids)} products for features-photo retrofit...\n")

    n_done = n_skip = 0
    for i, pid in enumerate(pids, 1):
        r = gql(store, token,
                'query($id:ID!){product(id:$id){handle '
                'metafield(namespace:"custom",key:"features"){value} '
                'variants(first:50){nodes{image{id}}} '
                'media(first:50){nodes{mediaContentType ... on MediaImage{id image{url width}}}}}}',
                {"id": pid})
        p = r["data"]["product"]
        handle = p["handle"]
        mf = p.get("metafield")
        if not mf or not mf.get("value"):
            n_skip += 1
            continue
        try:
            feats = json.loads(mf["value"])
        except Exception:
            n_skip += 1
            continue
        items = feats.get("items") or []
        if not items:
            n_skip += 1
            continue
        # Already has images?
        if all(it.get("image_url") for it in items):
            n_skip += 1
            continue

        # Collect candidate images: full-size, not variant swatches
        variant_media = {(v.get("image") or {}).get("id") for v in p["variants"]["nodes"] if v.get("image")}
        candidates = []
        for n in p["media"]["nodes"]:
            if n.get("mediaContentType") != "IMAGE":
                continue
            if n.get("id") in variant_media:
                continue
            img = n.get("image") or {}
            if (img.get("width") or 0) >= MIN_WIDTH and img.get("url"):
                candidates.append(img["url"].split("?")[0])
        # Skip the very first (it's usually the hero/featured already shown up top)
        usable = candidates[1:] if len(candidates) > 3 else candidates
        if len(usable) < 1:
            n_skip += 1
            continue

        # Assign one distinct image per feature item (cycle if fewer images)
        n_items = min(len(items), 3)
        changed = False
        for idx in range(n_items):
            if items[idx].get("image_url"):
                continue
            img = usable[idx % len(usable)]
            items[idx]["image_url"] = img
            items[idx].setdefault("image_alt", items[idx].get("h4", "feature"))
            changed = True
        if not changed:
            n_skip += 1
            continue
        feats["items"] = items

        print(f"  [{i:3d}] {handle[:50]:50s} → {n_items} feature photos")
        if args.dry_run:
            continue
        sq = ("mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){"
              "metafields{key} userErrors{field message}}}")
        rs = gql(store, token, sq, {"m": [{
            "ownerId": pid, "namespace": "custom", "key": "features",
            "type": "json", "value": json.dumps(feats, ensure_ascii=False),
        }]})
        errs = rs["data"]["metafieldsSet"]["userErrors"]
        if errs:
            print(f"        errs: {errs[:2]}")
        else:
            n_done += 1
        time.sleep(0.15)

    print(f"\n{'=' * 60}")
    print(f"  Features-photo added: {n_done}")
    print(f"  Skipped (no features / already has / no images): {n_skip}")
    if args.dry_run:
        print("\n  [dry-run] no writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
