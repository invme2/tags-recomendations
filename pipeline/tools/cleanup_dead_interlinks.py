#!/usr/bin/env python3
"""cleanup_dead_interlinks.py — strip dead links from product interlinks
metafields.

When pipeline created interlinks to collections that are now empty or
unpublished, those links 404 on storefront. This tool rewrites the
custom.interlinks metafield JSON, removing items whose handle points to
empty/missing/unpublished collections.

Use after:
  • Mass unpublishing empty collections
  • Deleting old collections
  • Manual cleanup that changes collection inventory

USAGE:
  python pipeline/tools/cleanup_dead_interlinks.py                  # all products
  python pipeline/tools/cleanup_dead_interlinks.py --pid 8892...    # one product
  python pipeline/tools/cleanup_dead_interlinks.py --dry-run        # preview only
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


def fetch_live_collection_handles(store: str, token: str) -> set[str]:
    """Return only collections that are (a) non-empty AND (b) published to Online Store."""
    valid: set[str] = set()
    cursor = None
    while True:
        r = gql(store, token,
                'query($c:String){collections(first:100, after:$c){'
                'pageInfo{hasNextPage endCursor} '
                'nodes{handle productsCount{count} '
                'resourcePublications(first:5){nodes{publication{name} isPublished}}}}}',
                {"c": cursor})
        page = r["data"]["collections"]
        for c in page["nodes"]:
            count = (c.get("productsCount") or {}).get("count", 0)
            published_online = any(
                n["publication"]["name"] == "Online Store" and n["isPublished"]
                for n in c.get("resourcePublications", {}).get("nodes", [])
            )
            if count >= 1 and published_online:
                valid.add(c["handle"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return valid


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pid", type=str, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    load_env()
    store, token = get_token()

    print("Fetching live (non-empty + published) collection handles...")
    valid_handles = fetch_live_collection_handles(store, token)
    print(f"  {len(valid_handles)} valid collections\n")

    # Get all products + their interlinks
    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){'
                    'pageInfo{hasNextPage endCursor} nodes{id}}}',
                    {"c": cursor})
            page = r["data"]["products"]
            pids.extend(n["id"] for n in page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        print(f"Scanning {len(pids)} products for dead interlinks...\n")

    set_q = ('mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){'
             'metafields{key} userErrors{field message code}}}')

    n_cleaned = n_skipped = n_total_removed = 0
    for i, pid in enumerate(pids, 1):
        r = gql(store, token,
                'query($id:ID!){product(id:$id){handle '
                'metafield(namespace:"custom", key:"interlinks"){value}}}',
                {"id": pid})
        p_data = r.get("data", {}).get("product")
        if not p_data:
            continue
        handle = p_data["handle"]
        mf = p_data.get("metafield")
        if not mf or not mf.get("value"):
            continue
        try:
            data = json.loads(mf["value"])
        except json.JSONDecodeError:
            print(f"  [{i:3d}] PARSE-FAIL {handle}")
            continue
        items = data.get("items", []) or []
        kept = [it for it in items if it.get("handle") in valid_handles]
        removed = [it.get("handle") for it in items
                   if it.get("handle") not in valid_handles]
        if not removed:
            n_skipped += 1
            continue
        # Update items
        data["items"] = kept
        n_cleaned += 1
        n_total_removed += len(removed)
        print(f"  [{i:3d}] {handle[:55]:55s} kept={len(kept)} removed={len(removed)}")
        for h in removed:
            print(f"        ✗ {h}")

        if not args.dry_run:
            ri = gql(store, token, set_q, {"m": [{
                "ownerId": pid, "namespace": "custom", "key": "interlinks",
                "type": "json",
                "value": json.dumps(data, ensure_ascii=False),
            }]})
            errs = ri["data"]["metafieldsSet"]["userErrors"]
            if errs:
                print(f"        metafieldsSet err: {errs}")
            time.sleep(0.1)

    print(f"\n{'=' * 60}")
    print(f"  Cleaned: {n_cleaned} products  (skipped clean: {n_skipped})")
    print(f"  Total dead links removed: {n_total_removed}")
    if args.dry_run:
        print(f"\n  [dry-run] no metafields written. Remove --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
