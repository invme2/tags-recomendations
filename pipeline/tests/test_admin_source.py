"""Tests for the admin-only `custom.source` metafield.

Stores the EPROLO provenance record per product (URL, scraped title/description,
cost price, image URL lists). NEVER rendered on storefront — only visible in
Shopify Admin → Product → Metafields, so the operator can audit which EPROLO
listing each product was scraped from.
"""
from __future__ import annotations

import re
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"


@pytest.fixture(scope="module")
def cells() -> dict:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    return {c.get("id"): c["source"] for c in nb.cells if c.cell_type == "code"}


# ============================================================
# Cell 2: definition exists and is admin-only
# ============================================================

def test_cell2_creates_source_definition(cells: dict) -> None:
    """Cell 2 must declare the custom.source metafield definition."""
    c2 = cells["b810afd7"]
    assert "('source'," in c2, (
        "Cell 2 must create custom.source metafield definition"
    )
    assert "'Wanelo · Source'" in c2, "Source metafield must have a human title"


def test_source_definition_is_json_type(cells: dict) -> None:
    """Source metafield is a JSON object — same default type as the rest.
    Only photo_pack is overridden to 'url'; source stays in the json default."""
    c2 = cells["b810afd7"]
    pat = re.compile(r"_wanelo_metafields\s*=\s*\[(.*?)\n\s{4}\]", re.DOTALL)
    m = pat.search(c2)
    assert m, "_wanelo_metafields list not found"
    assert "'source'" in m.group(1)
    # Cell 2 uses _type_overrides for per-key type and defaults to 'json'.
    # 'source' must NOT appear in the overrides — staying on the json default.
    ov = re.search(r"_type_overrides\s*=\s*\{([^}]+)\}", c2)
    assert ov, "_type_overrides dict not found"
    assert "'source'" not in ov.group(1), (
        "source must not be in _type_overrides — it should stay json"
    )
    assert "_type_overrides.get(_k, 'json')" in c2, (
        "Loop must use _type_overrides.get with 'json' default"
    )


def test_source_is_admin_only(cells: dict) -> None:
    """Cell 2 must include 'source' in the _admin_only set so the metafield
    is created with visible_to_storefront=False."""
    c2 = cells["b810afd7"]
    m = re.search(r"_admin_only\s*=\s*\{([^}]+)\}", c2)
    assert m, "_admin_only set declaration not found"
    members = {s.strip().strip("'\"") for s in m.group(1).split(',') if s.strip()}
    assert "source" in members, (
        f"'source' must be in _admin_only; got {members}. "
        "Without this it would leak provenance data via Storefront API."
    )


def test_source_count_in_print(cells: dict) -> None:
    """Cell 2 print message should reflect new admin-only count."""
    c2 = cells["b810afd7"]
    assert "2 admin-only" in c2 or "photo_pack ZIP + source" in c2, (
        "Print message should advertise both admin-only metafields"
    )


# ============================================================
# Cell 6: source dict built and pushed
# ============================================================

def test_step5_builds_source_meta(cells: dict) -> None:
    """Step 5 must build _src_meta dict from the scraped product before
    metafieldsSet runs."""
    c6 = cells["ce20f070"]
    assert "_src_meta" in c6, "Step 5 must build _src_meta dict"
    assert "'platform'" in c6 and "'EPROLO'" in c6


def test_source_meta_includes_url(cells: dict) -> None:
    """The source URL is the most important field — operator clicks it
    in Admin to view the original listing."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_src_meta\s*=\s*\{(.*?)\}", re.DOTALL)
    m = pat.search(c6)
    assert m, "_src_meta dict literal not found"
    assert "'url'" in m.group(1)
    assert "purl" in m.group(1), "url field must come from purl (eprolo_url)"


def test_source_meta_includes_title_and_description(cells: dict) -> None:
    """Scraped title + description are the primary audit fields."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_src_meta\s*=\s*\{(.*?)\}", re.DOTALL)
    m = pat.search(c6)
    assert m
    body = m.group(1)
    assert "'title'" in body
    assert "'description'" in body


