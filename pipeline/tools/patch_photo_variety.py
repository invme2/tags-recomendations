#!/usr/bin/env python3
"""patch_photo_variety.py — inject a per-PRODUCT photo styling theme so the
Designer's photo_briefs (image-generation prompts) stop looking the same across
products.

Root cause: the carousel slot semantics are fixed ("pure white seamless" hero,
etc.), so the model emits near-identical edit_instructions for every product.
A soft "be varied" instruction isn't enough.

Fix (same idea as video_prompts.py): compute a DISTINCT styling theme per product
deterministically in Python (surface / props / palette / light / angle, all
LIGHT) and inject it into the Designer user prompt. The model must build the
photo_briefs around this concrete, per-product theme -> the catalog's generated
photos become genuinely varied.

nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

HELPER = '''# ── Per-product photo styling theme (variety for photo_briefs; all LIGHT) ──
_PHOTO_SURFACES = [
    "white carrara marble", "pale honey-oak wood", "cream washed linen",
    "soft pink terrazzo", "frosted pale-blue glass", "warm sand travertine stone",
    "matte ivory ceramic tile", "light poured concrete", "brushed champagne metal",
    "a blush-to-cream paper gradient", "pale sage-painted plaster", "light woven rattan",
]
_PHOTO_PROPS = [
    "a sprig of fresh eucalyptus", "a few dried wildflowers", "halved citrus and herbs",
    "smooth river pebbles", "a neatly folded waffle towel", "scattered water droplets",
    "a trailing silk ribbon", "a single fresh bloom", "soft monstera-leaf shadows",
    "pastel geometric blocks", "loose flower petals", "a small potted succulent",
]
_PHOTO_PALETTES = [
    "warm cream and sage green", "blush pink and ivory", "pale sky-blue and white",
    "soft peach and sand", "dusty lavender and grey", "fresh mint and cream",
    "terracotta and natural linen", "butter-yellow and white",
]
_PHOTO_LIGHT = [
    "soft morning window light", "bright clean diffused daylight", "warm golden-hour glow",
    "airy overcast softbox light", "gentle dappled sunlight through leaves",
    "even bright editorial daylight",
]
_PHOTO_ANGLES = [
    "straight-on eye-level", "a 45-degree three-quarter view", "a crisp top-down flat-lay",
    "a slightly low hero angle", "a floating gently-tilted angle",
]

def _photo_theme(seed_str):
    import hashlib as _hh
    _n = int(_hh.md5((seed_str or "x").encode("utf-8")).hexdigest(), 16)
    _s = _PHOTO_SURFACES[_n % len(_PHOTO_SURFACES)]
    _p = _PHOTO_PROPS[(_n // 7) % len(_PHOTO_PROPS)]
    _pal = _PHOTO_PALETTES[(_n // 13) % len(_PHOTO_PALETTES)]
    _l = _PHOTO_LIGHT[(_n // 17) % len(_PHOTO_LIGHT)]
    _a = _PHOTO_ANGLES[(_n // 19) % len(_PHOTO_ANGLES)]
    return ("surface/backdrop: " + _s + "; props: " + _p + "; palette accents: " + _pal
            + "; light mood: " + _l + "; hero angle: " + _a)


def _check_anthropic_budget():'''

EDITS = [
    # cell 4: pools + _photo_theme() before _check_anthropic_budget
    (4, "def _check_anthropic_budget():", HELPER),
    # cell 14: compute theme before _product_context
    (14,
     '            _product_context = f"""Generate a product description page for this product:',
     '            _photo_theme_str = _photo_theme(handle if handle else safe_title)\n'
     '            _product_context = f"""Generate a product description page for this product:'),
    # cell 14: inject theme into the user prompt
    (14,
     "ACCENT_SOFT: {stage1.get('accent_soft','#F5F0EA')}\n\nVISION ANALYSIS:",
     "ACCENT_SOFT: {stage1.get('accent_soft','#F5F0EA')}\n\n"
     "PHOTO STYLING THEME (use this DISTINCT look for THIS product's photo_briefs so it "
     "differs from every other product; ALL backgrounds LIGHT): {_photo_theme_str}\n\n"
     "VISION ANALYSIS:"),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    for idx, (ci, old, new) in enumerate(EDITS):
        cell = nb.cells[ci]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx} (cell {ci}): found {n}")
            print(f"  old: {old[:60]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx} (cell {ci})")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("Per-product photo styling theme injected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
