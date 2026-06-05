#!/usr/bin/env python3
"""patch_title_prompt.py — inject an expert marketplace TITLE / META / SHORT-DESC
instruction block into the Designer system prompt.

WHY: the Shopify storefront product title is set to meta.seo_meta.title
(_clean_title = (seo_t or product['title'])[:255]). The Designer prompt only
specified "55-60 chars" for it — no merchandising guidance. The title is the
single highest-leverage sales/CTR element (catalog grid, on-site search,
Google Shopping, cart, browser tab). This adds concrete expert rules so titles
stop being length-only and become conversion-optimized, and gives meta
description + short_description real CTR guidance too.

nbformat path. After: python pipeline/tools/notebook_smoke.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 14

# Anchor: insert BETWEEN the IMG_ALT line and the IMAGES line of COPY QUALITY.
IMG_ALT_LINE = '                "- IMG_ALT 5-12 word descriptive (not \\"image 1\\").\\n\\n"'
IMAGES_LINE = '                "IMAGES (URL-based, picked from EPROLO source list):\\n"'
OLD = IMG_ALT_LINE + "\n" + IMAGES_LINE

# Expert instruction text (plain — escaped into source literals via json.dumps).
INSERT = [
    "PRODUCT TITLE (meta.seo_meta.title) — THIS BECOMES THE STOREFRONT PRODUCT NAME shown in the catalog grid, on-site search, Google Shopping, the cart and the browser tab. It is the single highest-leverage sales + click-through element. Craft it like a marketplace merchandiser, NOT an SEO bot:",
    "- STRUCTURE: <recognizable product-type noun> + <strongest single benefit or differentiator>. The shopper must know WHAT it is in under 1 second, then WHY it is better. e.g. 'LED Light Therapy Wand — Firmer-Looking Skin in 8 Weeks'; 'Leg Compression Massager — Relief After Long Days on Your Feet'.",
    "- Lead with the category noun a real shopper would actually search ('Facial Steamer', 'Memory Foam Pillow') — never a brand buzzword or model code.",
    "- Front-load ONE concrete benefit/outcome. Title Case. Human and scannable.",
    "- 50-60 chars ideal, HARD cap 60 (Google truncates beyond ~60). Never pad to reach length.",
    "- FORBIDDEN (AliExpress/EPROLO tells that destroy CTR + trust): ALL-CAPS words, '2024/2025 New', 'Hot Sale', 'Free Shipping', emoji, spec dumps ('1500mAh 6-in-1 Multifunction'), keyword stuffing, comma-piles.",
    "- Include the primary search keyword naturally (helps Google Shopping + on-site search), but a HUMAN must want to click it.",
    "META DESCRIPTION (meta.seo_meta.description) — the Google result snippet that wins or loses the click. 140-155 chars: open with the core benefit + primary keyword, add ONE curiosity or proof hook, close with a soft pull ('See why...', 'Made for...'). Do NOT restate the title. No price, no shipping, no exclamation marks.",
    "SHORT DESCRIPTION (meta.short_description) — opens the body copy. Lead with the AFTER-STATE the buyer wants (the outcome/feeling), not the spec sheet. 2-3 editorial sentences.",
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    src = cell.source
    if src.count(OLD) != 1:
        print(f"FAIL: anchor found {src.count(OLD)} times (need exactly 1)")
        return 1
    block = "".join("                " + json.dumps(t + "\n") + "\n" for t in INSERT)
    block += "                " + json.dumps("\n") + "\n"  # blank line before IMAGES
    new = IMG_ALT_LINE + "\n" + block + IMAGES_LINE
    cell.source = src.replace(OLD, new)
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print(f"OK: inserted {len(INSERT)} title/meta/short-desc instruction lines into Designer prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
