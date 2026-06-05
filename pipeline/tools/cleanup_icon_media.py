#!/usr/bin/env python3
"""cleanup_icon_media.py — remove tiny icon/badge images that leaked into
product carousels (e.g. from an un-filtered gallery retrofit).

Shopify returns MediaImage.image.width/height, so we don't re-download —
just query dimensions and delete any IMAGE media below MIN_WIDTH.

USAGE:
  python pipeline/tools/cleanup_icon_media.py --dry-run
  python pipeline/tools/cleanup_icon_media.py            # delete icons
  python pipeline/tools/cleanup_icon_media.py --min-width 200
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None)
    parser.add_argument("--min-width", type=int, default=200)
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
    print(f"Scanning {len(pids)} products for icon-sized media (< {args.min_width}px)...\n")

    n_deleted = 0
    n_products_touched = 0
    for i, pid in enumerate(pids, 1):
        r = gql(store, token,
                'query($id:ID!){product(id:$id){handle media(first:50){nodes{'
                'id mediaContentType ... on MediaImage{image{width height url}}}}}}',
                {"id": pid})
        p = r["data"]["product"]
        handle = p["handle"]
        icon_ids = []
        for n in p["media"]["nodes"]:
            if n.get("mediaContentType") != "IMAGE":
                continue
            img = n.get("image") or {}
            w = img.get("width") or 0
            if w and w < args.min_width:
                icon_ids.append((n["id"], w, img.get("height")))
        if not icon_ids:
            continue
        n_products_touched += 1
        print(f"  [{i:3d}] {handle[:50]:50s} {len(icon_ids)} icon(s): "
              f"{[f'{w}x{h}' for _,w,h in icon_ids]}")
        if args.dry_run:
            continue
        ids = [iid for iid, _, _ in icon_ids]
        rd = gql(store, token,
                 'mutation($pid:ID!,$ids:[ID!]!){productDeleteMedia(productId:$pid,mediaIds:$ids){'
                 'deletedMediaIds mediaUserErrors{field message}}}',
                 {"pid": pid, "ids": ids})
        data = (rd.get("data") or {}).get("productDeleteMedia") or {}
        deleted = data.get("deletedMediaIds") or []
        n_deleted += len(deleted)
        errs = data.get("mediaUserErrors") or []
        if errs:
            print(f"        errors: {errs[:2]}")

    print(f"\n{'=' * 60}")
    print(f"  Products with icons: {n_products_touched}")
    print(f"  Icon media deleted: {n_deleted}")
    if args.dry_run:
        print("\n  [dry-run] no deletions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
