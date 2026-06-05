#!/usr/bin/env python3
"""build_smart_collections.py — create SMART (rule-based) collections from
the product cluster: tags so each category auto-populates with ALL matching
products, instead of the fragmented 1-2-product manual collections.

Root problem: pipeline made a manual micro-collection per product → 62
collections averaging 1-2 products. Products carry consistent taxonomy tags
(cluster:anti-aging-skin, cluster:makeup-basics, ...). A smart collection
with rule `tag == cluster:X` pulls in EVERY product with that tag and keeps
auto-updating as new products arrive.

This tool defines a curated set of PRODUCT-TYPE clusters (skip persona/
occasion clusters like girls-night), grouped under parent categories for a
clean hierarchical menu, and creates+publishes a smart collection for each.

USAGE:
  python pipeline/tools/build_smart_collections.py --dry-run
  python pipeline/tools/build_smart_collections.py
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

# Curated product-type clusters → (clean title, parent category, icon key).
# Parent groups drive the hierarchical menu later. Persona/occasion/style
# clusters (girls-night, self-care-day, style-y2k) are intentionally excluded
# from the main category tree (they can be "shop by vibe" later).
SMART_COLLECTIONS = [
    # cluster_tag, title, handle, parent, icon
    ("makeup-basics",      "Makeup",              "makeup",              "Makeup",      "lipstick"),
    ("starter-makeup-kit", "Makeup Kits",         "makeup-kits",         "Makeup",      "palette"),
    ("lash-brow-care",     "Lashes & Brows",      "lashes-brows",        "Makeup",      "eye"),
    ("lip-care",           "Lip Care",            "lip-care",            "Makeup",      "lips"),
    ("eye-care-routine",   "Eye Care",            "eye-care",            "Makeup",      "eye"),
    ("brow-care",          "Brow Care",           "brow-care",           "Makeup",      "eye"),

    ("skincare-routine",   "Skincare",            "skincare",            "Skincare",    "drop"),
    ("anti-aging-skin",    "Anti-Aging",          "anti-aging",          "Skincare",    "sparkle"),
    ("acne-treatment",     "Acne Care",           "acne-care",           "Skincare",    "shield"),
    ("morning-routine",    "Daily Routine",       "daily-routine",       "Skincare",    "sun"),
    ("organic-natural",    "Natural & Organic",   "natural-organic",     "Skincare",    "leaf"),

    ("bath-ritual",        "Bath",                "bath",                "Bath & Body", "wave"),
    ("body-care-routine",  "Body Care",           "body-care",           "Bath & Body", "drop"),
    ("shower-upgrade",     "Shower",              "shower",              "Bath & Body", "wave"),
    ("bathroom-essentials","Bathroom",            "bathroom",            "Bath & Body", "home"),
    ("massage-therapy",    "Massage",             "massage",             "Bath & Body", "heart"),
    ("body-sculpting",     "Body Sculpting",      "body-sculpting",      "Bath & Body", "sparkle"),

    ("haircare-routine",   "Hair Care",           "hair-care",           "Hair",        "wave"),

    ("oral-care",          "Oral Care",           "oral-care",           "Oral Care",   "star"),
    ("dental-bundle",      "Dental Kits",         "dental-kits",         "Oral Care",   "star"),

    ("nail-care",          "Nail Care",           "nail-care",           "Nails",       "sparkle"),
]


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


def get_publication_ids(store: str, token: str) -> list[str]:
    r = gql(store, token, 'query{publications(first:20){nodes{id name}}}')
    pubs = {n["name"]: n["id"] for n in r["data"]["publications"]["nodes"]}
    return [pubs[n] for n in ("Online Store", "Shop") if n in pubs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    store, token = get_token()
    pub_ids = get_publication_ids(store, token)

    # Existing handles (avoid dupes; update if exists)
    existing = {}
    cursor = None
    while True:
        r = gql(store, token,
                'query($c:String){collections(first:100, after:$c){pageInfo{hasNextPage endCursor} nodes{id handle ruleSet{rules{column}}}}}',
                {"c": cursor})
        pg = r["data"]["collections"]
        for c in pg["nodes"]:
            existing[c["handle"]] = c["id"]
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]

    create_q = """
    mutation($input: CollectionInput!) {
      collectionCreate(input: $input) {
        collection { id handle productsCount { count } }
        userErrors { field message }
      }
    }
    """
    publish_q = """
    mutation($id: ID!, $input: [PublicationInput!]!) {
      publishablePublish(id: $id, input: $input) { userErrors { message } }
    }
    """

    n_created = n_exists = n_fail = 0
    for cluster, title, handle, parent, icon in SMART_COLLECTIONS:
        if handle in existing:
            print(f"  EXISTS  {handle:22s} ({parent})")
            n_exists += 1
            continue
        rule_input = {
            "title": title,
            "handle": handle,
            "ruleSet": {
                "appliedDisjunctively": False,
                "rules": [{"column": "TAG", "relation": "EQUALS",
                           "condition": f"cluster:{cluster}"}],
            },
        }
        if args.dry_run:
            print(f"  [dry] CREATE {handle:22s} smart: tag==cluster:{cluster}  ({parent})")
            continue
        r = gql(store, token, create_q, {"input": rule_input})
        cd = (r.get("data") or {}).get("collectionCreate") or {}
        coll = cd.get("collection")
        errs = cd.get("userErrors") or []
        if coll:
            cnt = (coll.get("productsCount") or {}).get("count", "?")
            print(f"  CREATE  {handle:22s} → {cnt} products (cluster:{cluster})")
            n_created += 1
            if pub_ids:
                gql(store, token, publish_q,
                    {"id": coll["id"], "input": [{"publicationId": p} for p in pub_ids]})
        else:
            print(f"  FAIL    {handle}: {errs[:1]}")
            n_fail += 1
        time.sleep(0.3)

    print(f"\n{'=' * 60}")
    print(f"  Created: {n_created}  Exists: {n_exists}  Fail: {n_fail}")
    if args.dry_run:
        print("\n  [dry-run] no writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
