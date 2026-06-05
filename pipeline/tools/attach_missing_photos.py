#!/usr/bin/env python3
"""attach_missing_photos.py — re-attach product media to products that ended up
with ZERO images (failed media step during their run). Sources image URLs from
the recovery plan (photo_recovery_plan.json, built by matching each imageless
product's EPROLO source url to its run-DB scrape gallery).

DRY-RUN by default. --execute attaches via productCreateMedia.
  python pipeline/tools/attach_missing_photos.py
  python pipeline/tools/attach_missing_photos.py --execute [--limit N] [--max-img 8]
"""
from __future__ import annotations
import argparse, json, os, re, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
PLAN = ROOT / "pipeline" / "runs" / "_logs" / "photo_recovery_plan.json"


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


def fullres(u):
    # strip OSS thumbnail processing + query params -> original full-size image
    return re.sub(r'\?.*$', '', u or '')


MUT = """mutation($id:ID!,$media:[CreateMediaInput!]!){
  productCreateMedia(productId:$id, media:$media){
    media{... on MediaImage{id}}
    mediaUserErrors{field message}
  }
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-img", type=int, default=8)
    args = ap.parse_args()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if args.limit:
        plan = plan[:args.limit]
    tok = token()
    print(f"Товаров к восстановлению фото: {len(plan)} | {'EXECUTE' if args.execute else 'DRY-RUN'}\n")
    done = imgs = fail = 0
    for p in plan:
        urls = []
        seen = set()
        for u in p["urls"]:
            fu = fullres(u)
            if fu and fu not in seen and fu.startswith("http"):
                seen.add(fu); urls.append(fu)
            if len(urls) >= args.max_img:
                break
        if not urls:
            print(f"  ✗ {p['handle']}: нет валидных url"); continue
        # idempotency: skip products that already have media (avoids duplicate galleries on re-run)
        chk = gql(tok, 'query($id:ID!){product(id:$id){mediaCount{count}}}', {"id": p["id"]})
        cur_n = (((chk.get("data") or {}).get("product") or {}).get("mediaCount") or {}).get("count", 0)
        if cur_n and cur_n > 0:
            print(f"  ⏭  {p['handle']:<46} уже {cur_n} медиа — пропуск")
            continue
        print(f"  ▸ {p['handle']:<46} +{len(urls)} фото")
        if args.execute:
            media = [{"originalSource": u, "mediaContentType": "IMAGE",
                      "alt": p["handle"].replace("-", " ")} for u in urls]
            r = gql(tok, MUT, {"id": p["id"], "media": media})
            ue = (((r.get("data") or {}).get("productCreateMedia") or {}).get("mediaUserErrors")) or []
            if ue or not (r.get("data") or {}).get("productCreateMedia"):
                fail += 1
                print(f"      ! {ue or json.dumps(r)[:120]}")
            else:
                done += 1; imgs += len(urls)
                print(f"      ✅ прикреплено")
            time.sleep(0.6)
    if args.execute:
        print(f"\nГотово: восстановлено {done} товаров ({imgs} фото), ошибок {fail}.")
        print("⚠ Shopify обрабатывает медиа асинхронно — фото появятся через минуту. Перепроверь скриптом-аудитом.")
    else:
        print("\nDRY-RUN — запусти с --execute чтобы прикрепить.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
