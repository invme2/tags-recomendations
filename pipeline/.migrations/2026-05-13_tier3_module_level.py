"""Tier 3 hygiene migration:
  - _PHOTO_FUNNEL_ORDER + _PhotoPackSkipped → module-level (Cell 2 helpers)
  - Silent-truncation warnings for _all_eprolo_d[:14] cap + source [:50] caps
"""
from __future__ import annotations
from pathlib import Path
import nbformat

NB = Path("/home/user/tags-recomendations/pipeline/Shopify_Pipeline.ipynb")

# ============================================================
# Cell 2 — add module-level constants near the other shared state
# ============================================================
CELL2_ANCHOR = '''_PW_STATE = {"pw": None, "browser": None, "ctx": None}'''

CELL2_NEW = '''_PW_STATE = {"pw": None, "browser": None, "ctx": None}

# Photo-pack funnel order — used by Step 4.5 to sort briefs before naming
# files. Module-level so it isn't rebuilt on every product iteration; also
# easier for tests to import + reason about.
_PHOTO_FUNNEL_ORDER = [
    'carousel-hero', 'carousel-lifestyle', 'carousel-in-use',
    'carousel-detail', 'carousel-scale',
    'inline-hero', 'inline-story-1', 'inline-story-2', 'inline-story-3',
    'inline-feature', 'inline-cta',
]
_PHOTO_FUNNEL_IDX = {s: i for i, s in enumerate(_PHOTO_FUNNEL_ORDER)}


class _PhotoPackSkipped(Exception):
    """Sentinel: graceful skip mid-build in Step 4.5 (e.g. all downloads
    failed). Caught separately from real errors so logs stay clean.
    Module-level so the class identity is stable across resume / retry."""
    pass'''

# ============================================================
# Cell 6 — remove the local _FUNNEL_ORDER definition, reuse module-level.
# Also remove the local class _PhotoPackSkipped definition.
# Add silent-truncation warnings.
# ============================================================
EDITS_CELL6 = [
    # Remove local _FUNNEL_ORDER + _funnel_idx (now module-level _PHOTO_FUNNEL_*)
    (
        '''                    # Sort by carousel conversion funnel — filenames `01-...` `02-...`
                    # now reflect the order the operator should drop into Shopify carousel.
                    # Unknown slots go after, preserving Designer's emission order.
                    _FUNNEL_ORDER = [
                        'carousel-hero', 'carousel-lifestyle', 'carousel-in-use',
                        'carousel-detail', 'carousel-scale',
                        'inline-hero', 'inline-story-1', 'inline-story-2', 'inline-story-3',
                        'inline-feature', 'inline-cta',
                    ]
                    _funnel_idx = {s: i for i, s in enumerate(_FUNNEL_ORDER)}
                    _resolved.sort(key=lambda rb: _funnel_idx.get(rb[0].get('slot', '') or '', 999))''',
        '''                    # Sort by carousel conversion funnel (module-level _PHOTO_FUNNEL_IDX).
                    # Filenames `01-...`, `02-...` reflect the order the operator should
                    # drop into Shopify carousel. Unknown slots go after (key=999).
                    _resolved.sort(key=lambda rb: _PHOTO_FUNNEL_IDX.get(rb[0].get('slot', '') or '', 999))''',
    ),
    # Remove the local class _PhotoPackSkipped declaration — now module-level.
    (
        '''        if pstatus == 'html_ready':
            class _PhotoPackSkipped(Exception):
                """Sentinel: graceful skip mid-build (e.g. all downloads failed).
                Caught separately from real errors so logs stay clean."""
                pass
            try:''',
        '''        if pstatus == 'html_ready':
            # _PhotoPackSkipped is now module-level (Cell 2).
            try:''',
    ),
    # Warn when EPROLO has > 14 photos so operator knows Designer cap is hit.
    (
        '''            _all_eprolo_d = (_img_data_for_designer.get('top') or []) + (_img_data_for_designer.get('desc') or [])
            _vision_imgs_d = {ii.get('index'): ii for ii in _stage1_for_designer.get('images', [])}
            _eprolo_list = []
            for _i, _img in enumerate(_all_eprolo_d[:14]):''',
        '''            _all_eprolo_d = (_img_data_for_designer.get('top') or []) + (_img_data_for_designer.get('desc') or [])
            if len(_all_eprolo_d) > 14:
                print(f'    \\u26a0 EPROLO has {len(_all_eprolo_d)} photos but Designer sees first 14 (token-budget cap). Photos 15-{len(_all_eprolo_d)} ignored for source_index selection.')
            _vision_imgs_d = {ii.get('index'): ii for ii in _stage1_for_designer.get('images', [])}
            _eprolo_list = []
            for _i, _img in enumerate(_all_eprolo_d[:14]):''',
    ),
    # Warn when custom.source image_urls cap [:50] truncates
    (
        '''                            'cost_price_usd': product.get('cost_price', 0),
                            'image_urls': {
                                'top':  list(product.get('top_image_urls')  or [])[:50],
                                'desc': list(product.get('desc_image_urls') or [])[:50],
                            },''',
        '''                            'cost_price_usd': product.get('cost_price', 0),
                            'image_urls': {
                                'top':  list(product.get('top_image_urls')  or [])[:50],
                                'desc': list(product.get('desc_image_urls') or [])[:50],
                            },
                        }
                        # Surface silent truncation so operator can decide whether
                        # to raise the cap. Storefront cares about top photos most.
                        _src_top_n  = len(product.get('top_image_urls')  or [])
                        _src_desc_n = len(product.get('desc_image_urls') or [])
                        if _src_top_n > 50 or _src_desc_n > 50:
                            print(f'    \\u26a0 source metafield: truncated top {_src_top_n}\\u219250, desc {_src_desc_n}\\u219250 (custom.source [:50] cap)')
                        _src_meta_post_check = {
                            'platform':       'EPROLO',
                            'url':            purl or '',''',
    ),
]