def test_source_meta_caps_description_length(cells: dict) -> None:
    """Source description must be capped — EPROLO descriptions can be huge,
    Shopify metafield JSON has size limits."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_src_meta\s*=\s*\{(.*?)\}", re.DOTALL)
    m = pat.search(c6)
    assert m
    body = m.group(1)
    assert "[:5000]" in body, "description must be capped at 5000 chars"
    assert "[:200]" in body, "title must be capped at 200 chars"


def test_source_meta_includes_image_urls(cells: dict) -> None:
    """Both top + desc image URL lists must be preserved so operator can
    cross-check exactly which photos were scraped."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_src_meta\s*=\s*\{(.*?)\}", re.DOTALL)
    m = pat.search(c6)
    assert m
    body = m.group(1)
    assert "'image_urls'" in body
    assert "top_image_urls" in body
    assert "desc_image_urls" in body


def test_source_meta_includes_cost_price(cells: dict) -> None:
    """Source must record the EPROLO cost price as scraped — useful for
    later margin audits."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_src_meta\s*=\s*\{(.*?)\}", re.DOTALL)
    m = pat.search(c6)
    assert m
    assert "'cost_price_usd'" in m.group(1)


def test_source_build_is_non_blocking(cells: dict) -> None:
    """If the source dict build itself fails (weird scrape JSON), the
    pipeline must still push the rest of the metafields — provenance is
    a nice-to-have, not a blocker.

    Tier 3 inserted a truncation-warning print between the dict and the
    _sections['source'] assignment, so the regex tolerates either form.
    """
    c6 = cells["ce20f070"]
    pat = re.compile(
        r"_src_meta\s*=\s*\{.*?\}.*?_sections\['source'\]\s*=\s*_src_meta.*?except Exception",
        re.DOTALL,
    )
    assert pat.search(c6), (
        "source build must be wrapped in try/except so a failure doesn't "
        "break the metafieldsSet batch"
    )


def test_source_in_wanelo_keys(cells: dict) -> None:
    """The metafieldsSet loop must iterate over 'source' so it actually
    gets pushed to Shopify."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_wanelo_keys\s*=\s*\[(.*?)\]", re.DOTALL)
    m = pat.search(c6)
    assert m, "_wanelo_keys list not found in Step 5"
    assert "'source'" in m.group(1), (
        "_wanelo_keys must include 'source' so it's pushed to Shopify"
    )


def test_wanelo_keys_total_is_41(cells: dict) -> None:
    """Sanity: _wanelo_keys is the GROWING set of metafield keys. By design the
    catalog adds keys over time (different product categories need different
    metafields), so this is a FLOOR check (>= baseline), not an exact count —
    plus the must-have admin/storefront keys below."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_wanelo_keys\s*=\s*\[(.*?)\]", re.DOTALL)
    m = pat.search(c6)
    assert m
    keys = re.findall(r"'(\w+)'", m.group(1))
    assert len(keys) >= 41, f"expected >= 41 metafield keys, got {len(keys)}: {keys}"
    assert keys.count("source") == 1
    assert keys.count("photo_pack") == 1
    assert keys.count("source_url") == 1
    assert keys.count("designer_prompt") == 1
    assert keys.count("videos") == 1
    assert keys.count("research_refs") == 1, (
        "research_refs storefront metafield (auto-generated by Opus Strategy "
        "per category) must be in _wanelo_keys for metafieldsSet push"
    )


# ============================================================
# Storefront markup must NOT reference source
# ============================================================

def test_no_liquid_snippet_references_source() -> None:
    """No snippet should read product.metafields.custom.source — that's the
    whole point of admin-only."""
    snippets_dir = ROOT / "pipeline" / "theme_assets" / "snippets"
    pat = re.compile(r"metafields\.custom\.source\b")
    for snippet_path in snippets_dir.glob("*.liquid"):
        content = snippet_path.read_text(encoding="utf-8")
        assert not pat.search(content), (
            f"{snippet_path.name}: must NOT reference custom.source — "
            "source is admin-only EPROLO provenance, not page content"
        )


def test_master_section_does_not_render_source() -> None:
    """The master product-page section must not list source among its
    rendered snippets."""
    section = (ROOT / "pipeline" / "theme_assets" / "sections" /
               "wanelo-product-page.liquid").read_text(encoding="utf-8")
    pat = re.compile(r"metafields\.custom\.source\b|render\s+'wanelo-source'")
    assert not pat.search(section), (
        "Master section must not render source — it's admin-only provenance"
    )
