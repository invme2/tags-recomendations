#!/usr/bin/env python3
"""retrofit_variant_images.py — attach per-variant featured images so the photo
switches when a customer picks a Color/Style option.

The variant retrofit (retrofit_variants_from_db.py) created options + prices but
NOT per-variant images, so selecting Gold vs Silver didn't change the photo. The
EPROLO scrape stored per-value photos in scrape_json.variants[].`_value_photos`
({value: url}) for 54% of multi-variant products. This tool, for each live
product: uploads each value's photo as product media and assigns it to the
matching variant (productVariantsBulkUpdate mediaId).

Idempotent: skips products whose variants already all have images.
DRY-RUN by default. --execute applies.
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


def norm(u):
    u = (u or "").strip().lower().rstrip("/"); u = re.sub(r"\?.*$", "", u)
    return re.sub(r"(--\d+)-\d+$", r"\1", u)


def fullres(u):
    return re.sub(r"\?.*$", "", u or "")


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


def vphoto_index():
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
            ph = {}
            for v in vs:
                for k, u in (v.get("_value_photos") or {}).items():
                    if k and u:
                        ph[k.strip().lower()] = fullres(u)
            if not ph:
                continue
            ne = norm(eu)
            if ne and ne not in by_e:
                by_e[ne] = ph
            if h and h not in by_h:
                by_h[h] = ph
    return by_e, by_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    tok = token()
    by_e, by_h = vphoto_index()
    print(f"индекс per-value фото из run DB: by_eprolo={len(by_e)} by_handle={len(by_h)}")

    cur, targets = None, []
    while True:
        r = gql(tok, """query($c:String){products(first:120,after:$c){pageInfo{hasNextPage endCursor}
          nodes{id handle variantsCount{count}
            variants(first:100){nodes{id selectedOptions{value} image{id}}}
            src:metafield(namespace:"custom",key:"source"){value}}}}""", {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("ERR", json.dumps(r)[:200]); break
        for n in d["nodes"]:
            if (n.get("variantsCount") or {}).get("count", 0) < 2:
                continue
            vn = (n.get("variants") or {}).get("nodes", [])
            if vn and all(v.get("image") for v in vn):
                continue  # already done
            su = ""
            try:
                su = norm(json.loads((n.get("src") or {}).get("value") or "{}").get("url", ""))
            except Exception:
                pass
            ph = by_e.get(su) or by_h.get(n["handle"])
            if not ph:
                continue
            targets.append({"id": n["id"], "handle": n["handle"], "vn": vn, "ph": ph})
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break
    if args.limit:
        targets = targets[:args.limit]
    print(f"товаров с вариантами без фото, но с per-value фото в скрейпе: {len(targets)} | "
          f"{'EXECUTE' if args.execute else 'DRY-RUN'}\n")

    done = fail = 0
    for t in targets:
        # which option values (present on variants, missing image) have a photo
        need = {}
        for v in t["vn"]:
            if v.get("image"):
                continue
            for so in v["selectedOptions"]:
                val = so["value"].strip().lower()
                if val in t["ph"]:
                    need[val] = t["ph"][val]
                    break
        if not need:
            continue
        print(f"  ▸ {t['handle']:<46} {len(need)} фото-вариантов")
        if not args.execute:
            continue
        # 1) create media for each needed value (one batched call)
        media_in = [{"originalSource": u, "mediaContentType": "IMAGE", "alt": f"{t['handle']} {val}"}
                    for val, u in need.items()]
        rc = gql(tok, """mutation($id:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$id,media:$m){
            media{...on MediaImage{id}} mediaUserErrors{message}}}""", {"id": t["id"], "m": media_in})
        mids = [m["id"] for m in (((rc.get("data") or {}).get("productCreateMedia") or {}).get("media") or []) if m.get("id")]
        if len(mids) != len(need):
            fail += 1
            print(f"      ! media create {len(mids)}/{len(need)}: {(((rc.get('data') or {}).get('productCreateMedia') or {}).get('mediaUserErrors'))}")
            continue
        val_to_mid = dict(zip(need.keys(), mids))
        time.sleep(6)  # let Shopify process the new media before assigning
        # 2) assign mediaId to each matching variant lacking an image
        upd = []
        for v in t["vn"]:
            if v.get("image"):
                continue
            for so in v["selectedOptions"]:
                mid = val_to_mid.get(so["value"].strip().lower())
                if mid:
                    upd.append({"id": v["id"], "mediaId": mid}); break
        ok = True
        for i in range(0, len(upd), 50):
            rr = gql(tok, """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
                productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{message}}}""",
                     {"pid": t["id"], "v": upd[i:i+50]})
            ue = (((rr.get("data") or {}).get("productVariantsBulkUpdate") or {}).get("userErrors")) or []
            if ue:
                ok = False; print(f"      ! assign: {ue[:1]}")
            time.sleep(0.3)
        if ok:
            done += 1; print(f"      ✅ {len(upd)} вариантов получили фото")
        time.sleep(0.4)
    if args.execute:
        print(f"\nГотово: фото вариантам у {done} товаров, ошибок {fail}.")
    else:
        print("\nDRY-RUN — запусти с --execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
