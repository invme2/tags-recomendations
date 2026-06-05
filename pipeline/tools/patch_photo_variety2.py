#!/usr/bin/env python3
"""patch_photo_variety2.py — enlarge the photo-theme pools and improve the
distribution so backgrounds rarely repeat across products.

- Pools roughly 2-3x bigger (28 surfaces, 24 props, 16 palettes, 12 lights,
  10 angles) + a NEW 'composition' dimension.
- _photo_theme now derives each dimension from an INDEPENDENT slice of the md5
  hex digest, so dimensions are uncorrelated and near-uniform (the old version
  reused the same integer, clustering surfaces).

Replaces the existing _PHOTO_* block + _photo_theme() in cell 4 in place.
nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
START = "# ── Per-product photo styling theme"
END = "def _check_anthropic_budget():"

NEW = '''# ── Per-product photo styling theme (variety for photo_briefs; all LIGHT) ──
_PHOTO_SURFACES = [
    "white carrara marble", "pale honey-oak wood", "cream washed linen",
    "soft pink terrazzo", "frosted pale-blue glass", "warm sand travertine stone",
    "matte ivory ceramic tile", "light poured concrete", "brushed champagne metal",
    "a blush-to-cream paper gradient", "pale sage-painted plaster", "light woven rattan",
    "pale grey limewash wall", "soft white boucle fabric", "light beech butcher-block",
    "pale pink quartz", "cream marble with soft grey veining", "raw oat-toned canvas",
    "light birch plywood", "soft lilac matte acrylic", "pale celadon ceramic",
    "warm white plaster", "light cork board", "pastel-mint glass",
    "sun-bleached driftwood", "ivory ribbed glass", "pale apricot suede", "white pebbled leather",
]
_PHOTO_PROPS = [
    "a sprig of fresh eucalyptus", "a few dried wildflowers", "halved citrus and herbs",
    "smooth river pebbles", "a neatly folded waffle towel", "scattered water droplets",
    "a trailing silk ribbon", "a single fresh bloom", "soft monstera-leaf shadows",
    "pastel geometric blocks", "loose flower petals", "a small potted succulent",
    "a sprig of lavender", "fresh mint leaves", "a curl of orange peel",
    "soft cotton flowers", "a few pale seashells", "a glass of still water with tiny bubbles",
    "dried palm fronds", "a loosely draped linen napkin", "fresh chamomile flowers",
    "a smooth ceramic dish", "soft tulle gauze", "a sprig of rosemary",
]
_PHOTO_PALETTES = [
    "warm cream and sage green", "blush pink and ivory", "pale sky-blue and white",
    "soft peach and sand", "dusty lavender and grey", "fresh mint and cream",
    "terracotta and natural linen", "butter-yellow and white", "soft coral and bone",
    "powder-blue and oat", "sage and warm taupe", "apricot and cream",
    "lilac and soft grey", "seafoam and ivory", "dusty rose and beige", "pale gold and white",
]
_PHOTO_LIGHT = [
    "soft morning window light", "bright clean diffused daylight", "warm golden-hour glow",
    "airy overcast softbox light", "gentle dappled sunlight through leaves",
    "even bright editorial daylight", "soft backlit halo glow", "fresh cool north-window light",
    "warm afternoon side-light", "bright high-key wash", "gentle sunrise pastel light",
    "soft diffused skylight from above",
]
_PHOTO_ANGLES = [
    "straight-on eye-level", "a 45-degree three-quarter view", "a crisp top-down flat-lay",
    "a slightly low hero angle", "a floating gently-tilted angle", "a close macro detail angle",
    "a high three-quarter overhead", "an off-center editorial angle",
    "a slight dutch-tilt dynamic angle", "a centered symmetrical hero angle",
]
_PHOTO_COMPOSITION = [
    "minimalist with generous negative space", "a styled flat-lay arrangement",
    "the product as a bold single hero", "an editorial off-center layout",
    "a tight macro crop", "a relaxed lifestyle vignette",
    "a clean symmetrical centered shot", "a layered depth arrangement with soft foreground",
]

def _photo_theme(seed_str):
    import hashlib as _hh
    _d = _hh.md5((seed_str or "x").encode("utf-8")).hexdigest()
    def _pk(seq, a, b):
        return seq[int(_d[a:b], 16) % len(seq)]
    _s    = _pk(_PHOTO_SURFACES,    0, 6)
    _p    = _pk(_PHOTO_PROPS,       6, 12)
    _pal  = _pk(_PHOTO_PALETTES,    12, 18)
    _l    = _pk(_PHOTO_LIGHT,       18, 23)
    _a    = _pk(_PHOTO_ANGLES,      23, 27)
    _comp = _pk(_PHOTO_COMPOSITION, 27, 32)
    return ("surface/backdrop: " + _s + "; props: " + _p + "; palette accents: " + _pal
            + "; light mood: " + _l + "; composition: " + _comp + "; hero angle: " + _a)


'''


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[4]
    src = cell.source
    i = src.find(START)
    j = src.find(END)
    if i < 0 or j < 0 or j < i:
        print(f"FAIL: markers not found (i={i} j={j})")
        return 1
    cell.source = src[:i] + NEW + src[j:]
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("Expanded photo-theme pools + independent-slice distribution applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
