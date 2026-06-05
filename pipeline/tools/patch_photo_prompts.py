#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_photo_prompts.py — fix 3 photo-pack prompt bugs in Cell 14 (id ce20f070).

1) REVIEWS: were a fully hardcoded template (8 fixed scenes, no product palette)
   -> identical across products from the same collection. Now inject the product's
   own visual_style + a per-product seed that picks/orders 8 scenes from an 11-scene
   pool and rotates room/surface/light/clutter anchors. Two products diverge.
2) INLINE no-text contradiction: Designer sometimes emits 'infographic / callout /
   overlay' wording into an editorial (no-text) inline slot. Add a build-time
   EDITORIAL OVERRIDE guardrail + an inline-hero "must be lifestyle" nudge.
3) Designer instruction: add an explicit 'INLINE = ZERO TEXT' rule (prevention).

Notebook edits via nbformat (+ snapshot already taken). Validates with ast.parse.
Idempotent: re-running is a no-op (markers detected).
"""
from __future__ import annotations
import ast
import sys
import nbformat
from pathlib import Path

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL_ID = "ce20f070"

# ─────────────────────────────────────────────────────────────────────────────
# EDIT A — Designer instruction: explicit INLINE = ZERO TEXT rule
EDIT_A_ANCHOR = 'aspirational close-up that reinforces purchase decision.\\n"'
EDIT_A_INSERT = (
    '\n                "  - INLINE = ZERO TEXT: every inline brief is editorial in-page '
    'imagery. Its concept AND edit_instructions MUST NOT request overlay text, callouts, '
    'infographics, badges, specs, step numbers, labels, arrows or annotations (those belong '
    "to CAROUSEL only). A brief that requests 'infographic / callout / overlay / step / badge' "
    'for an inline slot is INVALID; rewrite it as a pure mood / lifestyle scene.\\n"'
)
EDIT_A_MARKER = "INLINE = ZERO TEXT"

# ─────────────────────────────────────────────────────────────────────────────
# EDIT B — inline build guardrail in _build_scope_prompt
EDIT_B_OLD = (
    "                                _entry.extend([\n"
    "                                    f\"- Concept: {_brief_pp.get('concept','')}\",\n"
    "                                    f\"- Edit instructions: {_brief_pp.get('edit_instructions','')}\",\n"
    "                                    \"\",\n"
    "                                ])\n"
    "                                lines.extend(_entry)"
)
EDIT_B_NEW = (
    "                                _entry.extend([\n"
    "                                    f\"- Concept: {_brief_pp.get('concept','')}\",\n"
    "                                    f\"- Edit instructions: {_brief_pp.get('edit_instructions','')}\",\n"
    "                                ])\n"
    "                                if scope == 'inline':\n"
    "                                    _ov_blob = (str(_brief_pp.get('concept','')) + ' ' + str(_brief_pp.get('edit_instructions',''))).lower()\n"
    "                                    _OV_KW = ('infographic', 'callout', 'call-out', 'overlay', 'badge', 'step ', 'step-', 'annotat', 'connector', 'caption', 'headline', 'text label', 'arrow')\n"
    "                                    if any(_k in _ov_blob for _k in _OV_KW):\n"
    "                                        _entry.append(\"- \\u26a0 EDITORIAL OVERRIDE: ignore any infographic / overlay / callout / step / badge / label / arrow wording above. Render NO text or graphics on this image \\u2014 product + ambient mood ONLY (page copy sits beside it).\")\n"
    "                                    if _slot_pp == 'inline-hero':\n"
    "                                        _entry.append(\"- \\u26a0 inline-hero must be a LIFESTYLE / in-use / emotional scene (a person or a real lived-in environment), NOT a product-on-surface still-life and NOT a repeat of carousel-hero's backdrop.\")\n"
    "                                _entry.append(\"\")\n"
    "                                lines.extend(_entry)"
)
EDIT_B_MARKER = "EDITORIAL OVERRIDE: ignore any infographic"

# ─────────────────────────────────────────────────────────────────────────────
# EDIT C — reviews block (relative indent, base 0). Splices in place of the old
# `_rev_lines = [ ... ]` literal, up to (not incl.) the `_prompt_reviews_txt` line.
REVIEWS_REL = r'''# Per-product seed -> distinct setting anchors + the product's own
# palette, so two products from the same collection never yield the
# same review scenes (fixes "reviews look identical" bug).
import hashlib as _hl_rev
_seed_src = (product.get('url_handle') or product.get('handle') or product.get('title') or 'x')
_seed_rev = int(_hl_rev.md5(_seed_src.encode('utf-8', 'ignore')).hexdigest(), 16)
def _rot(_lst, _k, _salt=0):
    if not _lst:
        return []
    _n = len(_lst)
    _order = sorted(range(_n), key=lambda _j: _hl_rev.md5(('%d-%d-%d' % (_seed_rev, _salt, _j)).encode()).hexdigest())
    return [_lst[_order[_i % _n]] for _i in range(_k)]
_ROOMS_R = ['bathroom counter', 'kitchen island', 'bedroom nightstand', 'home-office desk', 'sunny windowsill', 'vanity table', 'living-room coffee table', 'entryway console', 'reading nook', 'balcony bistro table']
_SURF_R = ['pale marble', 'light oak', 'white subway tile', 'woven rattan', 'crumpled linen', 'sand travertine', 'cream ceramic tray', 'blond bamboo', 'soft cotton throw', 'brushed pale concrete']
_LIGHT_R = ['soft morning window light', 'warm late-afternoon sun', 'overcast diffused daylight', 'bright midday daylight', 'golden-hour glow through a window']
_CLUT_R = ['a coffee mug', 'car keys', 'a hair tie', 'reading glasses', 'a small potted plant', 'a phone charger cable', 'a folded hand towel', 'an unlit candle', 'a paperback book', 'a water glass', 'a few receipts', 'a hairbrush']
_anchor_rooms = _rot(_ROOMS_R, 4, 11) or ['a real room']
_anchor_surf = _rot(_SURF_R, 3, 22) or ['a light surface']
_anchor_light = (_rot(_LIGHT_R, 1, 33) or ['soft daylight'])[0]
_anchor_clut = _rot(_CLUT_R, 5, 44)
_palette_for_rev = (_visual_style_pp or '').strip()
if len(_palette_for_rev) > 600:
    _palette_for_rev = _palette_for_rev[:600].rsplit(' ', 1)[0] + ' …'
_REV_POOL = [
    ("Quick mirror selfie holding product", [
        "Bathroom or hallway mirror, phone visible in the hand reflection.",
        "Other hand holds the product at chest height; subject looks at the",
        "product, not the camera. Cluttered surface behind."]),
    ("Just arrived / unboxing on the counter", [
        "Product fresh out of the mailer on a real counter. Cardboard",
        "shipper or shopping bag at the edge of frame."]),
    ("Mid-application / in-use moment", [
        "Hand mid-gesture using the product, action caught in motion with",
        "slight blur (pouring, applying, opening, dispensing, pressing)."]),
    ("First impression / 30-day check-in diptych", [
        "Two phone shots taped side-by-side as one image, same person and",
        "angle, slight tonal difference (shot on different days). If there is",
        "no visible change, make it a 'day 1 vs week 4' mood diptych."]),
    ("On the porch / just delivered", [
        "Delivery box on a porch or doorway, product half-pulled out, one",
        "packing-slip or shipping-sticker detail visible."]),
    ("Among everyday objects", [
        "Product surrounded by 6-10 unrelated everyday items, low-angle or",
        "top-down phone shot."]),
    ("Close-up of the label, fingerprints visible", [
        "Macro-ish close-up of the label held between thumb and index, a",
        "light fingerprint on the glossy surface, background out of focus."]),
    ("Wide lifestyle shot, product not the hero", [
        "Wider room scene; product visible somewhere in frame but NOT",
        "centered. Subject doing something normal (reading, cooking)."]),
    ("In the bag / on the go", [
        "Product tucked into a tote or handbag with everyday carry items,",
        "shot on a car seat, cafe table, or train tray."]),
    ("Gifted to a friend", [
        "Product with a simple ribbon or a handwritten sticky note, just",
        "handed over — two people's hands in the frame."]),
    ("Morning routine on the nightstand", [
        "Product among morning items (alarm clock, water glass, glasses),",
        "soft just-woke-up light, slightly messy."]),
]
_picked = _rot(_REV_POOL, 8, 55)
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
    "SETTING ANCHORS for THIS product — weave these in; do NOT reuse",
    "the generic example objects from other listings",
    "============================================================",
    f"  Rooms to favour:   {', '.join(_anchor_rooms)}",
    f"  Surfaces:          {', '.join(_anchor_surf)}",
    f"  Dominant light:    {_anchor_light}",
    f"  Everyday clutter:  {', '.join(_anchor_clut)}",
    "  Spread the 8 photos across these rooms/surfaces — no two photos",
    "  in the same spot with the same props.",
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
    "    - Background sometimes cluttered (real counter, desk, kitchen)",
    "      — NOT a clean white studio",
    "    - Use the SETTING ANCHORS above for props, not generic ones",
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
    "8 SHOT CONCEPTS — distinct scenes selected for THIS product",
    "============================================================",
    "",
]
for _ri, (_rtitle, _rbody) in enumerate(_picked, 1):
    _room = _anchor_rooms[(_ri - 1) % len(_anchor_rooms)]
    _surf = _anchor_surf[(_ri - 1) % len(_anchor_surf)]
    _rev_lines.append("### review_%02d — '%s'" % (_ri, _rtitle))
    for _bl in _rbody:
        _rev_lines.append("    " + _bl)
    _rev_lines.append("    Setting: %s on %s, %s." % (_room, _surf, _anchor_light))
    _rev_lines.append("")
_rev_lines.extend([
    "============================================================",
    "OUTPUT CHECKLIST",
    "============================================================",
    "  □ 8 distinct images — none look like the same person/room",
    "  □ NO white seamless backdrops anywhere",
    "  □ NO studio lighting setups visible",
    "  □ Each photo uses a DIFFERENT room/surface from the anchors",
    "  □ Product packaging text remains readable + unchanged",
    "  □ Faces (when present) are demographically varied",
    "  □ At least 2 photos include NO person at all",
    "    (product-only candid moments)",
])
'''

REVIEWS_START_MARK = "_rev_lines = ["
REVIEWS_END_MARK = '_prompt_reviews_txt = "\\n".join(_rev_lines)'
REVIEWS_DONE_MARK = "PRODUCT PALETTE & MOOD"


def apply_reviews(src: str) -> str:
    if REVIEWS_DONE_MARK in src:
        print("  EDIT C: already applied (marker present) — skip")
        return src
    lines = src.split("\n")
    si = next((i for i, l in enumerate(lines) if l.strip() == REVIEWS_START_MARK), None)
    if si is None:
        raise SystemExit("EDIT C: start marker '_rev_lines = [' not found")
    ei = next((i for i, l in enumerate(lines) if l.strip().startswith(REVIEWS_END_MARK)), None)
    if ei is None or ei <= si:
        raise SystemExit("EDIT C: end marker '_prompt_reviews_txt' not found after start")
    base = len(lines[si]) - len(lines[si].lstrip(" "))
    new_block = [(" " * base + ln) if ln.strip() else "" for ln in REVIEWS_REL.split("\n")]
    # drop a trailing empty produced by the closing newline of the raw string
    while new_block and new_block[-1] == "":
        new_block.pop()
    lines[si:ei] = new_block
    print(f"  EDIT C: spliced reviews block ({ei - si} old lines -> {len(new_block)} new), base indent={base}")
    return "\n".join(lines)


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = next((c for c in nb.cells if c.get("id") == CELL_ID), None)
    if cell is None:
        raise SystemExit(f"cell {CELL_ID} not found")
    src = cell.source
    orig = src

    # EDIT A
    if EDIT_A_MARKER in src:
        print("  EDIT A: already applied — skip")
    else:
        n = src.count(EDIT_A_ANCHOR)
        if n != 1:
            raise SystemExit(f"EDIT A: anchor found {n} times (want 1)")
        src = src.replace(EDIT_A_ANCHOR, EDIT_A_ANCHOR + EDIT_A_INSERT, 1)
        print("  EDIT A: inserted INLINE=ZERO TEXT rule")

    # EDIT B
    if EDIT_B_MARKER in src:
        print("  EDIT B: already applied — skip")
    else:
        n = src.count(EDIT_B_OLD)
        if n != 1:
            raise SystemExit(f"EDIT B: old block found {n} times (want 1)")
        src = src.replace(EDIT_B_OLD, EDIT_B_NEW, 1)
        print("  EDIT B: inserted inline EDITORIAL OVERRIDE guardrail")

    # EDIT C
    src = apply_reviews(src)

    if src == orig:
        print("No changes (all edits already applied).")
        return 0

    # validate
    try:
        ast.parse(src)
    except SyntaxError as e:
        Path("/tmp/cell14_failed.py").write_text(src, encoding="utf-8")
        raise SystemExit(f"AST parse FAILED: {e} (dumped /tmp/cell14_failed.py)")
    print("  ast.parse OK")

    cell.source = src
    nbformat.write(nb, NB)
    print(f"WROTE {NB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
