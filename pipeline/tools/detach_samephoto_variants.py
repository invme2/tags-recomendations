#!/usr/bin/env python3
"""detach_samephoto_variants.py — un-assign per-variant images where ALL variants
share the SAME image (quantity / size / spec variants).

retrofit_variant_images.py assigned each variant the photo from _value_photos.
For Color/Style that's great (photo switches). But for quantity/size variants the
source has ONE photo for every value, so all variants got the SAME image. Having
a featuredImage still makes the theme RE-RENDER the gallery on variant select —
even though the image is identical — which causes a layout shift ("Shipping
calculated at checkout" jumps). Detaching the variant<->media link for these
same-image products stops the pointless re-render. Media stays in the gallery.

Idempotent. DRY-RUN by default; --execute applies.
"""
from __future__ import annotations
import argparse, json, os, time
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    tok = token()
    cur, targets = None, []
    while True:
        r = gql(tok, "query($c:String){products(first:120,after:$c){pageInfo{hasNextPage endCursor}"
                     " nodes{id handle variantsCount{count}"
                     " variants(first:100){nodes{id image{id} media(first:3){nodes{id}}}}}}}", {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("ERR", json.dumps(r)[:200]); break
        for n in d["nodes"]:
            if (n.get("variantsCount") or {}).get("count", 0) < 2:
                continue
            vn = (n.get("variants") or {}).get("nodes", [])
            withimg = [v for v in vn if v.get("image")]
            if len(withimg) < 2:
                continue
            uniq = {v["image"]["id"] for v in withimg}
            if len(uniq) <= 1:  # all variants share ONE image -> redundant
                vm = []
                for v in withimg:
                    mids = [m["id"] for m in (v.get("media") or {}).get("nodes", [])]
                    if mids:
                        vm.append({"variantId": v["id"], "mediaIds": mids})
                if vm:
                    targets.append({"id": n["id"], "handle": n["handle"], "vm": vm})
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break
    if args.limit:
        targets = targets[:args.limit]
    print(f"товаров с ОДИНАКОВЫМ фото на всех вариантах (дают дёрганье): {len(targets)} | "
          f"{'EXECUTE' if args.execute else 'DRY-RUN'}\n")
    done = fail = 0
    for t in targets:
        print(f"  ▸ {t['handle']:<46} {len(t['vm'])} вариантов")
        if not args.execute:
            continue
        r = gql(tok, """mutation($pid:ID!,$vm:[ProductVariantDetachMediaInput!]!){
            productVariantDetachMedia(productId:$pid, variantMedia:$vm){userErrors{field message}}}""",
                {"pid": t["id"], "vm": t["vm"]})
        ue = (((r.get("data") or {}).get("productVariantDetachMedia") or {}).get("userErrors")) or []
        if ue:
            fail += 1; print(f"      ! {ue[:1]}")
        else:
            done += 1; print(f"      ✅ отвязано")
        time.sleep(0.3)
    if args.execute:
        print(f"\nГотово: отвязаны вариант-фото у {done} товаров, ошибок {fail}.")
    else:
        print("\nDRY-RUN — запусти с --execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
