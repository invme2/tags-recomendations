"""Tests for cross-collection SEO interlinking — silo structure.

Verifies:
  - Cell 2 declares the COLLECTION-scoped custom.related_collections metafield
  - Cell 2 ships the _compute_collection_related graph algorithm
  - Cell 4 cross-link step writes the metafield + appends inline-mention HTML
  - Theme section wanelo-collection-related.liquid renders the chip-row
  - Algorithm correctness (synthetic 4-collection fixture)
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
THEME = ROOT / "pipeline" / "theme_assets"


@pytest.fixture(scope="module")
def cells() -> dict:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    return {c.get("id"): c["source"] for c in nb.cells if c.cell_type == "code"}


# ============================================================
# Cell 2 — metafield definition + helper function
# ============================================================

def test_cell2_declares_collection_metafield(cells: dict) -> None:
    """Collection-level metafield definition must exist with COLLECTION
    owner_type — Shopify rejects setting a metafield on a Collection if
    the definition was scoped to PRODUCT."""
    c2 = cells["b810afd7"]
    assert "_wanelo_coll_metafields" in c2
    assert "('related_collections'" in c2
    assert "owner_type='COLLECTION'" in c2 or 'owner_type="COLLECTION"' in c2, (
        "Collection metafield definition must use owner_type=COLLECTION"
    )


def test_cell2_collection_metafield_is_storefront_visible(cells: dict) -> None:
    """Related collections must be readable by the Liquid theme — not
    admin-only. Otherwise the chip-row section can't render."""
    c2 = cells["b810afd7"]
    # Block where collection metafields are ensured; visible_to_storefront=True
    pat = re.compile(
        r"_wanelo_coll_metafields.*?visible_to_storefront=True",
        re.DOTALL,
    )
    assert pat.search(c2), (
        "Collection metafield loop must pass visible_to_storefront=True"
    )


def test_cell2_has_compute_helper(cells: dict) -> None:
    """The graph algorithm must be defined as a regular helper in Cell 2."""
    c2 = cells["b810afd7"]
    assert "def _compute_collection_related(" in c2, (
        "_compute_collection_related helper missing from Cell 2"
    )


def test_compute_helper_uses_reciprocity(cells: dict) -> None:
    """The helper must symmetrize the adjacency (A→B implies B→A) so
    SEO authority flows both ways. Critical for the silo to work."""
    c2 = cells["b810afd7"]
    # Look inside the function body for reciprocity comments + the
    # symmetric-closure block.
    assert "reciprocity" in c2.lower()
    assert "Symmetric closure" in c2 or "symmetric closure" in c2.lower()


def test_compute_helper_uses_hub_detection(cells: dict) -> None:
    """Helper must compute in-degree per handle and flag hubs (top ~15%)."""
    c2 = cells["b810afd7"]
    assert "in_deg" in c2, "Must compute in-degree per handle"
    assert "is_hub" in c2, "Output must have is_hub flag"
    assert "hub" in c2.lower()


def test_compute_helper_uses_anchor_variety(cells: dict) -> None:
    """Helper must cycle through anchor types (exact title / keyword /
    generic 'explore X') so we don't over-optimize a single anchor."""
    c2 = cells["b810afd7"]
    assert "idx % 4" in c2, "Anchor variety should cycle every 4 items"
    assert "Shop all" in c2, "Hub anchor should use 'Shop all' phrasing"
    assert "explore " in c2, "Generic anchor should use 'explore X' phrasing"


# ============================================================
# Cell 4 — post-creation cross-linking step
# ============================================================

def test_cell4_invokes_compute_helper(cells: dict) -> None:
    """Cell 4 must call _compute_collection_related on the collection rows."""
    c4 = cells["066bb296"]
    assert "_compute_collection_related(_ci_rows" in c4 or \
           "_compute_collection_related(coll_rows" in c4, (
        "Cell 4 must invoke the graph helper"
    )


def test_cell4_writes_related_collections_metafield(cells: dict) -> None:
    """Cell 4 must metafieldsSet 'related_collections' on each collection."""
    c4 = cells["066bb296"]
    assert "'key': 'related_collections'" in c4 or \
           '"key": "related_collections"' in c4
    assert "metafieldsSet" in c4
    # Type must be json since value is a list of dicts
    assert "'type': 'json'" in c4 or '"type": "json"' in c4


