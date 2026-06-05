"""sync_order_eprolo_links.py — for recent Shopify orders, populate
admin-only `order.metafields.custom.eprolo_sources` (JSON array) with the
EPROLO source URLs of each line-item's product, so the operator can see
EPROLO links straight from the order admin without drilling into each
product page.

PRIMARY USE-CASE: visibility. After running this, opening an order in
Shopify Admin shows a metafield card with [{title, eprolo_url, qty,
sku, variant_title}] entries — one per line item.

For ACTIONABLE fulfillment (auto-add to EPROLO cart, fill shipping
address), see `fulfill_order_via_eprolo.py`.

USAGE:
    # Process orders created in the last 7 days that don't yet have
    # the eprolo_sources metafield set.
    python pipeline/tools/sync_order_eprolo_links.py --since-days 7

    # Force re-sync (overwrite existing values — useful if you re-mapped
    # source_url on the product after the order was placed).
    python pipeline/tools/sync_order_eprolo_links.py --since-days 30 --force

    # Sync a single order by name (order number with #) or numeric id
    python pipeline/tools/sync_order_eprolo_links.py --order 1001
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

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


# ── Shopify auth ────────────────────────────────────────────────────────────
def get_shopify_token() -> Tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not token:
        cid = os.environ["SHOPIFY_CLIENT_ID"]
        sec = os.environ["SHOPIFY_CLIENT_SECRET"]
        r = requests.post(
            f"https://{store}/admin/oauth/access_token",
            json={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
    return store, token


def shopify_gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    body = {"query": query, "variables": variables or {}}
    for attempt in range(4):
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify GQL failed: {r.status_code} {r.text[:200]}")


# ── Ensure order-level metafield definition exists ──────────────────────────
def ensure_order_metafield_definition(store: str, token: str) -> bool:
    """Idempotent: create custom.eprolo_sources definition on ORDER owner if
    missing, admin-only (visible_to_storefront=False)."""
    q_check = """
    query {
      metafieldDefinitions(first: 5, ownerType: ORDER, namespace: "custom") {
        nodes { id key }
      }
    }
    """
    r = shopify_gql(store, token, q_check)
    existing = {n["key"] for n in r.get("data", {}).get("metafieldDefinitions", {}).get("nodes", [])}
    if "eprolo_sources" in existing:
        print("  metafield definition order/custom.eprolo_sources already exists")
        return True
    print("  creating metafield definition order/custom.eprolo_sources (admin-only json)...")
    q_create = """
    mutation($definition: MetafieldDefinitionInput!) {
      metafieldDefinitionCreate(definition: $definition) {
        createdDefinition { id key }
        userErrors { field message code }
      }
    }
    """
    r2 = shopify_gql(store, token, q_create, {"definition": {
        "namespace": "custom",
        "key": "eprolo_sources",
        "name": "EPROLO Sources",
        "description": "Admin-only: per-line-item EPROLO source URLs + variant + qty. "
                       "Populated by sync_order_eprolo_links.py.",
        "type": "json",
        "ownerType": "ORDER",
        "access": {"storefront": "NONE", "admin": "MERCHANT_READ_WRITE"},
    }})
    data = r2.get("data", {}).get("metafieldDefinitionCreate", {}) or {}
    errs = data.get("userErrors", []) or []
    if errs and any("taken" not in (e.get("message", "").lower()) for e in errs):
        print(f"  definition create errors: {errs}")
        return False
    return True


# ── Fetch orders ────────────────────────────────────────────────────────────
def query_orders(store: str, token: str, since_days: Optional[int] = None,
                 order_name: Optional[str] = None) -> List[dict]:
    """Return order nodes with lineItems + product metafields nested."""
    q_filter = ""
    if order_name:
        q_filter = f"name:{order_name}" if order_name.startswith("#") else f"name:#{order_name}"
    elif since_days:
        cutoff = (datetime.utcnow() - timedelta(days=since_days)).strftime("%Y-%m-%d")
        q_filter = f"created_at:>={cutoff}"

    orders = []
    cursor = None
    while True:
        q = """
        query($cursor: String, $q: String) {
          orders(first: 50, after: $cursor, query: $q, sortKey: CREATED_AT, reverse: true) {
            edges {
              cursor
              node {
                id
                name
                createdAt
                eprolo_sources: metafield(namespace: "custom", key: "eprolo_sources") { value }
                lineItems(first: 50) {
                  edges {
                    node {
                      title
                      quantity
                      sku
                      variantTitle
                      product {
                        id
                        title
                        handle
                        source_url: metafield(namespace: "custom", key: "source_url") { value }
                        source: metafield(namespace: "custom", key: "source") { value }
                      }
                    }
                  }
                }
              }
            }
            pageInfo { hasNextPage }
          }
        }
        """
        r = shopify_gql(store, token, q, {"cursor": cursor, "q": q_filter or None})
        edges = r.get("data", {}).get("orders", {}).get("edges", [])
        for e in edges:
            orders.append(e["node"])
        page = r.get("data", {}).get("orders", {}).get("pageInfo", {})
        if not page.get("hasNextPage") or order_name:
            break
        cursor = edges[-1]["cursor"]
    return orders


# ── Build payload per order ─────────────────────────────────────────────────
def build_sources(order: dict) -> List[dict]:
    """Return list of {title, eprolo_url, qty, sku, variant_title} for each
    line item that has a product with a known EPROLO URL."""
    items = []
    for e in order.get("lineItems", {}).get("edges", []):
        n = e["node"]
        prod = n.get("product") or {}
        eprolo = ""
        # source_url metafield (preferred — clickable)
        su = prod.get("source_url") or {}
        if su.get("value", "").startswith("http"):
            eprolo = su["value"]
        # fallback: source JSON
        if not eprolo:
            src = prod.get("source") or {}
            if src.get("value"):
                try:
                    eprolo = json.loads(src["value"]).get("url", "")
                except Exception:
                    pass
        if not eprolo:
            # No EPROLO URL known for this product — still include for visibility,
            # just with an empty eprolo_url so operator sees "unknown source"
            eprolo = ""
        items.append({
            "title":         n.get("title", ""),
            "qty":           n.get("quantity", 0),
            "sku":           n.get("sku", "") or "",
            "variant_title": n.get("variantTitle", "") or "",
            "eprolo_url":    eprolo,
            "product_handle": prod.get("handle", "") or "",
        })
    return items


def write_order_metafield(store: str, token: str, order_id: str, sources: List[dict]) -> bool:
    q = """
    mutation($input: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $input) {
        metafields { id key }
        userErrors { field message code }
      }
    }
    """
    r = shopify_gql(store, token, q, {"input": [{
        "ownerId": order_id,
        "namespace": "custom",
        "key": "eprolo_sources",
        "type": "json",
        "value": json.dumps(sources, ensure_ascii=False),
    }]})
    data = r.get("data", {}).get("metafieldsSet", {}) or {}
    errs = data.get("userErrors", []) or []
    if errs:
        print(f"    metafieldsSet errors: {errs[:3]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--since-days", type=int,
                   help="process orders created in the last N days")
    g.add_argument("--order", default=None,
                   help="process a single order by name/number (e.g. 1001 or #1001)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite eprolo_sources even if already set")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be written without calling metafieldsSet")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)
    store, token = get_shopify_token()
    print(f"Shopify: {store} (token: {token[:6]}...{token[-4:]})")

    print("\nEnsuring order/custom.eprolo_sources metafield definition...")
    if not args.dry_run:
        ensure_order_metafield_definition(store, token)

    print("\nFetching orders...")
    orders = query_orders(store, token,
                          since_days=args.since_days,
                          order_name=args.order)
    if not orders:
        print("No orders found.")
        return 0

    print(f"Found {len(orders)} orders. Processing...")
    ok = 0
    skip = 0
    fail = 0
    for o in orders:
        name = o.get("name", "?")
        oid = o["id"]
        already = (o.get("eprolo_sources") or {}).get("value")
        if already and not args.force:
            print(f"  [skip already set] {name}")
            skip += 1
            continue
        sources = build_sources(o)
        if not sources:
            print(f"  [skip no line items] {name}")
            skip += 1
            continue
        known_urls = sum(1 for s in sources if s.get("eprolo_url"))
        print(f"  → {name} ({len(sources)} line items, {known_urls} with EPROLO URL)")
        if args.dry_run:
            for s in sources:
                print(f"      {s['title'][:40]:40s} qty={s['qty']:>3}  {s['eprolo_url'][:50]}")
            ok += 1
        else:
            if write_order_metafield(store, token, oid, sources):
                ok += 1
            else:
                fail += 1

    print(f"\nDone: {ok} written, {skip} skipped, {fail} failed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
