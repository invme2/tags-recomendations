#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_vibe_home.py — push the Vibe homepage to a target theme:
uploads vibe.css + vibe-icon.liquid + vibe-home.liquid and writes templates/index.json
to render ONLY the vibe-home section wired to real collections.
Usage: python apply_vibe_home.py <theme_id>
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_edit as T
import requests

ROOT = Path(__file__).resolve().parents[1] / "theme_assets"
ASSETS = [
    ("assets/vibe.css", ROOT / "assets" / "vibe.css"),
    ("snippets/vibe-icon.liquid", ROOT / "snippets" / "vibe-icon.liquid"),
    ("sections/vibe-home.liquid", ROOT / "sections" / "vibe-home.liquid"),
]

INDEX = {
    "sections": {
        "vibe": {
            "type": "vibe-home",
            "blocks": {
                "r1": {"type": "row", "settings": {"collection": "bestsellers", "title": "Curated for you", "subtitle": "Learned from everything you’ve loved"}},
                "r2": {"type": "row", "settings": {"collection": "massage", "title": "🛰 Flash drops", "subtitle": "Live deals — gone when the timer hits zero"}},
                "r3": {"type": "row", "settings": {"collection": "skincare", "title": "Trending in your city", "subtitle": "Popular right now"}},
            },
            "block_order": ["r1", "r2", "r3"],
            "settings": {"featured_collection": "bestsellers"},
        }
    },
    "order": ["vibe"],
}


def main():
    tid = sys.argv[1]
    tok = T.token()
    H = {"X-Shopify-Access-Token": tok}
    for key, p in ASSETS:
        sc, r = T.upload(tok, tid, key, p.read_text(encoding="utf-8"))
        print("upload", key, "->", sc, ("" if sc in (200, 201) else str(r)[:160]))
        time.sleep(0.3)
    # index.json
    sc, r = T.upload(tok, tid, "templates/index.json", json.dumps(INDEX, ensure_ascii=False, indent=2))
    print("upload templates/index.json ->", sc, ("" if sc in (200, 201) else str(r)[:200]))
    shop = T.BASE.split("/admin")[0].replace("https://", "")
    print("PREVIEW:", f"https://{shop}/?preview_theme_id={tid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
