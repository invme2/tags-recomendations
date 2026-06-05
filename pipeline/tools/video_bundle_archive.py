#!/usr/bin/env python3
"""video_bundle_archive.py — organize each product's generated video bundle
into a per-product folder so the operator can improve a clip and have it
re-uploaded later (see reupload_videos.py).

LAYOUT (per product, under pipeline/runs/video_bundles/<handle>/):
  manifest.json        — gid, handle, title, ordered items
                         [{index, preset, slot_eyebrow, url, thumbnail_url, video_id}]
  current/<i>_<preset>.mp4   — the LIVE video currently in the metafield
                               (downloaded so you have the source to edit)
  improved/            — DROP ZONE. Put an improved clip here named by its
                         index: `0.mp4` (or `0_anything.mp4`). reupload_videos.py
                         picks it up, uploads to Shopify Files, and swaps the
                         metafield item at that index. (You can't rename CDN
                         files, so we key by the leading index number.)
  HOW_TO.txt           — the same instructions, in the folder.

The slot eyebrows are the on-page labels for each position (fixed by the
product-page master section): index 0..5 →
  See it in action / Watch it work / Real routine / See the difference /
  Closer look / Why people love it

USAGE:
  python pipeline/tools/video_bundle_archive.py --handle 6-in-1-led-microcurrent-skin-rejuvenation-beauty-device
  python pipeline/tools/video_bundle_archive.py --all          # every product with custom.videos
  python pipeline/tools/video_bundle_archive.py --all --no-download   # manifest only, skip mp4 download
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
BUNDLE_DIR = REPO_ROOT / "pipeline" / "runs" / "video_bundles"
API_VERSION = "2024-10"

SLOT_EYEBROWS = [
    "See it in action", "Watch it work", "Real routine",
    "See the difference", "Closer look", "Why people love it",
    "Real results", "The verdict",
]

HOW_TO = """HOW TO IMPROVE A VIDEO IN THIS BUNDLE
=====================================
1. Look in  current/  — those are the videos live on the product page now.
   File name = <index>_<preset>.mp4  (the leading number is the slot index).

2. Improve / re-edit any clip however you like (trim, re-render, replace).

3. Save your improved clip into the  improved/  folder, named by the SAME
   leading index number, e.g.:
       improved/0.mp4      (replaces slot 0 = "See it in action")
       improved/3.mp4      (replaces slot 3 = "See the difference")
   The rest of the filename doesn't matter — only the leading number is read.

4. Tell Claude "перезалей видео" (or run):
       python pipeline/tools/reupload_videos.py --handle <this-folder-name>
   It uploads your improved clip to Shopify Files and swaps it into the
   product's video metafield at that slot. The page updates automatically.

Nothing here touches the live store until you run reupload_videos.py.
"""


def load_env() -> None:
    load_dotenv(ENV_FILE, override=True)


def get_token() -> tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"},
        timeout=15,
    )
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers,
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    return r.json()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "clip"


def products_with_videos(store: str, token: str):
    cursor = None
    while True:
        r = gql(store, token,
                'query($c:String){products(first:100,after:$c){pageInfo{hasNextPage endCursor} '
                'nodes{id handle title metafield(namespace:"custom",key:"videos"){value}}}}',
                {"c": cursor})
        pg = r["data"]["products"]
        for n in pg["nodes"]:
            mf = (n.get("metafield") or {}).get("value")
            if mf:
                try:
                    items = json.loads(mf).get("items") or []
                except Exception:
                    items = []
                if items:
                    yield n["id"], n["handle"], n["title"], items
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]


def archive_one(store, token, gid, handle, title, items, download: bool) -> None:
    folder = BUNDLE_DIR / handle
    (folder / "current").mkdir(parents=True, exist_ok=True)
    (folder / "improved").mkdir(parents=True, exist_ok=True)

    manifest = {"gid": gid, "handle": handle, "title": title, "items": []}
    for i, it in enumerate(items):
        preset = it.get("preset") or it.get("title") or f"video{i}"
        entry = {
            "index": i,
            "preset": preset,
            "slot_eyebrow": SLOT_EYEBROWS[i] if i < len(SLOT_EYEBROWS) else "",
            "url": it.get("url", ""),
            "thumbnail_url": it.get("thumbnail_url", ""),
            "video_id": it.get("video_id", ""),
        }
        manifest["items"].append(entry)
        if download and entry["url"]:
            dest = folder / "current" / f"{i}_{slug(preset)}.mp4"
            if not dest.exists():
                try:
                    resp = requests.get(entry["url"], timeout=180)
                    resp.raise_for_status()
                    dest.write_bytes(resp.content)
                    print(f"    downloaded {dest.name} ({len(resp.content)/1024/1024:.1f} MB)")
                except Exception as e:
                    print(f"    DL FAIL {dest.name}: {str(e)[:120]}")

    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "HOW_TO.txt").write_text(HOW_TO, encoding="utf-8")
    print(f"  archived {handle}: {len(items)} videos → {folder}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--handle", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-download", action="store_true", help="manifest only, skip mp4 download")
    args = ap.parse_args()
    if not args.handle and not args.all:
        sys.exit("pass --handle <h> or --all")

    load_env()
    store, token = get_token()
    download = not args.no_download

    if args.handle:
        r = gql(store, token,
                'query($h:String!){productByHandle(handle:$h){id handle title '
                'metafield(namespace:"custom",key:"videos"){value}}}',
                {"h": args.handle})
        p = r["data"]["productByHandle"]
        if not p:
            sys.exit(f"product not found: {args.handle}")
        mf = (p.get("metafield") or {}).get("value")
        items = json.loads(mf).get("items") if mf else []
        if not items:
            sys.exit(f"{args.handle} has no custom.videos items")
        archive_one(store, token, p["id"], p["handle"], p["title"], items, download)
    else:
        n = 0
        for gid, handle, title, items in products_with_videos(store, token):
            archive_one(store, token, gid, handle, title, items, download)
            n += 1
        print(f"\nArchived {n} product bundle(s) → {BUNDLE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
