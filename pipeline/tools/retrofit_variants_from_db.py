#!/usr/bin/env python3
"""retrofit_variants_from_db.py — add missing Shopify variants to live products
from the run-DB scrape data (NO re-scrape).

ROOT BUG: the pipeline scrapes EPROLO variants into scrape_json.variants but the
push reads them from the `variants_json` column — which is never populated (None
for 100% of products). So shopify_create_variants got [] and every product is a
single "Default Title" variant, even when EPROLO had Color/Size/Specification.
54% of Tools&Accessories (430/792) were affected; likely store-wide.

This tool: for each live 1-variant product, finds its scrape_json.variants (by
normalized EPROLO source url), and if it has real options, runs
productOptionsCreate(variantStrategy:CREATE) + prices EVERY variant at the
product's CURRENT price (safe: scrape _value_prices are NOT costs — running them
through the markup would 10x the price). Idempotent: skips products already > 1
variant. DRY-RUN by default.

USAGE
  python pipeline/tools/retrofit_variants_from_db.py            # dry-run
  python pipeline/tools/retrofit_variants_from_db.py --execute [--limit N]
"""
from __future__ import annotations
import argparse, glob, json, os, re, sqlite3, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
MAX_VARIANTS = 100  # Shopify per-product variant ceiling (classic)


def norm(u):
    u = (u or "").strip().lower().rstrip("/")
    u = re.sub(r"\?.*$", "", u)
    u = re.sub(r"(--\d+)-\d+$", r"\1", u)
    return u


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    for a in range(6):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=60).json()
        if r.get("errors") and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in r["errors"]):
            time.sleep(2 + a); continue
        return r
    return r


def clean_opts(variants):
    """scrape_json.variants -> Shopify OptionCreateInput list. Dedup values, drop
    single-value/empty options, cap to 3 options, cap cartesian to MAX_VARIANTS."""
    opts = []
    total = 1
    for v in (variants or [])[:3]:
        name = (v.get("option_name") or "").strip()[:255]
        seen, vals = set(), []
        for x in (v.get("values") or []):
            x = str(x).strip()
            if x and x.lower() not in seen:
                seen.add(x.lower()); vals.append(x[:255])
        if name and len(vals) >= 2:
            opts.append({"name": name, "values": vals})
    # enforce variant ceiling by trimming value lists if needed
    out = []
    for o in opts:
        if total * len(o["values"]) > MAX_VARIANTS:
            keep = max(1, MAX_VARIANTS // total)
            o = {"name": o["name"], "values": o["values"][:keep]}
        if len(o["values"]) >= 2:
            out.append(o); total *= len(o["values"])
    return out


def build_index():
    by_e, by_h = {}, {}
    for db in glob.glob(str(ROOT / "runs" / "*" / ".db" / "pipeline.db")) + glob.glob(str(ROOT / "runs" / "*" / "pipeline.db")):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=8)
            rows = c.execute("SELECT url_handle, eprolo_url, scrape_json FROM products").fetchall()
            c.close()
        except Exception:
            continue
        for h, eu, sj in rows:
            try:
                vs = json.loads(sj or "{}").get("variants") or []
            except Exception:
                vs = []
            opts = clean_opts(vs)
            if not opts:
                continue
            ne = norm(eu)
            if ne and ne not in by_e:
                by_e[ne] = opts
            if h and h not in by_h:
                by_h[h] = opts
    return by_e, by_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    tok = token()
    by_e, by_h = build_index()
    print(f"индекс вариантов из run DB: by_eprolo={len(by_e)} by_handle={len(by_h)}")

    # live products with exactly 1 variant
    cur, targets = None, []
    while True:
        r = gql(tok, """query($c:String){products(first:200,after:$c){pageInfo{hasNextPage endCursor}
          nodes{id handle variantsCount{count} variants(first:1){nodes{price}}
            src:metafield(namespace:"custom",key:"source"){value}}}}""", {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("ERR", json.dumps(r)[:200]); break
        for n in d["nodes"]:
            if (n.get("variantsCount") or {}).get("count", 0) != 1:
                continue
            su = ""
            try:
                su = norm(json.loads((n.get("src") or {}).get("value") or "{}").get("url", ""))
            except Exception:
                pass
            opts = by_e.get(su) or by_h.get(n["handle"])
            if opts:
                price = (n.get("variants") or {}).get("nodes", [{}])[0].get("price", "0")
                targets.append({"id": n["id"], "handle": n["handle"], "opts": opts, "price": price})
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break
    if args.limit:
        targets = targets[:args.limit]
    print(f"товаров без вариантов, но с вариантами в скрейпе: {len(targets)} | "
          f"{'EXECUTE' if args.execute else 'DRY-RUN'}\n")

    done = fail = 0
    for t in targets:
        summary = ", ".join(f"{o['name']}({len(o['values'])})" for o in t["opts"])
        print(f"  ▸ {t['handle']:<46} {summary}")
        if not args.execute:
            continue
        opt_inputs = [{"name": o["name"], "values": [{"name": x} for x in o["values"]]} for o in t["opts"]]
        r = gql(tok, """mutation($pid:ID!,$opts:[OptionCreateInput!]!){
            productOptionsCreate(productId:$pid, options:$opts, variantStrategy:CREATE){
                product{variantsCount{count}} userErrors{field message}}}""",
                {"pid": t["id"], "opts": opt_inputs})
        oc = (r.get("data") or {}).get("productOptionsCreate") or {}
        ue = oc.get("userErrors") or []
        if ue:
            fail += 1; print(f"      ! {ue[:2]}"); continue
        time.sleep(1.0)
        # price every variant at the product's current price (safe)
        rv = gql(tok, "query($id:ID!){product(id:$id){variants(first:100){nodes{id}}}}", {"id": t["id"]})
        vn = (((rv.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes", [])
        upd = [{"id": v["id"], "price": str(t["price"])} for v in vn]
        for i in range(0, len(upd), 50):
            gql(tok, """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
                productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{message}}}""",
                {"pid": t["id"], "v": upd[i:i+50]})
            time.sleep(0.3)
        done += 1
        print(f"      ✅ {len(vn)} вариантов @ ${t['price']}")
        time.sleep(0.4)
    if args.execute:
        print(f"\nГотово: вариантов восстановлено у {done} товаров, ошибок {fail}.")
    else:
        print("\nDRY-RUN — запусти с --execute чтобы применить.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
