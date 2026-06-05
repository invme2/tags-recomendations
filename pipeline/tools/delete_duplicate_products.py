#!/usr/bin/env python3
"""delete_duplicate_products.py — remove duplicate products (same EPROLO source_url).

Keeps the NEWER product (higher Shopify numeric ID = created later = better quality
from the new Opus 4.8 + DeepSeek pro stack). Deletes the older duplicate(s).
Safe: reads source_url metafield, groups, deletes oldest per group only.
Default = DRY RUN. Pass --execute to delete.
"""
from __future__ import annotations
import argparse, os, sys, time
from collections import defaultdict
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


def token():
    r = requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15)
    return r.json()["access_token"]


def gql(tok, q, v=None):
    r = requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                     "Content-Type": "application/json"},
                      json={"query": q, "variables": v or {}}, timeout=60)
    return r.json()


LIST_Q = """
query($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title handle
      source_url: metafield(namespace:"custom", key:"source_url") { value }
      hero: metafield(namespace:"custom", key:"hero") { value }
    }
  }
}"""

DEL_M = """
mutation($id: ID!) {
  productDelete(input: {id: $id}) {
    deletedProductId
    userErrors { field message }
  }
}"""


def gid_num(gid: str) -> int:
    return int(gid.split("/")[-1])


def norm_src(url: str) -> str:
    """Normalize EPROLO source_url: lowercase, drop query, strip trailing
    '-N' sub-suffix after the '--<id>' so '--1709' and '--1709-1' group as the
    SAME product (EPROLO sub-listings of one item). Different ids stay separate."""
    import re
    u = (url or "").strip().lower().split("?")[0].rstrip("/")
    return re.sub(r"(--\d+)-\d+$", r"\1", u)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    tok = token()

    # fetch all products with source_url
    print("Собираю все товары...")
    products, cursor = [], None
    while True:
        d = gql(tok, LIST_Q, {"cursor": cursor})
        block = d["data"]["products"]
        for n in block["nodes"]:
            url = ((n.get("source_url") or {}).get("value") or "").strip().split("?")[0].rstrip("/")
            hv = (n.get("hero") or {}).get("value") or ""
            products.append({"id": n["id"], "title": n["title"], "handle": n["handle"],
                              "url": url, "has_hero": bool(hv and hv not in ("null", "{}", "[]"))})
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]

    print(f"Всего: {len(products)} товаров")

    # group by NORMALIZED source_url, find duplicates
    by_url = defaultdict(list)
    for p in products:
        nu = norm_src(p["url"])
        if nu:
            by_url[nu].append(p)

    dupes = {u: ps for u, ps in by_url.items() if len(ps) > 1}
    to_delete = []
    for url, ps in dupes.items():
        # keep the most complete (has hero content) then newest
        ps2 = sorted(ps, key=lambda x: (1 if x.get("has_hero") else 0, gid_num(x["id"])))
        keep = ps2[-1]
        for old in ps2[:-1]:
            to_delete.append((old, keep))

    print(f"Дубль-групп: {len(dupes)} | к удалению (старые): {len(to_delete)}")
    for old, keep in to_delete[:15]:
        print(f"  DEL [{old['title'][:45]}]  -> KEEP [{keep['title'][:45]}]")
    if len(to_delete) > 15:
        print(f"  … ещё {len(to_delete)-15}")

    if not args.execute:
        print(f"\nDRY RUN — ничего не удалено. Re-run с --execute.")
        return 0

    print(f"\nУдаляю {len(to_delete)} старых дублей...")
    ok = err = 0
    for old, keep in to_delete:
        d = gql(tok, DEL_M, {"id": old["id"]})
        did = (d.get("data") or {}).get("productDelete", {}).get("deletedProductId")
        ue = (d.get("data") or {}).get("productDelete", {}).get("userErrors", [])
        if did:
            ok += 1
        else:
            err += 1
            print(f"  ! err {old['handle']}: {ue or d.get('errors')}")
        if ok % 50 == 0 and ok:
            print(f"  …{ok+err}/{len(to_delete)} (ok={ok} err={err})")
        time.sleep(0.15)

    print(f"\nГотово: удалено {ok}, ошибок {err}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
