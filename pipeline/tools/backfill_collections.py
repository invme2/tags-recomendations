#!/usr/bin/env python3
"""backfill_collections.py — fix INCOMPLETE collection membership on the
Shopify storefront caused by products being uploaded across many separate
pipeline chunk runs (inconsistent tagging between runs).

ROOT CAUSE (verified 2026-06-01):
  Storefront category collections are almost entirely SMART (rule:
  TAG EQUALS cluster:X). A product is auto-included iff it carries the
  matching `cluster:X` tag. Across overlapping chunk runs the SAME product
  sometimes received slightly different cluster-tag sets, and the version
  actually pushed to Shopify was occasionally missing one or more
  `cluster:X` tags that another run had assigned. Those products silently
  drop out of the corresponding smart collection.

  The MANUAL (custom) collections are NOT the problem: every product the
  pipeline DBs assign to a manual collection is already a member live
  (collectionAddProducts ran fine), and the 450+ empty manual collections
  are pre-created category shells with no products in this catalog — there
  is nothing to backfill into them.

FIX STRATEGY (tag route — automatic + future-proof):
  For every live product, gather the UNION of cluster: tags the pipeline DBs
  ever assigned to it (across runs/*/pipeline.db). For each such cluster tag
  that (a) has a matching SMART collection live and (b) is MISSING from the
  product's live tag list, ADD it via productUpdate. The smart collection
  then auto-includes the product. We ONLY ADD tags; we never remove a tag
  and never remove a product from a collection.

  Manual collections: as a safety net we also re-assert intended manual
  memberships via collectionAddProducts (idempotent — Shopify no-ops if the
  product is already a member). In practice this is currently 0 adds.

IDEMPOTENT + RE-RUNNABLE:
  Everything is recomputed from the LIVE Shopify state on each run, so it is
  safe to run repeatedly. A Health Care upload is still running and keeps
  creating products — RE-RUN this tool after all uploads finish to catch
  the remaining products.

DB SAFETY: pipeline DBs are opened strictly READ-ONLY (mode=ro). A live
upload is writing one of them; we never write any DB.

USAGE:
  python pipeline/tools/backfill_collections.py --dry-run    # show plan, no writes
  python pipeline/tools/backfill_collections.py              # apply ADD-only fixes
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
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
RUNS_DIR = REPO_ROOT / "runs"
API_VERSION = "2024-10"


# --------------------------------------------------------------------------- #
# Shopify helpers
# --------------------------------------------------------------------------- #
def get_token() -> tuple[str, str]:
    load_dotenv(ENV_FILE, override=True)
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={
            "client_id": os.environ["SHOPIFY_CLIENT_ID"],
            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    for attempt in range(5):
        r = requests.post(url, headers=headers,
                          json={"query": query, "variables": variables or {}}, timeout=90)
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        data = r.json()
        # GraphQL throttle
        if data.get("errors") and any("THROTTLED" in str(e) for e in data["errors"]):
            time.sleep(2 * (attempt + 1))
            continue
        return data
    return data  # type: ignore


def fetch_collections(store: str, token: str) -> dict:
    """handle/gid maps + smart-cluster -> handle/gid map. Returns dict."""
    Q = ('query($c:String){collections(first:100,after:$c){'
         'pageInfo{hasNextPage endCursor} nodes{id handle title '
         'productsCount{count} ruleSet{appliedDisjunctively rules{column relation condition}}}}}')
    nodes = []
    cursor = None
    while True:
        r = gql(store, token, Q, {"c": cursor})
        pg = r["data"]["collections"]
        nodes += pg["nodes"]
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]
    smart_cluster_to_handle = {}
    for c in nodes:
        if c["ruleSet"]:
            for rule in c["ruleSet"]["rules"]:
                if rule["column"] == "TAG" and rule["condition"].startswith("cluster:"):
                    smart_cluster_to_handle[rule["condition"]] = c["handle"]
    return {
        "nodes": nodes,
        "by_handle": {c["handle"]: c for c in nodes},
        "by_gid": {c["id"]: c for c in nodes},
        "smart_cluster_to_handle": smart_cluster_to_handle,
    }


def fetch_live_products(store: str, token: str) -> dict:
    """gid -> {tags:set, coll_gids:set}."""
    Q = ('query($c:String){products(first:100,after:$c){'
         'pageInfo{hasNextPage endCursor} nodes{id tags '
         'collections(first:50){nodes{id}}}}}')
    out = {}
    cursor = None
    while True:
        r = gql(store, token, Q, {"c": cursor})
        pg = r["data"]["products"]
        for p in pg["nodes"]:
            out[p["id"]] = {
                "tags": set(p["tags"]),
                "coll_gids": {c["id"] for c in p["collections"]["nodes"]},
            }
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]
        time.sleep(0.15)
    return out


# --------------------------------------------------------------------------- #
# Pipeline DB (READ-ONLY) — build intended membership
# --------------------------------------------------------------------------- #
def build_intended() -> dict:
    """Union across all runs/*/pipeline.db:
       shopify_product_gid -> {tags:set(cluster: tags), mcoll_gids:set}."""
    intended: dict = {}
    for db in sorted(glob.glob(str(RUNS_DIR / "*" / "pipeline.db"))):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except Exception as e:
            print(f"  [warn] cannot open {db} read-only: {e}")
            continue
        con.row_factory = sqlite3.Row
        try:
            cmap = {}  # db collection id -> shopify gid
            for r in con.execute(
                "select id, shopify_collection_id from collections"):
                cmap[r["id"]] = r["shopify_collection_id"]
            pmap = {}  # db product id -> shopify gid
            for r in con.execute(
                "select id, shopify_product_id, product_tags, status from products"):
                if r["status"] != "done" or not r["shopify_product_id"]:
                    continue
                spid = r["shopify_product_id"]
                pmap[r["id"]] = spid
                e = intended.setdefault(spid, {"tags": set(), "mcoll_gids": set()})
                try:
                    for t in json.loads(r["product_tags"] or "[]"):
                        if isinstance(t, str) and t.startswith("cluster:"):
                            e["tags"].add(t)
                except Exception:
                    pass
            for r in con.execute(
                "select product_id, collection_id from product_collections"):
                spid = pmap.get(r["product_id"])
                gid = cmap.get(r["collection_id"])
                if spid and gid:
                    intended[spid]["mcoll_gids"].add(gid)
        except Exception as e:
            print(f"  [warn] error reading {db}: {e}")
        finally:
            con.close()
    return intended


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def compute_plan(intended, live, colls):
    """Return (tag_adds, manual_adds).
    tag_adds: list of (gid, [tags_to_add], [resulting_smart_handles])
    manual_adds: dict collection_gid -> [product_gids] for MANUAL collections.
    """
    smart_map = colls["smart_cluster_to_handle"]
    by_gid = colls["by_gid"]

    tag_adds = []
    manual_adds: dict = {}
    for spid, info in intended.items():
        if spid not in live:
            continue  # stale/deleted product id from an old DB run
        live_tags = live[spid]["tags"]
        live_colls = live[spid]["coll_gids"]

        # --- tag route ---
        add = sorted(t for t in info["tags"] if t in smart_map and t not in live_tags)
        if add:
            tag_adds.append((spid, add, [smart_map[t] for t in add]))

        # --- manual safety net ---
        for gid in info["mcoll_gids"]:
            meta = by_gid.get(gid)
            if not meta or meta["ruleSet"]:
                continue  # deleted or smart (smart handled by tags)
            if gid in live_colls:
                continue  # already a member
            manual_adds.setdefault(gid, []).append(spid)

    return tag_adds, manual_adds


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
TAGS_ADD_M = """
mutation($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node { id }
    userErrors { field message }
  }
}
"""

COLL_ADD_M = """
mutation($id: ID!, $productIds: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $productIds) {
    collection { id productsCount { count } }
    userErrors { field message }
  }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show plan, write nothing")
    args = ap.parse_args()

    store, token = get_token()
    print(f"[backfill] store={store} api={API_VERSION}")

    print("[backfill] fetching live collections ...")
    colls = fetch_collections(store, token)
    n_smart = sum(1 for c in colls["nodes"] if c["ruleSet"])
    print(f"  collections: {len(colls['nodes'])} "
          f"(smart={n_smart}, manual={len(colls['nodes']) - n_smart})")

    print("[backfill] fetching live products ...")
    live = fetch_live_products(store, token)
    print(f"  live products: {len(live)}")

    print("[backfill] reading pipeline DBs (READ-ONLY) ...")
    intended = build_intended()
    print(f"  intended (done) products across all DBs: {len(intended)}")

    tag_adds, manual_adds = compute_plan(intended, live, colls)

    # --- print plan ---
    total_tags = sum(len(a[1]) for a in tag_adds)
    print("\n" + "=" * 64)
    print("PLAN — TAG ROUTE (adds cluster: tag -> smart collection auto-includes)")
    print("=" * 64)
    growth: dict = {}
    for _, tags, handles in tag_adds:
        for h in handles:
            growth[h] = growth.get(h, 0) + 1
    if tag_adds:
        for spid, tags, handles in tag_adds:
            short = spid.rsplit("/", 1)[-1]
            print(f"  product {short}: +{tags}  -> {handles}")
        print(f"\n  projected smart-collection growth:")
        for h, n in sorted(growth.items(), key=lambda x: -x[1]):
            cur = colls["by_handle"][h]["productsCount"]["count"]
            print(f"     {h:20s} {cur:4d} -> {cur + n} (+{n})")
    else:
        print("  (no missing tags — nothing to add)")
    print(f"\n  products to update: {len(tag_adds)}   tags to add: {total_tags}")

    print("\n" + "=" * 64)
    print("PLAN — MANUAL COLLECTION SAFETY NET (collectionAddProducts)")
    print("=" * 64)
    total_manual = sum(len(v) for v in manual_adds.values())
    if manual_adds:
        for gid, pids in manual_adds.items():
            h = colls["by_gid"][gid]["handle"]
            print(f"  {h:30s} += {len(pids)} products")
    else:
        print("  (no manual membership gaps)")
    print(f"\n  manual collections to touch: {len(manual_adds)}   "
          f"product-adds: {total_manual}")

    if args.dry_run:
        print("\n[dry-run] no writes performed.")
        print("[note] RE-RUN backfill_collections.py after all uploads finish "
              "to catch remaining products.")
        return 0

    # --- apply: tag adds ---
    print("\n[apply] adding tags ...")
    n_ok = n_fail = 0
    for spid, tags, _ in tag_adds:
        r = gql(store, token, TAGS_ADD_M, {"id": spid, "tags": tags})
        errs = (((r.get("data") or {}).get("tagsAdd") or {}).get("userErrors")) or []
        if r.get("errors") or errs:
            n_fail += 1
            print(f"  FAIL {spid}: {r.get('errors') or errs}")
        else:
            n_ok += 1
        time.sleep(0.25)
    print(f"  tagsAdd: ok={n_ok} fail={n_fail} (tags total {total_tags})")

    # --- apply: manual adds ---
    n_mok = n_mfail = 0
    if manual_adds:
        print("[apply] manual collectionAddProducts ...")
        for gid, pids in manual_adds.items():
            # Shopify caps productIds per call at 250; our lists are tiny.
            r = gql(store, token, COLL_ADD_M, {"id": gid, "productIds": pids})
            cd = ((r.get("data") or {}).get("collectionAddProducts")) or {}
            errs = cd.get("userErrors") or []
            if r.get("errors") or errs:
                n_mfail += 1
                print(f"  FAIL {gid}: {r.get('errors') or errs}")
            else:
                n_mok += 1
            time.sleep(0.3)
        print(f"  collectionAddProducts: ok={n_mok} fail={n_mfail}")

    # --- after counts ---
    print("\n[apply] re-fetching collection counts (smart collections lag a few "
          "seconds; re-run --dry-run later to confirm) ...")
    time.sleep(3)
    after = fetch_collections(store, token)
    print("\n  BEFORE/AFTER smart collections touched:")
    for h in sorted(growth):
        b = colls["by_handle"][h]["productsCount"]["count"]
        a = after["by_handle"][h]["productsCount"]["count"]
        print(f"     {h:20s} {b:4d} -> {a:4d}")

    print("\n[done] tags added: {} (over {} products); manual adds: {}".format(
        total_tags, len(tag_adds), total_manual))
    print("[note] A Health Care upload is still running. RE-RUN "
          "backfill_collections.py after ALL uploads finish to catch remaining "
          "products.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
