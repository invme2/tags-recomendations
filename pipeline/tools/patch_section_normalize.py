#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_section_normalize.py — normalize Designer output keys BEFORE they are
cached into dynamic_schemas / pushed as metafields. Fixes the "Designer keeps
inventing the same junk sections" problem:
  - typo/variant keys that shadow real sections: timerline->timeline,
    comparison->compare, ingredients_explanation->ingredients, idline->timeline
  - photo-brief slots leaked as top-level keys (inline_hero, inline_story_1,
    inline-cta, inline_photo_briefs, ...) -> dropped (they belong in photo_briefs)
  - explicit junk placeholders (variant_key, additional_keys) -> dropped

Inserted right before the new-key capture loop (cell ce20f070). nbformat +
snapshot + ast.parse. Idempotent.
"""
from __future__ import annotations
import ast, sys, nbformat
from pathlib import Path

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL_ID = "ce20f070"
ANCHOR = "Capture any NEW keys Designer emitted"
MARK = "_SECTION_ALIAS = {'timerline'"

BLOCK_REL = """# -- Normalize Designer keys BEFORE caching/section-build: drop photo-brief
# leaks (inline_* slots dumped as top-level keys) and fix typo/variant keys
# that shadow real sections (timerline->timeline, comparison->compare). Stops
# junk metafields + stops the dynamic-schema cache perpetuating them.
_SECTION_ALIAS = {'timerline': 'timeline', 'comparison': 'compare', 'ingredients_explanation': 'ingredients', 'idline': 'timeline'}
_JUNK_DROP = {'variant_key', 'additional_keys'}
def _is_photobrief_shape(_v):
    if isinstance(_v, dict):
        _ks = set(_v.keys())
        return bool(_ks) and _ks <= {'image_url', 'image_alt', 'source_index', 'slot', 'concept', 'edit_instructions', 'id', 'caption', 'alt'}
    if isinstance(_v, list) and _v:
        return all(_is_photobrief_shape(_x) for _x in _v)
    return False
if isinstance(designer_resp, dict):
    for _bad, _good in _SECTION_ALIAS.items():
        if _bad in designer_resp:
            if not designer_resp.get(_good):
                designer_resp[_good] = designer_resp.pop(_bad)
            else:
                designer_resp.pop(_bad, None)
    for _jk in [_k for _k in list(designer_resp.keys()) if _k not in _DESIGNER_HARDCODED_KEYS and (_k in _JUNK_DROP or re.match(r'^inline[-_]', _k) or 'inline_photo' in _k or _k.endswith('_inline_photos') or _is_photobrief_shape(designer_resp.get(_k)))]:
        designer_resp.pop(_jk, None)
"""


def main():
    nb = nbformat.read(NB, as_version=4)
    cell = next(c for c in nb.cells if c.get("id") == CELL_ID)
    src = cell.source
    if MARK in src:
        print("already applied — skip"); return 0
    lines = src.split("\n")
    idx = next((i for i, l in enumerate(lines) if ANCHOR in l), None)
    if idx is None:
        raise SystemExit("anchor not found")
    base = len(lines[idx]) - len(lines[idx].lstrip(" "))
    block = [(" " * base + ln) if ln.strip() else "" for ln in BLOCK_REL.split("\n")]
    while block and block[-1] == "":
        block.pop()
    block.append("")  # blank line before the anchor comment
    lines[idx:idx] = block
    new_src = "\n".join(lines)
    ast.parse(new_src)
    print(f"  inserted normalization ({len(block)} lines) at line {idx}, base={base}; ast.parse OK")
    cell.source = new_src
    nbformat.write(nb, NB)
    print(f"WROTE {NB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
