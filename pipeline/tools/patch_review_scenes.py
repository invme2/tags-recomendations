#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_review_scenes.py — make review-photo scenes PRODUCT-RELEVANT.

Problem: review scenes were a fixed beauty-ish pool (mirror selfie, vanity) ->
identical-ish across products AND wrong for non-beauty (a fishing rod must show
a riverbank, not a bathroom).

Fix (3 layers):
  D) Designer output schema gains `review_scenes`: 8 UGC scene ideas grounded in
     the product's real use/category.
  G) Designer instruction block explaining review_scenes with category examples.
  E) meta-assembly tucks designer_resp.review_scenes into stored meta.
  F) reviews builder consumes meta.review_scenes (PRIMARY) and, when absent,
     falls back to a CATEGORY-AWARE pool keyed off product title/tags (fishing/
     sports/car/tools/electronics/apparel/jewelry/kids/home/beauty/fragrance),
     not the old beauty template. Both seed-shuffled + product palette injected.

Notebook edits via nbformat (+ snapshot already taken). ast.parse validated.
Idempotent (markers detected).
"""
from __future__ import annotations
import ast, sys, nbformat
from pathlib import Path

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL_ID = "ce20f070"

# ── EDIT D: schema — add review_scenes after photo_briefs close ──────────────
D_OLD = (
    "                '    //          | inline-hero | inline-story-1 | inline-story-2 | inline-story-3 | inline-feature | inline-cta\\n'\n"
    "                '  ],\\n'\n"
)
D_NEW = D_OLD + (
    "                '  \"review_scenes\":[ // EXACTLY 8 UGC phone-snapshot scene ideas for the review widget, matched to THIS product\\n'\n"
    "                '    {\"title\":\"3-5 word scene name\",\"scene\":\"ONE sentence: a candid iPhone shot of THIS product used or shown where a REAL owner would; derive place and activity from the product category (fishing rod to a riverbank with the catch; drill to mid-repair in a garage; perfume to a vanity before a night out). Real, lived-in, slightly cluttered. NO studio, NO white seamless.\",\"setting\":\"2-4 word real place\"},\\n'\n"
    "                '    ... 8 scenes total, ALL different places/activities\\n'\n"
)
D_MARK = '"review_scenes":['

# ── EDIT G: instruction block — review_scenes with category examples ─────────
G_OLD = 'so the editor sees what TEXT the photo accompanies.\\n\\n"'
G_NEW = G_OLD + "\n" + (
    '                "REVIEW_SCENES (meta-level, EXACTLY 8 items) — UGC phone-snapshot scene ideas for the Judge.me/Loox review widget. NOT studio: imitate a real owner\'s candid iPhone shot. Ground EVERY scene in where and how a real owner of THIS product would use or show it; derive place and activity from the product category, never a generic template: fishing rod -> riverbank with the catch / casting at dawn; cordless drill -> mid-repair on a workbench / install at home; perfume -> vanity before a night out / in the handbag / gifted; kids toy -> child mid-play on the rug / birthday. All 8 DISTINCT places, real and lived-in, slightly cluttered, NO white seamless, NO studio light.\\n\\n"'
)
G_MARK = "REVIEW_SCENES (meta-level"

# ── EDIT E: meta assembly — tuck review_scenes in ───────────────────────────
E_OLD = "            meta['photo_briefs'] = designer_resp.get('photo_briefs') or []"
E_NEW = E_OLD + "\n            meta['review_scenes'] = designer_resp.get('review_scenes') or []"
E_MARK = "meta['review_scenes'] = designer_resp.get('review_scenes')"

# ── EDIT F: replace the reviews builder block (relative indent, base 0) ──────
REVIEWS_REL2 = r'''# Per-product review scenes. PRIMARY = Designer meta.review_scenes (product-
# specific, e.g. fishing rod -> riverbank). FALLBACK = category-aware pool keyed
# off the product title/tags. Both seed-shuffled so two products never share the
# same set/order; the product palette is injected so shots read in its tonal family.
import hashlib as _hl_rev
_seed_src = (product.get('url_handle') or product.get('handle') or product.get('title') or 'x')
_seed_rev = int(_hl_rev.md5(_seed_src.encode('utf-8', 'ignore')).hexdigest(), 16)
def _rot(_lst, _k, _salt=0):
    if not _lst:
        return []
    _n = len(_lst)
    _order = sorted(range(_n), key=lambda _j: _hl_rev.md5(('%d-%d-%d' % (_seed_rev, _salt, _j)).encode()).hexdigest())
    return [_lst[_order[_i % _n]] for _i in range(_k)]
try:
    _meta_for_rev = _meta_pp if isinstance(_meta_pp, dict) else {}
except NameError:
    _meta_for_rev = {}
_palette_for_rev = (_visual_style_pp or '').strip()
if len(_palette_for_rev) > 600:
    _palette_for_rev = _palette_for_rev[:600].rsplit(' ', 1)[0] + ' …'
_scenes_src = []
for _s in (_meta_for_rev.get('review_scenes') or []):
    if not isinstance(_s, dict):
        continue
    _t = (_s.get('title') or '').strip()
    _sc = (_s.get('scene') or '').strip()
    _set = (_s.get('setting') or '').strip()
    if not (_t and _sc):
        continue
    _bd = [_sc]
    if _set:
        _bd.append('Setting: %s.' % _set)
    _scenes_src.append((_t, _bd))
_used_designer = len(_scenes_src) >= 6
_GENERIC_FB = [
    ("Just arrived / unboxing", ["Product fresh out of the shipping mailer on a table,", "cardboard and packing slip still in frame."]),
    ("Among everyday things", ["Product among the owner's clutter — keys, mug, phone —", "low-angle candid phone shot."]),
    ("Gifted to someone", ["Handed over with a simple ribbon or sticky note,", "two people's hands in frame."]),
    ("In the bag / on the go", ["Tucked into a tote or backpack with everyday carry,", "shot in a car or on a cafe table."]),
    ("Close-up in hand", ["Macro-ish close-up held between thumb and finger,", "background out of focus."]),
    ("In its real spot", ["Where the owner actually keeps it, slightly messy", "real room, natural window light."]),
]
_CAT_FB = {
    "fragrance": [
        ("Before a night out", ["At the vanity mid-routine, mirror lights, a spritz", "to the wrist before heading out."]),
        ("On the dresser", ["Bottle by a watch, jewelry dish and keys on a dresser,", "morning window light."]),
        ("In the handbag", ["Bottle tucked in an open handbag with phone and lipstick,", "candid grab shot."]),
        ("Gifted with a ribbon", ["Boxed bottle with a ribbon just handed over,", "two hands in frame, warm light."]),
        ("Spritz on the wrist", ["Wrist mid-spritz, fine mist in the air, hallway backdrop,", "slight motion blur."]),
    ],
    "beauty": [
        ("Morning routine at the sink", ["On the bathroom sink mid-routine, towel and toothbrush", "in frame, mirror slightly steamy."]),
        ("On the vanity", ["Among makeup and a mirror on the vanity, soft daylight,", "a little clutter."]),
        ("Mid-application", ["Hand applying it, caught in motion with slight blur,", "real bathroom backdrop."]),
        ("Shelfie", ["Lined up with other bottles on a bathroom shelf,", "candid phone shot."]),
        ("Just arrived", ["Fresh out of the mailer on the counter, packing slip in frame."]),
    ],
    "tools": [
        ("Mid-repair on the bench", ["In use on a cluttered workbench, screws and sawdust around,", "garage light."]),
        ("On the pegboard", ["Resting on a garage pegboard among other tools,", "candid phone shot."]),
        ("On the jobsite", ["Pulled from a tool bag on a worksite floor,", "dust and offcuts around."]),
        ("Mid-install at home", ["Owner mid-install with the tool in hand,", "real room, slightly messy."]),
        ("Just unboxed", ["Fresh out of the box on the garage bench, packaging beside it."]),
    ],
    "car": [
        ("Mounted in the car", ["Installed in the car interior, dashboard and wheel in frame,", "daylight through the windshield."]),
        ("Garage install", ["Owner fitting it by the open car door in a garage,", "tools nearby."]),
        ("On a road trip", ["In use during a drive, road and dashboard visible,", "casual phone snap."]),
        ("In the trunk", ["In an open trunk with everyday car clutter,", "parking-lot light."]),
        ("Just arrived", ["Fresh out of the box on the driver's seat, packaging beside it."]),
    ],
    "electronics": [
        ("On the desk in use", ["In use on a cluttered desk with a laptop and mug,", "candid shot."]),
        ("Charging on the nightstand", ["On the bedside table charging overnight, soft lamp light."]),
        ("On the commute", ["In use on a train or in a car, device in hand,", "real commute backdrop."]),
        ("On the couch", ["Used while relaxing on the sofa, TV or window behind,", "evening light."]),
        ("Just unboxed", ["Fresh out of the box on a table, cable and manual in frame."]),
    ],
    "apparel": [
        ("Outfit mirror selfie", ["Wearing or holding it in a mirror selfie, phone in hand,", "bedroom or hallway."]),
        ("Flat-lay on the bed", ["Laid out on the bed with accessories, top-down phone shot."]),
        ("Out and about", ["Worn or carried outdoors — street, cafe or park —", "candid shot."]),
        ("In the closet", ["Hung among other clothes in the closet, phone snap."]),
        ("Trying it on", ["Fresh out of the poly mailer, mid try-on, mirror in frame."]),
    ],
    "jewelry": [
        ("Worn close-up", ["On the wrist, neck or hand, skin and natural light,", "slightly soft focus."]),
        ("In the gift box", ["In its little box with a ribbon, just opened, two hands."]),
        ("On the vanity dish", ["Resting in a trinket dish with other jewelry,", "morning light."]),
        ("Dressed up", ["Worn with an outfit in a mirror selfie before going out."]),
        ("Just arrived", ["Fresh out of the pouch on a hand, packaging beside it."]),
    ],
    "kids": [
        ("Child mid-play", ["Child playing with it on the living-room rug, toys around,", "candid parent phone shot."]),
        ("Birthday moment", ["Just unwrapped at a small party, ribbon and box in frame."]),
        ("In the nursery", ["In its spot in the kid's room, soft daylight, slightly messy."]),
        ("On the go", ["In the stroller or diaper bag out and about, candid grab shot."]),
        ("Just arrived", ["Fresh out of the box on the play mat, packaging beside it."]),
    ],
    "sports": [
        ("Out in use", ["Outdoors — riverbank, trail, court or gym — owner mid-", "activity, natural light."]),
        ("Gear laid out", ["Laid out with the rest of the kit before heading out,", "entryway or garage floor."]),
        ("Post-activity", ["After use, a bit of dirt or water on it, candid shot", "at the car or trailhead."]),
        ("In the gear bag", ["Packed in the duffel or tackle bag with other gear,", "candid shot."]),
        ("Ready to try", ["Fresh out of the box at home, ready to take out,", "packaging beside it."]),
    ],
    "home": [
        ("In use on the counter", ["In use on the kitchen counter mid-task, cookware and", "ingredients around."]),
        ("In its spot", ["Where it lives — shelf, corner, counter — slightly", "lived-in room, daylight."]),
        ("Mid-task at home", ["Owner using it mid-chore, candid phone shot."]),
        ("On the shelf", ["Among everyday household items on a shelf, phone snap."]),
        ("Just unboxed", ["Fresh out of the box on the table, packaging in frame."]),
    ],
}
_CAT_KW = [
    ("fragrance", ("perfume", "cologne", "fragrance", "eau de", "parfum", " scent")),
    ("beauty", ("serum", "cream", "skin", "facial", "makeup", "lipstick", " mask", "lotion", "cosmetic", "shampoo", "nail", "lash", "wrinkle", "moistur")),
    ("tools", ("drill", " saw", "wrench", "screwdriver", " tool", "sander", "hammer", "plier", "hardware", "grinder")),
    ("car", ("car ", " auto", "vehicle", "motorcycle", "dashboard", "windshield", " tire", "engine", "automotive")),
    ("electronics", ("phone", "charger", "earbud", "headphone", "speaker", "camera", " cable", "laptop", "tablet", "bluetooth", "wireless", " led", "gadget", "power bank")),
    ("apparel", ("shirt", "dress", "jacket", "hoodie", "pants", "jeans", " sock", "legging", "sweater", " coat", " shoe", "sneaker", " boot", "backpack", "wallet", " bag")),
    ("jewelry", (" ring", "necklace", "bracelet", "earring", "pendant", "jewelry", " bangle", "anklet")),
    ("kids", (" toy", " baby", " kids", " child", "nursery", "stroller", "infant", "plush", "toddler")),
    ("sports", ("fishing", " rod", " reel", "tackle", "camping", " tent", "hiking", "cycling", " bike", "fitness", " yoga", " gym", "dumbbell", "swim", " ski", "hunting", " golf", "running")),
    ("home", ("kitchen", " cook", " pan", " pot", " knife", " decor", " lamp", "storage", "cleaning", " pet ", "garden", " towel", "curtain", "pillow", "organizer", "household")),
]
_hay = ((product.get('title') or '') + ' ' + ' '.join(str(_x) for _x in (_meta_for_rev.get('product_tags') or []))).lower()
_bucket = ''
for _bk, _kws in _CAT_KW:
    if any(_kw in _hay for _kw in _kws):
        _bucket = _bk
        break
if len(_scenes_src) < 8:
    _fb_pool = _CAT_FB.get(_bucket, []) + _GENERIC_FB
    _seen = set(_t.lower() for _t, _ in _scenes_src)
    for _t, _bd in _rot(_fb_pool, len(_fb_pool), 77):
        if len(_scenes_src) >= 8:
            break
        if _t.lower() in _seen:
            continue
        _seen.add(_t.lower())
        _scenes_src.append((_t, _bd))
_picked = _rot(_scenes_src, min(8, len(_scenes_src)), 55)
_scene_source = 'Designer (product-specific)' if _used_designer else ('category fallback: %s' % (_bucket or 'generic'))
_rev_lines = [
    f"# UGC Review Photos — {product.get('title','')}",
    "",
    "8 authentic iPhone-snapshot prompts for review widgets",
    "(Judge.me / Loox / Stamped) and 'as seen on Insta' carousels.",
    "",
    "============================================================",
    "HOW TO USE",
    "============================================================",
    "1. Open ChatGPT-UI (GPT-4o image gen) OR Midjourney v6+",
    "   --style raw. AVOID DALL-E 3 — too clean / studio-y.",
    "2. Upload this file + 1-2 reference photos of the product",
    "   (the carousel hero from /photos/01-carousel-hero.* works).",
    "3. Tell ChatGPT EXACTLY: 'Generate 8 UGC review photos one at",
    "   a time, output as SEPARATE individual images, NOT a collage",
    "   or grid. Generate review_01 first, then in the NEXT message",
    "   generate review_02, then review_03, etc. Each output = ONE",
    "   image file. Use the reference for product likeness but make",
    "   it look like real candid phone snapshots.'",
    "4. Save outputs as review_01.jpg ... review_08.jpg",
    "5. If ChatGPT made a collage: reply 'split that result into 8",
    "   separate individual images, one per output message'.",
    "5. Upload to your review widget (Judge.me bulk import,",
    "   Loox Photos tab, Stamped UGC, etc).",
    "",
    "============================================================",
    "PRODUCT CONTEXT",
    "============================================================",
    f"  Product: {product.get('title','')}",
    f"  Use:     {_use_context}",
    f"  Scenes:  {_scene_source}",
    "",
    "============================================================",
    "PRODUCT PALETTE & MOOD (carry THIS product's tonal family)",
    "============================================================",
    "  These are candid phone snapshots, but the product and its",
    "  surroundings should read in the product's own colour world so",
    "  the set looks like THIS product, not a generic template:",
    f"    {_palette_for_rev or 'soft natural tones drawn from the product packaging'}",
    "",
    "============================================================",
    "UNIVERSAL VISUAL DNA (apply to ALL 8 photos)",
    "============================================================",
    "",
    "  CAMERA",
    "    - Shot on iPhone 13-15, default camera app, no filters",
    "    - 4:5 OR 3:4 vertical aspect (Instagram / phone-screen native)",
    "    - Slight handshake — NOT tripod-stable",
    "    - Auto-focus moment captured — sometimes slightly soft",
    "    - Auto-exposure imperfection: occasional mild over/under-exposure",
    "",
    "  LIGHT",
    "    - Mixed: warm tungsten + cool window light = realistic temperature",
    "    - No ring-light, no softbox, no rim-light",
    "    - Shadows are visible, not bounced out",
    "    - Occasional lens flare or window glare allowed",
    "",
    "  COMPOSITION",
    "    - Slightly off-center subject — not perfectly framed",
    "    - Real, lived-in background — NOT a clean white studio",
    "    - Everyday clutter appropriate to the scene's place",
    "",
    "  POST",
    "    - NO retouching, NO skin smoothing",
    "    - Pore-level skin texture (not airbrushed)",
    "    - JPEG compression artifacts subtly visible",
    "    - Optional: tiny EXIF-style timestamp overlay in corner",
    "",
    "  PEOPLE (when included)",
    "    - Diverse ages, skin tones, body types — DO NOT default",
    "      to one demographic. Mix across the 8 photos.",
    "    - NO model-perfect faces. Normal pores, hair flyaways,",
    "      slight asymmetry, occasional fingernail polish chip.",
    "    - NO posed smiling — neutral or mid-expression",
    "",
    "  PRODUCT PRESERVATION",
    "    - Brand text on packaging must remain READABLE and",
    "      unchanged. Don't redesign labels.",
    "",
    "============================================================",
    "8 SHOT CONCEPTS — distinct scenes, matched to THIS product",
    "============================================================",
    "",
]
for _ri, (_rtitle, _rbody) in enumerate(_picked, 1):
    _rev_lines.append("### review_%02d — '%s'" % (_ri, _rtitle))
    for _bl in _rbody:
        _rev_lines.append("    " + _bl)
    _rev_lines.append("")
_rev_lines.extend([
    "============================================================",
    "OUTPUT CHECKLIST",
    "============================================================",
    "  □ 8 distinct images — different places/activities, not one room",
    "  □ Every scene fits where a real owner of THIS product would shoot it",
    "  □ NO white seamless backdrops anywhere",
    "  □ NO studio lighting setups visible",
    "  □ Product packaging text remains readable + unchanged",
    "  □ Faces (when present) are demographically varied",
    "  □ At least 2 photos include NO person at all",
    "    (product-only candid moments)",
])
'''

F_START = "# Per-product seed -> distinct setting anchors + the product's own"
F_END = '_prompt_reviews_txt = "\\n".join(_rev_lines)'
F_MARK = "f\"  Scenes:  {_scene_source}\""


def splice_reviews(src: str) -> str:
    if F_MARK in src:
        print("  EDIT F: already applied — skip")
        return src
    lines = src.split("\n")
    si = next((i for i, l in enumerate(lines) if l.strip().startswith(F_START)), None)
    if si is None:
        raise SystemExit("EDIT F: start marker not found")
    ei = next((i for i, l in enumerate(lines) if l.strip().startswith(F_END)), None)
    if ei is None or ei <= si:
        raise SystemExit("EDIT F: end marker not found")
    base = len(lines[si]) - len(lines[si].lstrip(" "))
    new_block = [(" " * base + ln) if ln.strip() else "" for ln in REVIEWS_REL2.split("\n")]
    while new_block and new_block[-1] == "":
        new_block.pop()
    lines[si:ei] = new_block
    print(f"  EDIT F: spliced reviews v2 ({ei - si} -> {len(new_block)} lines, base={base})")
    return "\n".join(lines)


def repl(src, name, old, new, mark):
    if mark in src:
        print(f"  EDIT {name}: already applied — skip")
        return src
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"EDIT {name}: anchor count {n} (want 1)")
    print(f"  EDIT {name}: applied")
    return src.replace(old, new, 1)


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = next(c for c in nb.cells if c.get("id") == CELL_ID)
    src = cell.source
    orig = src
    src = repl(src, "D", D_OLD, D_NEW, D_MARK)
    src = repl(src, "G", G_OLD, G_NEW, G_MARK)
    src = repl(src, "E", E_OLD, E_NEW, E_MARK)
    src = splice_reviews(src)
    if src == orig:
        print("No changes.")
        return 0
    try:
        ast.parse(src)
    except SyntaxError as e:
        Path("review_scenes_failed.py").write_text(src, encoding="utf-8")
        raise SystemExit(f"AST FAILED: {e}")
    print("  ast.parse OK")
    cell.source = src
    nbformat.write(nb, NB)
    print(f"WROTE {NB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
