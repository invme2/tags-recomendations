#!/usr/bin/env python3
"""enrich_video_copy.py — add editorial copy (eyebrow / heading / body) to each
custom.videos item so the Oura-style "video + content" rows render text beside
the clip. Copy is templated per preset and filled with the product's short name.

USAGE:
  python pipeline/tools/enrich_video_copy.py --handle <h>
  python pipeline/tools/enrich_video_copy.py --all
"""
from __future__ import annotations
import argparse, json, os, re, sys, io
from pathlib import Path
from typing import Optional
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
API_VERSION = "2024-10"

# preset -> list of (eyebrow, heading, body) variants; repeats cycle the list
COPY = {
    "Hyper Motion": [
        ("DESIGN IN MOTION", "Every detail, up close", "A cinematic look at the {p} — the finish, the glow, and the engineering that sets it apart."),
        ("BUILT TO IMPRESS", "Engineered to stand out", "See the {p} from every angle — premium design, in motion."),
    ],
    "UGC": [
        ("REAL ROUTINES", "Loved in everyday life", "See how real people fold the {p} into their daily self-care."),
        ("REAL PEOPLE", "Honest, unfiltered", "A genuine, phone-shot look at the {p} in action."),
        ("FROM THE COMMUNITY", "Why people keep reaching for it", "Everyday moments with the {p}, captured for real."),
    ],
    "Product Review": [
        ("HONEST REVIEW", "What you actually get", "A straight-talking walkthrough of the {p}, feature by feature."),
    ],
    "Unboxing": [
        ("FIRST LOOK", "The unboxing", "Open the box and meet the {p} for the very first time."),
    ],
    "TV Spot": [
        ("THE STORY", "Made for moments like this", "The {p}, shown the way it was meant to be seen."),
    ],
    "Wild Card": [
        ("A DIFFERENT ANGLE", "Something a little different", "A creative, scroll-stopping take on the {p}."),
    ],
}


def short_name(title: str) -> str:
    t = re.split(r"[|—\-–]", title or "")[0].strip()
    return (t[:52] or "product")


def load_env():
    load_dotenv(ENV_FILE, override=True)


def get_token():
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(f"https://{store}/admin/oauth/access_token",
                      json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
                            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
                            "grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store, token, q, v=None):
    return requests.post(f"https://{store}/admin/api/{API_VERSION}/graphql.json",
                         headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=60).json()


def enrich(store, token, handle) -> bool:
    r = gql(store, token,
            'query($h:String!){productByHandle(handle:$h){id title metafield(namespace:"custom",key:"videos"){value}}}',
            {"h": handle})
    p = r["data"]["productByHandle"]
    if not p:
        print(f"  {handle}: not found"); return False
    mf = (p.get("metafield") or {}).get("value")
    if not mf:
        print(f"  {handle}: no videos"); return False
    payload = json.loads(mf)
    sp = short_name(p["title"])
    seen = {}
    for it in payload.get("items", []):
        preset = it.get("preset", "")
        variants = COPY.get(preset)
        if not variants:
            continue
        n = seen.get(preset, 0)
        eb, h, b = variants[n % len(variants)]
        seen[preset] = n + 1
        it["eyebrow"] = eb
        it["heading"] = h
        it["body"] = b.replace("{p}", sp)
    g = gql(store, token,
            "mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){userErrors{message}}}",
            {"m": [{"ownerId": p["id"], "namespace": "custom", "key": "videos",
                    "type": "json", "value": json.dumps(payload, ensure_ascii=False)}]})
    errs = g["data"]["metafieldsSet"]["userErrors"]
    print(f"  {handle}: enriched {len(payload.get('items', []))} items" + (f" ERRS {errs}" if errs else ""))
    return not errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle"); ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    load_env()
    store, token = get_token()
    if a.handle:
        enrich(store, token, a.handle)
    elif a.all:
        cur = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{handle metafield(namespace:"custom",key:"videos"){value}}}}',
                    {"c": cur})
            pg = r["data"]["products"]
            for n in pg["nodes"]:
                if (n.get("metafield") or {}).get("value"):
                    enrich(store, token, n["handle"])
            if not pg["pageInfo"]["hasNextPage"]:
                break
            cur = pg["pageInfo"]["endCursor"]
    else:
        sys.exit("pass --handle or --all")


if __name__ == "__main__":
    sys.exit(main())
