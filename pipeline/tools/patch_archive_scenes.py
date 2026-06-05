#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_archive_scenes.py — add a FREE tier-2 to the reviews builder: derive
product-specific review scenes from the product's OWN photo_briefs (already in
the archive/meta) instead of a paid DeepSeek call. Priority becomes:
  1) meta.review_scenes (Designer / new products)
  2) derive from meta.photo_briefs lifestyle/in-use/inline concepts  <-- NEW, free
  3) category fallback top-up to 8

Notebook edit via nbformat (+ snapshot taken). ast.parse validated. Idempotent.
"""
from __future__ import annotations
import ast, sys, nbformat
from pathlib import Path

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL_ID = "ce20f070"
I = " " * 32  # base indent of the reviews block statements

A_OLD = I + "_used_designer = len(_scenes_src) >= 6"
A_NEW = "\n".join([
    I + "_used_designer = len(_scenes_src) >= 6",
    I + "_n_designer = len(_scenes_src)",
    I + "# tier-2: derive product-specific scenes from the product's OWN photo_briefs",
    I + "# already in the archive/meta (FREE — no API call, no re-parse).",
    I + "if len(_scenes_src) < 6:",
    I + "    _SCENE_SLOTS = ('carousel-lifestyle', 'carousel-in-use', 'inline-hero', 'inline-story-1', 'inline-story-2', 'inline-story-3', 'inline-cta', 'inline-lifestyle', 'inline-room-placement')",
    I + "    _SLOT_TITLE = {'carousel-lifestyle': 'In real life', 'carousel-in-use': 'Mid-use moment', 'inline-hero': 'In the moment', 'inline-story-1': 'Real-life story', 'inline-story-2': 'A few weeks in', 'inline-story-3': 'The payoff', 'inline-cta': 'Why it stays out', 'inline-lifestyle': 'Everyday use', 'inline-room-placement': 'In its place'}",
    I + "    _SKIP_KW = ('diagram', 'infographic', 'chart', 'illustration', 'anatomical', 'schematic', 'callout', 'overlay', 'before/after', 'comparison', 'white seamless')",
    I + "    _seen_t = set(_t.lower() for _t, _ in _scenes_src)",
    I + "    for _b in (_meta_for_rev.get('photo_briefs') or []):",
    I + "        if not isinstance(_b, dict):",
    I + "            continue",
    I + "        _sl = _b.get('slot', '')",
    I + "        if _sl not in _SCENE_SLOTS:",
    I + "            continue",
    I + "        _c = (_b.get('concept') or '').strip()",
    I + "        if not _c or any(_k in _c.lower() for _k in _SKIP_KW):",
    I + "            continue",
    I + "        _ti = _SLOT_TITLE.get(_sl, 'In real life')",
    I + "        while _ti.lower() in _seen_t:",
    I + "            _ti = _ti + ' +'",
    I + "        _seen_t.add(_ti.lower())",
    I + "        _scenes_src.append((_ti, ['Candid iPhone-snapshot version of this real product moment: ' + _c[:170], 'Real lived-in setting, a little clutter, phone-camera look — NOT studio, NO overlay text.']))",
    I + "_n_archive = len(_scenes_src) - _n_designer",
])
A_MARK = "_n_archive = len(_scenes_src) - _n_designer"

B_OLD = I + "_scene_source = 'Designer (product-specific)' if _used_designer else ('category fallback: %s' % (_bucket or 'generic'))"
B_NEW = "\n".join([
    I + "if _n_designer >= 6:",
    I + "    _scene_source = 'Designer (product-specific)'",
    I + "elif _n_archive > 0:",
    I + "    _scene_source = 'archive photo_briefs (%d) + category top-up [%s]' % (_n_archive, _bucket or 'generic')",
    I + "else:",
    I + "    _scene_source = 'category fallback: %s' % (_bucket or 'generic')",
])
B_MARK = "archive photo_briefs (%d) + category top-up"


def repl(src, name, old, new, mark):
    if mark in src:
        print(f"  EDIT {name}: already applied — skip"); return src
    if src.count(old) != 1:
        raise SystemExit(f"EDIT {name}: anchor count {src.count(old)} (want 1)")
    print(f"  EDIT {name}: applied")
    return src.replace(old, new, 1)


def main():
    nb = nbformat.read(NB, as_version=4)
    cell = next(c for c in nb.cells if c.get("id") == CELL_ID)
    src = cell.source
    orig = src
    src = repl(src, "A", A_OLD, A_NEW, A_MARK)
    src = repl(src, "B", B_OLD, B_NEW, B_MARK)
    if src == orig:
        print("No changes."); return 0
    ast.parse(src)
    print("  ast.parse OK")
    cell.source = src
    nbformat.write(nb, NB)
    print(f"WROTE {NB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
