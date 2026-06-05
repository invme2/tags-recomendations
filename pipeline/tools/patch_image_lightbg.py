#!/usr/bin/env python3
"""patch_image_lightbg.py — enforce LIGHT-background rule for IMAGE generation.

GAP FOUND: the operator rule (CLAUDE.md 2026-05-29) bans black/dark backgrounds
in BOTH image and video generation. Video has it (LIGHT_BG guard in
video_prompts.py). But the Designer's photo_briefs / visual_style (which drive
the photo_pack ZIP images the operator generates in ChatGPT/Ideogram) had NO
light-background mandate — Designer could emit visual_style "dramatic dark
studio" and produce dark photos that clash with the light store.

This inserts a non-negotiable LIGHT-BACKGROUND block into the PHOTO_BRIEFS
section (right after the brief-budget rules, before the CAROUSEL funnel),
mirroring the video guard, plus richer visual_style quality guidance.

Anchored on an ASCII-only line ('- Skip a slot...') to avoid em-dash escape
mismatches. nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 14


def lit(t: str) -> str:
    return "                " + json.dumps(t + "\n")


SKIP_ANCHOR = "                " + json.dumps(
    "- Skip a slot entirely rather than duplicate weakly. "
    "5 carousel + 2 strong inline > 12 weak briefs.\n\n"
)

IMG_LINES = [
    "IMAGE LOOK — LIGHT BACKGROUNDS ONLY (operator rule, NON-NEGOTIABLE — same as video):",
    "- The store is LIGHT. Every generated/edited photo AND the visual_style paragraph that governs them MUST use a bright white, pastel, or airy-daylight background. ABSOLUTELY NO black, dark, charcoal, moody or 'dramatic studio' background — any slot, any brief.",
    "- visual_style: describe ONE consistent light set — soft diffused daylight, gentle natural shadows, clean white/cream/pastel seamless OR a tasteful light lifestyle surface (marble, pale wood, linen). Pull 1-2 soft accent colors from the product palette. Editorial e-commerce quality, uncluttered.",
]
# last line carries the blank-line separator before CAROUSEL
IMG_LAST = "                " + json.dumps(
    "- Every brief's edit_instructions MUST name the background explicitly "
    "(e.g. 'pure white seamless', 'soft blush-cream gradient', 'bright sunlit "
    "kitchen counter') so no photo ever defaults to a dark background.\n\n"
)


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    src = cell.source
    if src.count(SKIP_ANCHOR) != 1:
        print(f"FAIL: skip-slot anchor count={src.count(SKIP_ANCHOR)}")
        return 1
    block = "".join(lit(x) + "\n" for x in IMG_LINES) + IMG_LAST + "\n"
    new = SKIP_ANCHOR + "\n" + block
    cell.source = src.replace(SKIP_ANCHOR, new)
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print(f"OK: inserted LIGHT-background image block ({len(IMG_LINES)+1} lines) into PHOTO_BRIEFS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
