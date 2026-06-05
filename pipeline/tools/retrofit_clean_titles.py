#!/usr/bin/env python3
"""retrofit_clean_titles.py — replace raw keyword-stuffed EPROLO product
titles with the clean SEO titles the pipeline already generated.

The pipeline stores a clean, marketing-quality title in seo.title (the SEO
meta title) but leaves product.title as the raw scrape name. product.title
shows in cart, browser tab, Google H1, search — so it should be the clean
one. The original EPROLO title is preserved in custom.source for provenance.

Free + instant — no Anthropic. Just copies seo.title → product.title.
Handle (URL) is NOT changed.

USAGE:
  python pipeline/tools/retrofit_clean_titles.py            # all
  python pipeline/tools/retrofit_clean_titles.py --pid 8892...
  python pipeline/tools/retrofit_clean_titles.py --dry-run
"""
from __future__ import annotations

import argparse
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
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    return r.json()


def clean_title(seo_title: str) -> str:
    """Light tidy: strip a trailing ' | Brand' if present (keep core),
    collapse whitespace. SEO titles are already concise."""
    t = (seo_title or "").strip()
    # Keep as-is; SEO titles are good. Just cap length for safety.
    return t[:255]


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
    print(f"Scanning {len(pids)} products for title cleanup...\n")

    n_done = n_skip = 0
    for i, pid in enumerate(pids, 1):
        r = gql(store, token,
                'query($id:ID!){product(id:$id){title seo{title}}}',
                {"id": pid})
        p = r["data"]["product"]
        raw = p["title"]
        seo = (p.get("seo") or {}).get("title") or ""
        new = clean_title(seo)
        if not new or new == raw:
            n_skip += 1
            continue
        print(f"  [{i:3d}] {raw[:45]:45s}\n        → {new[:60]}")
        if args.dry_run:
            continue
        ru = gql(store, token,
                 'mutation($i:ProductInput!){productUpdate(input:$i){product{id} userErrors{field message}}}',
                 {"i": {"id": pid, "title": new}})
        errs = (((ru.get("data") or {}).get("productUpdate") or {}).get("userErrors") or [])
        if errs:
            print(f"        errs: {errs[:2]}")
        else:
            n_done += 1
        time.sleep(0.15)

    print(f"\n{'=' * 60}")
    print(f"  Titles cleaned: {n_done}")
    print(f"  Skipped (no SEO title / already clean): {n_skip}")
    if args.dry_run:
        print("\n  [dry-run] no writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
