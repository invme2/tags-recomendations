#!/usr/bin/env python3
"""fix_broken_metafield_images.py — repair metafield image_urls that 404 after a
carousel media REPLACE (the Designer reused old gallery images inside metafields
like features/story; replacing the carousel deleted those files -> broken).

For each target product: HEAD-check every image_url inside every custom.* JSON
metafield. Any URL that 404s is re-pointed to one of the product's CURRENT media
images (round-robin), then metafieldsSet patches the JSON back.

Targets: handles from the photo-intake blacklist (default) or --handle X (repeat).
Default = DRY RUN. Pass --execute to write.
"""
from __future__ import annotations
import argparse, itertools, json, os, re, sys
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
BLACKLIST = ROOT / "pipeline" / "runs" / "photo_intake" / "_processed.json"
URL_RE = re.compile(r'https://\S+?\.(?:jpg|jpeg|png|webp)')

CUSTOM_KEYS = ["hero", "story", "features", "stats", "clinical_evidence", "timeline",
               "lifestyle_gallery", "ingredients", "compare", "app_showcase",
               "room_placement", "video_demo", "brand_story", "gift_options",
               "whats_included", "care", "trust", "how_to", "protocol", "safety"]


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                       "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=60).json()


def alive(url, cache):
    if url in cache:
        return cache[url]
    try:
        ok = requests.head(url, timeout=10, allow_redirects=True).status_code < 400
    except Exception:
        ok = False
    cache[url] = ok
    return ok


def fix_product(tok, handle, execute, http_cache):
    mf = " ".join(f'{k}:metafield(namespace:"custom",key:"{k}"){{value}}' for k in CUSTOM_KEYS)
    r = gql(tok, 'query($q:String!){products(first:1,query:$q){nodes{id title '
            'images(first:30){nodes{url}}' + mf + '}}}', {"q": f"handle:{handle}"})
    nodes = r.get("data", {}).get("products", {}).get("nodes") or []
    if not nodes:
        print(f"  ❓ {handle}: товар не найден"); return 0
    p = nodes[0]
    media = [im["url"] for im in (p.get("images") or {}).get("nodes", [])]
    if not media:
        print(f"  ⚠ {handle}: нет media — пропуск"); return 0
    cyc = itertools.cycle(media)

    patches = []
    fixed = 0
    for k in CUSTOM_KEYS:
        v = (p.get(k) or {}).get("value")
        if not v:
            continue
        new_v = v
        for u in set(URL_RE.findall(v)):
            if not alive(u, http_cache):
                new_v = new_v.replace(u, next(cyc))
                fixed += 1
        if new_v != v:
            patches.append({"ownerId": p["id"], "namespace": "custom", "key": k,
                            "type": "json", "value": new_v})
    if not patches:
        print(f"  ✓ {handle}: битых нет")
        return 0
    print(f"  {'[ИСПРАВЛЮ]' if execute else '[dry]'} {handle}: {fixed} битых в {len(patches)} метафилдах")
    if execute:
        d = gql(tok, "mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m)"
                "{userErrors{message}}}", {"m": patches})
        ue = (d.get("data", {}).get("metafieldsSet", {}) or {}).get("userErrors", [])
        if ue:
            print(f"     ! {ue}")
    return fixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--handle", action="append", default=[], help="repeat for each handle")
    args = ap.parse_args()
    tok = token()
    handles = args.handle
    if not handles and BLACKLIST.exists():
        bl = json.loads(BLACKLIST.read_text(encoding="utf-8"))
        handles = sorted({m.get("handle") for m in bl.values() if m.get("handle")})
    if not handles:
        print("Нет целей (ни --handle, ни блэклист).")
        return 0
    print(f"Целей: {len(handles)} | режим: {'EXECUTE' if args.execute else 'DRY-RUN'}\n")
    cache = {}
    total = 0
    for h in handles:
        total += fix_product(tok, h, args.execute, cache)
    print(f"\nИтого исправлено URL: {total}" + ("" if args.execute else "  (dry-run, ничего не записано)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
