#!/usr/bin/env python3
"""audit_fix_prices.py — find and fix wrong / $0 product prices store-wide.

Some products ended up at $0 (price never set when their pipeline run failed)
or mis-priced. Correct price = calc_price(scraped cost) exactly as the pipeline
intends: cost x RETAIL_MARKUP(10), psychological .90 ending, min $7.90; compare-at
= cost x 15.

For each live product: read its scraped cost from the run DBs (by EPROLO source
url), compute the correct price, and flag/fix where the live price is $0 or
deviates a lot. Sets EVERY variant to the correct price (+ compare-at).

DRY-RUN by default. --execute applies. --dev N% sets the "wrong" threshold.
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
MARKUP = float(os.environ.get("RETAIL_MARKUP", "10.0"))
CMP_MARKUP = float(os.environ.get("COMPARE_AT_MARKUP", "15.0"))


def calc_price(cost):
    raw = cost * MARKUP
    if raw < 10: price = round(raw) - 0.10
    elif raw < 30: price = (round(raw / 5) * 5) - 0.10
    else: price = (round(raw / 10) * 10) - 0.10
    return max(7.90, round(price, 2))


def calc_compare(cost):
    raw = cost * CMP_MARKUP
    if raw < 20: return float(max(15, round(raw / 5) * 5))
    return float(round(raw / 10) * 10)


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


def cost_index():
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
                cp = float(json.loads(sj or "{}").get("cost_price") or 0)
            except Exception:
                cp = 0
            if cp <= 0:
                continue
            ne = norm(eu)
            if ne and ne not in by_e:
                by_e[ne] = cp
            if h and h not in by_h:
                by_h[h] = cp
    return by_e, by_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--dev", type=float, default=0.40, help="flag as WRONG if |live-correct|/correct > this")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    tok = token()
    by_e, by_h = cost_index()
    print(f"индекс costs из run DB: by_eprolo={len(by_e)} by_handle={len(by_h)} | MARKUP={MARKUP}\n")

    cur = None
    zero, wrong, nocost, ok = [], [], [], 0
    while True:
        r = gql(tok, """query($c:String){products(first:150,after:$c){pageInfo{hasNextPage endCursor}
          nodes{id handle variants(first:50){nodes{id price}}
            src:metafield(namespace:"custom",key:"source"){value}}}}""", {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("ERR", json.dumps(r)[:200]); break
        for n in d["nodes"]:
            vn = (n.get("variants") or {}).get("nodes", [])
            if not vn:
                continue
            live = min(float(v["price"]) for v in vn)
            su = ""
            try:
                su = norm(json.loads((n.get("src") or {}).get("value") or "{}").get("url", ""))
            except Exception:
                pass
            cost = by_e.get(su) or by_h.get(n["handle"])
            rec = {"id": n["id"], "handle": n["handle"], "live": live,
                   "cost": cost, "correct": calc_price(cost) if cost else None,
                   "vids": [v["id"] for v in vn]}
            if cost is None:
                if live == 0:
                    nocost.append(rec)
                else:
                    ok += 1
                continue
            corr = rec["correct"]
            if live == 0:
                zero.append(rec)
            elif abs(live - corr) / max(corr, 1) > args.dev:
                wrong.append(rec)
            else:
                ok += 1
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break

    fixable = zero + wrong
    if args.limit:
        fixable = fixable[:args.limit]
    print(f"АУДИТ: ✅ корректных={ok} | 🔴 $0(с costs)={len(zero)} | "
          f"🟠 неверных(>{int(args.dev*100)}%)={len(wrong)} | ⚠ $0 без cost в DB={len(nocost)}")
    print("\nпримеры $0 (исправимы):")
    for r in zero[:6]:
        print(f"   {r['handle']:<42} live=$0 → ${r['correct']} (cost ${r['cost']:.2f})")
    print("примеры неверных:")
    for r in wrong[:8]:
        print(f"   {r['handle']:<42} live=${r['live']} → ${r['correct']} (cost ${r['cost']:.2f})")
    if nocost:
        print(f"\n⚠ {len(nocost)} товаров по $0 БЕЗ cost в run DB (не определить авто): {[r['handle'] for r in nocost[:6]]}")

    if not args.execute:
        print("\nDRY-RUN — запусти с --execute чтобы исправить (zero+wrong).")
        return 0

    print(f"\nИсправляю {len(fixable)} товаров…")
    done = 0
    for r in fixable:
        corr = r["correct"]; cmp_ = calc_compare(r["cost"])
        upd = [{"id": vid, "price": str(corr), "compareAtPrice": str(cmp_)} for vid in r["vids"]]
        ok2 = True
        for i in range(0, len(upd), 50):
            rr = gql(tok, """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
                productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{message}}}""",
                     {"pid": r["id"], "v": upd[i:i+50]})
            ue = (((rr.get("data") or {}).get("productVariantsBulkUpdate") or {}).get("userErrors")) or []
            if ue:
                ok2 = False; print(f"   ! {r['handle']}: {ue[:1]}")
            time.sleep(0.25)
        if ok2:
            done += 1
        time.sleep(0.2)
    print(f"\nИсправлено: {done}/{len(fixable)}. (Осталось вручную: {len(nocost)} без cost.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
