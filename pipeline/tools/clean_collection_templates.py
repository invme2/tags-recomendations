#!/usr/bin/env python3
"""clean_collection_templates.py — strip leftover Hyper "Garage" DEMO content from
the live collection templates. The store's collection pages render demo junk on
EVERY collection (furniture "About Garage" rich-text, "Popular Search" with
furniture terms, broken collection sliders to non-existent demo collections,
placeholder "Button label" buttons, a "Saving $30 for Lighting" promo card).

Keeps the real collection page: breadcrumbs -> banner (H1 + description) ->
product-grid (products). Removes every other (demo) section + demo image_card
blocks inside the product grid. Backs up each template to pipeline/.snapshots/.

DRY-RUN by default. --execute applies via the Shopify theme asset API.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
THEME_ID = 153321242802
BASE = f"https://{STORE}/admin/api/2024-10/themes/{THEME_ID}/assets.json"
SNAP = ROOT / "pipeline" / ".snapshots"

# A clean collection page keeps ONLY these section types; everything else in
# these templates is Hyper "Garage" demo content.
KEEP_TYPES = {"breadcrumbs", "main-collection-banner", "main-collection-product-grid"}

TEMPLATES = [
    "templates/collection.json",
    "templates/collection.banner-as-background.json",
    "templates/collection.banner-left.json",
    "templates/collection.banner-top-with-cards.json",
    "templates/collection.banner-without-image.json",
]


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def get_asset(tok, key):
    r = requests.get(BASE, headers={"X-Shopify-Access-Token": tok},
                     params={"asset[key]": key}, timeout=30).json()
    return (r.get("asset") or {}).get("value")


def put_asset(tok, key, value):
    return requests.put(BASE, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                        json={"asset": {"key": key, "value": value}}, timeout=30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    tok = token()
    SNAP.mkdir(parents=True, exist_ok=True)
    print(f"{'EXECUTE' if args.execute else 'DRY-RUN'} — чистка demo из {len(TEMPLATES)} collection-шаблонов\n")
    for t in TEMPLATES:
        v = get_asset(tok, t)
        if not v:
            print(f"  {t}: нет"); continue
        (SNAP / (t.replace("/", "_") + ".bak")).write_text(v, encoding="utf-8")
        d = json.loads(v)
        secs, order = d.get("sections", {}), d.get("order", [])
        removed = []
        for sid in list(secs):
            typ = secs[sid].get("type", "")
            if typ not in KEEP_TYPES:
                removed.append(typ)
                secs.pop(sid)
                if sid in order:
                    order.remove(sid)
            elif typ == "main-collection-product-grid":
                bl, bo = secs[sid].get("blocks", {}), secs[sid].get("block_order", [])
                demo = [bid for bid, b in bl.items() if b.get("type") == "image_card"]
                for bid in demo:
                    bl.pop(bid, None)
                    if bid in bo:
                        bo.remove(bid)
                if demo:
                    removed.append(f"{len(demo)}×image_card(demo-промо)")
        d["sections"], d["order"] = secs, order
        if not args.execute:
            print(f"  [dry] {t}: убрать → {removed}  | остаётся: {[secs[s]['type'] for s in order]}")
            continue
        r = put_asset(tok, t, json.dumps(d, ensure_ascii=False, indent=2))
        ok = r.status_code in (200, 201)
        print(f"  {t}: убрано {removed} → {'✅' if ok else '❌ ' + str(r.status_code) + ' ' + r.text[:120]}")
    print(f"\nБэкапы: {SNAP}/templates_collection*.bak  (откат: PUT обратно)")
    if not args.execute:
        print("DRY-RUN — запусти с --execute чтобы применить.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
