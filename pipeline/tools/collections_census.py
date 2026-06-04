#!/usr/bin/env python3
"""collections_census.py — live audit of (1) automatic-link readiness and
(2) product distribution across collections. Read-only.

Reports:
  A. Collections: total, published-to-OnlineStore, smart vs manual,
     parent_category coverage (blank parent => absent from homepage hubs),
     fill buckets (0 / 1-4 / 5-19 / 20+ products).
  B. Parent-hub map: how many collections roll up under each parent.
  C. Products: total, and an orphan scan (products in ZERO collections) over
     a bounded sample, plus full-catalog cluster-tag coverage from the pipeline DBs.
"""
from __future__ import annotations
import os, sys, time, json, sqlite3
from collections import Counter, defaultdict
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None, retries=5):
    for a in range(retries):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                         "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=60).json()
        if r.get("errors") and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in r["errors"]):
            time.sleep(2 + a); continue
        return r
    return r


def census_collections(tok):
    q = """query($c:String){collections(first:200,after:$c){pageInfo{hasNextPage endCursor}
      nodes{title handle productsCount{count} ruleSet{appliedDisjunctively rules{column}}
        pc:metafield(namespace:"custom",key:"parent_category"){value}}}}"""
    nodes = []
    cur = None
    while True:
        r = gql(tok, q, {"c": cur})
        d = (r.get("data") or {}).get("collections")
        if not d:
            print("ERR collections:", json.dumps(r)[:400]); break
        nodes.extend(d["nodes"])
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.3)
        else:
            break
    return nodes


def main():
    tok = token()
    cols = census_collections(tok)
    n = len(cols)
    smart = sum(1 for c in cols if c.get("ruleSet"))
    manual = n - smart
    have_pc = sum(1 for c in cols if (c.get("pc") or {}).get("value", "").strip())
    blank_pc = n - have_pc

    def cnt(c):
        return (c.get("productsCount") or {}).get("count", 0) or 0
    empty = sum(1 for c in cols if cnt(c) == 0)
    thin = sum(1 for c in cols if 1 <= cnt(c) <= 4)
    mid = sum(1 for c in cols if 5 <= cnt(c) <= 19)
    big = sum(1 for c in cols if cnt(c) >= 20)
    fills = sorted((cnt(c) for c in cols))
    median = fills[len(fills)//2] if fills else 0
    total_memberships = sum(fills)

    parents = Counter()
    blank_names = []
    for c in cols:
        pv = (c.get("pc") or {}).get("value", "").strip()
        if pv:
            parents[pv] += 1
        else:
            blank_names.append(c["title"])

    print("=" * 64)
    print("A. КОЛЛЕКЦИИ (живой Shopify)")
    print("=" * 64)
    print(f"  всего:                 {n}")
    print(f"  smart (по тегу):       {smart}")
    print(f"  manual:                {manual}")
    print(f"  с parent_category:     {have_pc}  ✅ попадают в хабы на главной")
    print(f"  БЕЗ parent_category:   {blank_pc}  {'⚠ НЕ в хабах главной (только в footer-Other)' if blank_pc else '✅'}")
    print(f"\n  заполнение: пусто={empty}  тонкие(1-4)={thin}  средние(5-19)={mid}  полные(20+)={big}")
    print(f"  медиана товаров/коллекция: {median} | макс: {fills[-1] if fills else 0} | сумма вхождений: {total_memberships}")

    print(f"\n  ХАБ-РАСПРЕДЕЛЕНИЕ (parent → сколько коллекций), {len(parents)} хабов:")
    for p, c in parents.most_common():
        print(f"     {p:<26} {c}")
    if blank_names:
        print(f"\n  ⚠ {len(blank_names)} коллекций БЕЗ parent_category (примеры): {blank_names[:8]}")

    # C. product distribution from pipeline DBs (cluster-tag coverage = assignable to a smart collection)
    print("\n" + "=" * 64)
    print("B. ТОВАРЫ — покрытие cluster-тегами (из pipeline DB, весь каталог)")
    print("=" * 64)
    runs = ROOT / "runs"
    smart_rule_clusters = set()  # which cluster handles actually have a smart collection
    for c in cols:
        # smart collection handle usually == cluster handle; capture handle
        smart_rule_clusters.add(c["handle"])
    tot_prod = 0; with_cluster = 0; no_cluster = 0; primary_set = 0
    per_db = []
    for db in sorted(runs.glob("*/pipeline.db")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
            rows = con.execute("SELECT product_tags, primary_collection FROM products WHERE status='done'").fetchall()
            con.close()
        except Exception:
            continue
        if not rows:
            continue
        dc = wc = 0
        for tags, primc in rows:
            tot_prod += 1; dc += 1
            t = tags or ""
            if "cluster:" in t:
                with_cluster += 1; wc += 1
            else:
                no_cluster += 1
            if (primc or "").strip():
                primary_set += 1
        per_db.append((db.parent.name, dc, wc))
    print(f"  всего done-товаров:        {tot_prod}")
    if tot_prod:
        print(f"  с cluster:-тегом:          {with_cluster}  ({100*with_cluster//tot_prod}%) — назначаемы в smart-коллекцию")
        print(f"  БЕЗ cluster:-тега:         {no_cluster}  ({100*no_cluster//tot_prod}%) — рискуют остаться вне коллекций")
        print(f"  с primary_collection:      {primary_set}  ({100*primary_set//tot_prod}%)")
    for name, dc, wc in per_db:
        print(f"     {name:<40} done={dc:<5} cluster-tagged={wc}")

    # bounded live orphan scan: sample products, check collection membership
    print("\n" + "=" * 64)
    print("C. ОРФАНЫ — выборочная проверка членства в Shopify (sample)")
    print("=" * 64)
    q = """query($c:String){products(first:100,after:$c,query:"status:active"){pageInfo{hasNextPage endCursor}
      nodes{handle collections(first:1){nodes{id}}}}}"""
    cur = None; scanned = 0; orphan = 0; orphan_ex = []
    PAGES = 6  # ~600 products sample
    for _ in range(PAGES):
        r = gql(tok, q, {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("  (orphan scan недоступен:", json.dumps(r)[:160], ")"); break
        for p in d["nodes"]:
            scanned += 1
            if not (p.get("collections") or {}).get("nodes"):
                orphan += 1
                if len(orphan_ex) < 8:
                    orphan_ex.append(p["handle"])
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.4)
        else:
            break
    if scanned:
        print(f"  проверено товаров:   {scanned}")
        print(f"  орфанов (0 коллекций): {orphan}  ({100*orphan//scanned}%)")
        if orphan_ex:
            print(f"  примеры орфанов: {orphan_ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
