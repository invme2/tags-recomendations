#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_demo_variants.py — TARGETED: create Color/option variants for the 2 demo
products (et570 smartwatch + hearing aid) from their scrape_json.variants, then
price every variant at the product's current price. Scoped to the demo run DB
only — does NOT touch the rest of the store.

DRY-RUN by default; --execute applies.
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, time
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
RUN_DB = ROOT / "runs" / "demo-fixed-2026-06-05" / ".db" / "pipeline.db"
MAX_OPTS, MAX_VALS, MAX_VARIANTS = 3, 50, 100


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    for a in range(5):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=60).json()
        if r.get("errors") and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in r["errors"]):
            time.sleep(2 + a); continue
        return r
    return r


def clean_opts(variants):
    """scrape_json.variants -> productOptionsCreate input (dedup, caps)."""
    opts = []
    total = 1
    for v in variants[:MAX_OPTS]:
        name = (v.get("option_name") or "Option").strip()[:50]
        seen, vals = set(), []
        for val in (v.get("values") or []):
            val = (str(val) or "").strip()[:100]
            if val and val.lower() not in seen:
                seen.add(val.lower()); vals.append(val)
        vals = vals[:MAX_VALS]
        if not vals:
            continue
        if total * len(vals) > MAX_VARIANTS:
            allowed = max(1, MAX_VARIANTS // total)
            vals = vals[:allowed]
        total *= len(vals)
        opts.append({"name": name, "values": [{"name": x} for x in vals]})
    return opts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    tok = token()
    c = sqlite3.connect(f"file:{RUN_DB.as_posix()}?mode=ro", uri=True)
    rows = c.execute("SELECT name, scrape_json, shopify_product_id FROM products WHERE shopify_product_id IS NOT NULL").fetchall()
    c.close()

    for name, sj, gid in rows:
        variants = (json.loads(sj or "{}") or {}).get("variants") or []
        opts = clean_opts(variants)
        # current variant count + price
        r = gql(tok, "query($id:ID!){product(id:$id){variantsCount{count} variants(first:1){nodes{price}}}}", {"id": gid})
        p = (r.get("data") or {}).get("product") or {}
        vcount = (p.get("variantsCount") or {}).get("count", 0)
        cur_price = ((p.get("variants") or {}).get("nodes") or [{}])[0].get("price")
        n_combo = 1
        for o in opts:
            n_combo *= len(o["values"])
        print(f"• {name[:34]} | scrape-opts: {[(o['name'], len(o['values'])) for o in opts]} | live variants now: {vcount} -> would be {n_combo} | price ${cur_price}")
        if not opts or vcount > 1:
            print("   skip (no options or already multi-variant)")
            continue
        if not args.execute:
            continue
        rc = gql(tok, """mutation($pid:ID!,$opts:[OptionCreateInput!]!){
            productOptionsCreate(productId:$pid, options:$opts, variantStrategy:CREATE){
              userErrors{field message}}}""", {"pid": gid, "opts": opts})
        ue = (((rc.get("data") or {}).get("productOptionsCreate") or {}).get("userErrors")) or []
        if ue:
            print(f"   ! optionsCreate: {ue[:2]}"); continue
        time.sleep(1)
        # price every variant at current price
        rv = gql(tok, "query($id:ID!){product(id:$id){variants(first:100){nodes{id}}}}", {"id": gid})
        vids = [n["id"] for n in (((rv.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes", [])]
        if cur_price and vids:
            upd = [{"id": vid, "price": str(cur_price)} for vid in vids]
            for i in range(0, len(upd), 50):
                gql(tok, """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
                    productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{message}}}""",
                    {"pid": gid, "v": upd[i:i+50]})
                time.sleep(0.3)
        print(f"   ✅ created {len(vids)} variants @ ${cur_price}")
    if not args.execute:
        print("\nDRY-RUN — re-run with --execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