# The last edit needs careful merging because it inserts a print + duplicates
# the dict opening. Simpler: do it as two separate edits — first add the
# warning, then keep the existing dict intact. Let me redo:
EDITS_CELL6 = EDITS_CELL6[:3]  # keep first 3; redo image_urls warning below

# Different approach: append warning right AFTER the dict closes + before
# `_sections['source']`.
EDITS_CELL6.append((
    '''                            'image_urls': {
                                'top':  list(product.get('top_image_urls')  or [])[:50],
                                'desc': list(product.get('desc_image_urls') or [])[:50],
                            },
                        }
                        _sections['source'] = _src_meta''',
    '''                            'image_urls': {
                                'top':  list(product.get('top_image_urls')  or [])[:50],
                                'desc': list(product.get('desc_image_urls') or [])[:50],
                            },
                        }
                        # Surface silent truncation — operator can decide whether to
                        # widen the [:50] cap. EPROLO occasionally returns 60-80 desc
                        # image URLs; rest are dropped from the audit record.
                        _src_top_n  = len(product.get('top_image_urls')  or [])
                        _src_desc_n = len(product.get('desc_image_urls') or [])
                        if _src_top_n > 50 or _src_desc_n > 50:
                            print(f'    \\u26a0 custom.source image_urls truncated (top {_src_top_n}\\u219250, desc {_src_desc_n}\\u219250)')
                        _sections['source'] = _src_meta''',
))


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cells = {c.get("id"): c for c in nb.cells if c.cell_type == "code"}

    c2 = cells.get("b810afd7")
    if CELL2_ANCHOR not in c2["source"]:
        print("ERR: CELL2_ANCHOR missing"); return 1
    c2["source"] = c2["source"].replace(CELL2_ANCHOR, CELL2_NEW, 1)

    c6 = cells.get("ce20f070")
    for old, new in EDITS_CELL6:
        if old not in c6["source"]:
            print(f"ERR: cell 6 anchor missing:\n{old[:140]}...")
            return 2
        c6["source"] = c6["source"].replace(old, new, 1)

    nbformat.write(nb, NB)
    print("✅ Tier 3 applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