def test_cell4_appends_inline_mention_paragraph(cells: dict) -> None:
    """Cell 4 must append a 'Browse related' paragraph to each collection's
    descriptionHtml — that's the inline-mention SEO contribution."""
    c4 = cells["066bb296"]
    assert "wanelo-coll-also" in c4, (
        "Inline-mention paragraph must use wanelo-coll-also class for styling"
    )
    assert "collectionUpdate" in c4, "Must use collectionUpdate to write bodyHtml"
    assert "descriptionHtml" in c4


def test_cell4_inline_mention_is_idempotent(cells: dict) -> None:
    """Re-running cross-link step must NOT append the inline paragraph
    twice — guard via sentinel class check."""
    c4 = cells["066bb296"]
    assert "'wanelo-coll-also' not in _existing" in c4, (
        "Inline-mention writer must check for sentinel before re-appending"
    )


def test_cell4_rate_limited(cells: dict) -> None:
    """Shopify GraphQL has cost-based throttling — must sleep between
    per-collection updates to avoid 429s when collection count is high."""
    c4 = cells["066bb296"]
    # asyncio.sleep inside the cross-link loop
    pat = re.compile(
        r"Cross-collection SEO interlinking.*?asyncio\.sleep\(0\.\d+\)",
        re.DOTALL,
    )
    assert pat.search(c4), (
        "Cross-link loop must include asyncio.sleep for rate limiting"
    )


def test_cell4_requires_at_least_two_collections(cells: dict) -> None:
    """Graph computation only makes sense with ≥2 collections. With 0-1,
    the related list is empty so skip the whole step."""
    c4 = cells["066bb296"]
    assert "len(_ci_rows) >= 2" in c4


# ============================================================
# Theme — wanelo-collection-related.liquid section
# ============================================================

def test_collection_related_section_exists() -> None:
    """The collection-page section file must exist."""
    f = THEME / "sections" / "wanelo-collection-related.liquid"
    assert f.exists(), "wanelo-collection-related.liquid section missing"


def test_collection_related_section_reads_metafield() -> None:
    """Section must read collection.metafields.custom.related_collections."""
    f = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "collection.metafields.custom.related_collections" in f


def test_collection_related_section_has_skip_if_blank() -> None:
    """Empty metafield = section renders nothing, so it's safe to leave
    installed on every collection (including ones without related data yet)."""
    f = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "if related and related.size > 0" in f, (
        "Section must skip-if-blank on empty metafield"
    )


def test_collection_related_section_handles_hub_flag() -> None:
    """Liquid must branch on is_hub for distinctive styling."""
    f = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "r.is_hub" in f, "Section must check is_hub flag per item"
    assert "is-hub" in f, "Hub items must get .is-hub class"


def test_collection_related_section_uses_anchor_with_title_fallback() -> None:
    """Anchor text from the data, but fall back to title if anchor empty."""
    f = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "r.anchor | default: r.title" in f


def test_collection_related_section_has_shopify_section_schema() -> None:
    """Must include {% schema %} block so operator can install via Customize.
    Section schema 'name' field is capped at 25 chars by Shopify, so we use
    the truncated 'Wanelo Related Coll' label (was 'Wanelo Related Collections'
    before — rejected by Shopify with 'name is too long' at upload)."""
    f = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "{% schema %}" in f
    assert '"Wanelo Related Coll"' in f


# ============================================================
# CSS styling
# ============================================================

def test_css_styles_collection_related_section() -> None:
    """CSS must define .wanelo-coll-related rules (chip-row layout)."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-coll-related" in css
    assert ".wanelo-coll-related__list" in css


def test_css_styles_hub_chips_distinctly() -> None:
    """Hub chips must be visually distinct from regular chips."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-coll-related__item.is-hub a" in css, (
        "Hub chips must have distinct CSS rules"
    )


