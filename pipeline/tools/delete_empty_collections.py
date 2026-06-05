#!/usr/bin/env python3
"""delete_empty_collections.py — delete EMPTY MANUAL collections (SEO cleanup).

Targets ONLY collections that are BOTH:
  - manual/custom (ruleSet is null — NOT a smart/tag-rule collection), AND
  - productsCount == 0.

Smart collections are never deleted (they auto-populate from cluster tags as
products are tagged). Non-empty collections are never deleted. Manual empties
never auto-populate (no tag rule), so removing them is safe even while uploads
run. Empty collection pages are thin-content SEO liabilities + clutter the
footer directory — this removes them.

Default = DRY RUN (lists what WOULD be deleted). Pass --execute to delete.

USAGE:
  python pipeline/tools/delete_empty_collections.py            # dry-run
  python pipeline/tools/delete_empty_collections.py --execute  # delete
"""
from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


def token() -> str:
    r = requests.post(f"https://{STORE}/admin/oauth/access_token",
                      json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
                            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
                            "grant_type": "client_credentials"}, timeout=15)
    return r.json()["access_token"]


def gql(tok, query, variables=None):
    r = requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                     "Content-Type": "application/json"},
                      json={"query": query, "variables": variables or {}}, timeout=60)
    return r.json()


LIST_Q = """
query($cursor: String) {
  collections(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { id handle title productsCount { count } ruleSet { appliedDisjunctively } }
  }
}"""

DEL_M = """
mutation($id: ID!) {
  collectionDelete(input: {id: $id}) { deletedCollectionId userErrors { field message } }
}"""


def fetch_empty_manual(tok):
    out, cursor = [], None
    while True:
        d = gql(tok, LIST_Q, {"cursor": cursor})
        block = d["data"]["collections"]
        for n in block["nodes"]:
            cnt = (n.get("productsCount") or {}).get("count", 0)
            is_smart = n.get("ruleSet") is not None
            if cnt == 0 and not is_smart:
                out.append(n)
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="actually delete (default: dry-run)")
    args = ap.parse_args()
    tok = token()
    targets = fetch_empty_manual(tok)
    print(f"Empty MANUAL collections (0 products, no rule): {len(targets)}")
    for n in targets[:25]:
        print(f"   - {n['title'][:55]}  ({n['handle']})")
    if len(targets) > 25:
        print(f"   … +{len(targets) - 25} more")

    if not args.execute:
        print(f"\nDRY RUN — nothing deleted. Re-run with --execute to delete these {len(targets)}.")
        return 0

    print(f"\nDELETING {len(targets)} empty manual collections…")
    ok = err = 0
    for i, n in enumerate(targets, 1):
        d = gql(tok, DEL_M, {"id": n["id"]})
        ue = (d.get("data", {}).get("collectionDelete", {}) or {}).get("userErrors", [])
        if d.get("data", {}).get("collectionDelete", {}).get("deletedCollectionId"):
            ok += 1
        else:
            err += 1
            print(f"   ! failed {n['handle']}: {ue or d.get('errors')}")
        if i % 50 == 0:
            print(f"   …{i}/{len(targets)} (ok={ok} err={err})")
        time.sleep(0.12)  # gentle on rate limit while uploads run
    print(f"\nDone: deleted {ok}, failed {err}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
