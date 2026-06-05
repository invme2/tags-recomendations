#!/usr/bin/env python3
"""place_orphan_photos.py — put orphaned inline-extra uploads (in Shopify Files
but referenced by no metafield) into the product's lifestyle_gallery image slots.

For each target product (handles from the photo-intake blacklist, or --handle X):
  1. find Files named "<handle>-inline-extra*";
  2. fill the empty image_url slots of custom.lifestyle_gallery.items (the
     snippet skips items with blank image_url, so partial fill renders clean);
  3. metafieldsSet the patched gallery.
Default = DRY RUN. Pass --execute to write.
"""
from __future__ import annotations
import argparse, json, os, sys
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
BLACKLIST = ROOT / "pipeline" / "runs" / "photo_intake" / "_processed.json"


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                       "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=60).json()


def orphan_files(tok, handle):
    r = gql(tok, 'query($q:String!){files(first:20,query:$q){nodes{... on MediaImage{'
            'image{url}}}}}', {"q": f"{handle}-inline-extra"})
    urls = []
    for n in r.get("data", {}).get("files", {}).get("nodes", []):
        u = (n.get("image") or {}).get("url")
        if u and f"{handle}-inline-extra" in u:
            urls.append(u)
    return sorted(urls)


def place(tok, handle, execute):
    r = gql(tok, 'query($q:String!){products(first:1,query:$q){nodes{id '
            'lifestyle_gallery:metafield(namespace:"custom",key:"lifestyle_gallery"){value}}}}',
            {"q": f"handle:{handle}"})
    nodes = r.get("data", {}).get("products", {}).get("nodes") or []
    if not nodes:
        print(f"  ❓ {handle}: товар не найден"); return 0
    p = nodes[0]
    orphans = orphan_files(tok, handle)
    if not orphans:
        print(f"  ✓ {handle}: осиротевших inline-extra нет"); return 0
    lg_raw = (p.get("lifestyle_gallery") or {}).get("value")
    if not lg_raw:
        print(f"  ⚠ {handle}: нет lifestyle_gallery — пропуск ({len(orphans)} осиротевших)")
        return 0
    lg = json.loads(lg_raw)
    items = lg.get("items") or []
    # fill empty image_url slots in order
    oi = 0
    filled = 0
    for it in items:
        if oi >= len(orphans):
            break
        if not (it.get("image_url") or "").strip():
            it["image_url"] = orphans[oi]
            oi += 1
            filled += 1
    # if more orphans than empty slots, append new items
    while oi < len(orphans):
        items.append({"image_url": orphans[oi], "caption": "", "credit": ""})
        oi += 1
        filled += 1
    lg["items"] = items
    print(f"  {'[ВСТАВЛЮ]' if execute else '[dry]'} {handle}: {filled} фото → lifestyle_gallery "
          f"({len(orphans)} осиротевших)")
    if execute:
        d = gql(tok, "mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m)"
                "{userErrors{message}}}",
                {"m": [{"ownerId": p["id"], "namespace": "custom", "key": "lifestyle_gallery",
                        "type": "json", "value": json.dumps(lg, ensure_ascii=False)}]})
        ue = (d.get("data", {}).get("metafieldsSet", {}) or {}).get("userErrors", [])
        if ue:
            print(f"     ! {ue}")
    return filled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--handle", action="append", default=[])
    args = ap.parse_args()
    tok = token()
    handles = args.handle
    if not handles and BLACKLIST.exists():
        bl = json.loads(BLACKLIST.read_text(encoding="utf-8"))
        handles = sorted({m.get("handle") for m in bl.values() if m.get("handle")})
    print(f"Целей: {len(handles)} | {'EXECUTE' if args.execute else 'DRY-RUN'}\n")
    tot = 0
    for h in handles:
        tot += place(tok, h, args.execute)
    print(f"\nИтого вставлено фото: {tot}" + ("" if args.execute else "  (dry-run)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