def test_css_styles_inline_browse_related_paragraph() -> None:
    """The inline-mention paragraph appended to collection bodyHtml must
    have its own CSS class (wanelo-coll-also) so it's styled like text,
    not a UI button."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-coll-also" in css


# ============================================================
# Algorithm correctness — synthetic 4-collection fixture
# ============================================================

@pytest.fixture(scope="module")
def compute_helper(cells: dict):
    """Extract and exec the helper from the notebook source so we can call
    it directly on synthetic data."""
    c2 = cells["b810afd7"]
    # Find the function body
    start = c2.find("def _compute_collection_related(")
    assert start != -1
    end = c2.find("\n# ════ v10.0: ALWAYS-IN-STOCK (dropshipping mode) ════", start)
    assert end != -1
    src = c2[start:end]
    mod = types.ModuleType("synth_compute")
    exec(src, mod.__dict__)
    return mod._compute_collection_related


def _make_row(handle: str, title: str, keywords: str = "", volume: int = 100):
    """Build a dict that looks like a sqlite3.Row for the helper.

    Must support r['key'] AND `'key' in r.keys()` access — the helper does
    both. dict already supports both.
    """
    return {
        'seo_handle': handle,
        'seo_title': title,
        'original_name': title,
        'top_keywords': keywords,
        'total_volume': volume,
        'shopify_collection_id': f"gid://shopify/Collection/{handle}",
    }


def test_algorithm_basic_overlap(compute_helper) -> None:
    """Two collections sharing title words must end up related to each other."""
    rows = [
        _make_row('neck-fans', 'Neck Fans', 'neck fan,portable cooling,bladeless fan'),
        _make_row('desk-fans', 'Desk Fans', 'desk fan,office fan,small fan'),
        _make_row('water-bottles', 'Water Bottles', 'water bottle,bpa free'),
    ]
    out = compute_helper(rows, k=3, cap=4)
    # neck-fans and desk-fans share "fans" in title → related
    nf_rel = {r['handle'] for r in out.get('neck-fans', [])}
    df_rel = {r['handle'] for r in out.get('desk-fans', [])}
    assert 'desk-fans' in nf_rel, "neck-fans → desk-fans (shared 'fans')"
    assert 'neck-fans' in df_rel, "desk-fans → neck-fans (shared 'fans')"
    # water-bottles is unrelated to fans (no overlap)
    wb_rel = {r['handle'] for r in out.get('water-bottles', [])}
    assert 'neck-fans' not in wb_rel
    assert 'desk-fans' not in wb_rel


def test_algorithm_reciprocity_guaranteed(compute_helper) -> None:
    """For every A→B in the output graph, B→A must also exist."""
    rows = [
        _make_row('neck-fans', 'Neck Fans', 'neck fan,portable fan'),
        _make_row('desk-fans', 'Desk Fans', 'desk fan,office fan'),
        _make_row('mini-fans', 'Mini Fans', 'mini fan,portable fan'),
        _make_row('floor-fans', 'Floor Fans', 'floor fan,large fan'),
        _make_row('ceiling-fans', 'Ceiling Fans', 'ceiling fan,room fan'),
    ]
    out = compute_helper(rows, k=4, cap=8)
    for a, items in out.items():
        for it in items:
            b = it['handle']
            b_rel = {r['handle'] for r in out.get(b, [])}
            assert a in b_rel, (
                f"Reciprocity broken: {a!r} → {b!r} exists but {b!r} → {a!r} missing"
            )


def test_algorithm_hub_detection(compute_helper) -> None:
    """A hub collection must have a keyword set that is a SUPERSET of
    spoke keywords — that's the realistic shape ("All Fans" knows every
    sub-category name). The algorithm should pick it up as the central
    node via weighted in-degree on the natural (pre-reciprocity) graph.
    """
    rows = [
        # Hub: keyword superset covering every spoke specifier.
        _make_row('all-fans', 'All Fans Collection',
                  'fan,cooling,airflow,neck cooling,desk fan,mini fan,floor fan,ceiling fan,handheld fan,tower fan',
                  volume=10000),
        _make_row('neck-fans', 'Neck Fans', 'neck fan,fan'),
        _make_row('desk-fans', 'Desk Fans', 'desk fan,fan'),
        _make_row('mini-fans', 'Mini Fans', 'mini fan,fan'),
        _make_row('floor-fans', 'Floor Fans', 'floor fan,fan'),
        _make_row('ceiling-fans', 'Ceiling Fans', 'ceiling fan,fan'),
        _make_row('handheld-fans', 'Handheld Fans', 'handheld fan,fan'),
        _make_row('tower-fans', 'Tower Fans', 'tower fan,fan'),
    ]
    out = compute_helper(rows, k=5, cap=8)
    # all-fans should accumulate weighted-in-degree from many spokes
    # → flagged is_hub in their related lists.
    spoke_handles = ['neck-fans', 'desk-fans', 'mini-fans', 'floor-fans']
    flagged_as_hub = 0
    for spoke in spoke_handles:
        for item in out.get(spoke, []):
            if item['handle'] == 'all-fans' and item.get('is_hub'):
                flagged_as_hub += 1
                break
    assert flagged_as_hub >= 2, (
        f"Hub detection should flag central node from multiple spokes; "
        f"got {flagged_as_hub} hub-flagged references to all-fans"
    )


def test_algorithm_anchor_variety(compute_helper) -> None:
    """Anchor texts in a single collection's related list must NOT all be
    identical — variety prevents over-optimization."""
    rows = [
        _make_row('fans', 'Fans', 'fan,cooling fan,portable fan,desk fan,neck fan'),
        _make_row('a1', 'A1 Fan Variant', 'a1 fan,small fan'),
        _make_row('a2', 'A2 Fan Variant', 'a2 fan,medium fan'),
        _make_row('a3', 'A3 Fan Variant', 'a3 fan,large fan'),
        _make_row('a4', 'A4 Fan Variant', 'a4 fan,huge fan'),
        _make_row('a5', 'A5 Fan Variant', 'a5 fan,quiet fan'),
    ]
    out = compute_helper(rows, k=5, cap=8)
    fans_related = out.get('fans', [])
    assert len(fans_related) >= 3, "Expected multiple related entries"
    anchors = {item['anchor'] for item in fans_related}
    assert len(anchors) >= 2, (
        f"Anchor texts should vary across related items; got: {anchors}"
    )


def test_algorithm_score_descending(compute_helper) -> None:
    """Within each collection's related list, non-hub items should be sorted
    by score descending (hubs may appear above by hub-priority)."""
    rows = [
        _make_row('fans', 'Fans cooling air', 'fan,cooling,air'),
        _make_row('weakly-related', 'Weakly Related', 'fan'),  # 1 overlap
        _make_row('strongly-related', 'Strongly Related cooling air', 'cooling,air'),  # 3 overlaps
        _make_row('mid-related', 'Mid Related air', 'air'),  # 2 overlap
    ]
    out = compute_helper(rows, k=5, cap=8)
    fans_items = out['fans']
    # Among non-hub items, scores should descend
    non_hub_scores = [r['score'] for r in fans_items if not r.get('is_hub')]
    assert non_hub_scores == sorted(non_hub_scores, reverse=True), (
        f"Non-hub items not score-descending: {non_hub_scores}"
    )


def test_algorithm_no_self_links(compute_helper) -> None:
    """A collection must never appear in its own related list."""
    rows = [
        _make_row('a', 'A B C', 'a,b,c'),
        _make_row('b', 'A B D', 'a,b,d'),
        _make_row('c', 'A C D', 'a,c,d'),
    ]
    out = compute_helper(rows, k=5, cap=8)
    for handle, items in out.items():
        for r in items:
            assert r['handle'] != handle, (
                f"Self-link in {handle}'s related list"
            )


def test_algorithm_empty_input_safe(compute_helper) -> None:
    """Empty input must return empty dict, not crash."""
    out = compute_helper([], k=5, cap=8)
    assert out == {}


def test_algorithm_single_collection_no_relations(compute_helper) -> None:
    """A single collection has no peers → empty related list."""
    out = compute_helper([_make_row('only', 'Only Collection', 'kw1,kw2')], k=5, cap=8)
    assert out == {'only': []}
