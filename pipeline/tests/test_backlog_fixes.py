"""Tests for the 9-fix backlog applied from session audit.

  #1  Designer prompt: no shipping/returns/refund/delivery
  #2  Designer prompt: compare module hallucination rule
  #3  body_html sanitize raw EPROLO description fallback
  #4  Augmented Product schema (JSON-LD) snippet
  #6  Image dedup in scrape_eprolo
  #7  MAX_DATAFORSEO_BUDGET env-configurable
  #8  Carousel reorder by Vision role before attach_media
  #10 Real-time cost checkpoint every 25 products
  #14 Designer prompt: spec source-tracing rule
"""
from __future__ import annotations

import re
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
# #1 — Designer prompt forbids shipping/returns/delivery/refund
# ============================================================

def test_designer_prompt_forbids_shipping_returns(cells: dict) -> None:
    """Designer must NEVER write shipping/returns/refund/secure-checkout
    content — operator handles those via a separate Shopify checkout-
    page module. Any mention on the PDP contradicts the actual policy."""
    c6 = cells["ce20f070"]
    assert "RULE (SHIPPING / RETURNS / REFUND)" in c6, (
        "Designer prompt must contain explicit no-shipping/returns rule"
    )
    # Specific words the prompt must forbid
    for forbidden in ("shipping cost", "return policy", "refund terms",
                      "money-back", "delivery times"):
        assert forbidden in c6.lower() or forbidden in c6, (
            f"Rule must list {forbidden!r} as forbidden"
        )


# ============================================================
# #2 — Compare module hallucination rule
# ============================================================

def test_designer_prompt_compare_hallucination_rule(cells: dict) -> None:
    """Compare module is high-risk because Designer has no source-of-
    truth for competitor numbers. Prompt must instruct Yes/No/Partial
    over specific invented numbers, and skip-module-entirely as fallback."""
    c6 = cells["ce20f070"]
    assert "RULE (COMPARE MODULE" in c6, (
        "Compare module rule must be present"
    )
    assert "Yes/No/Partial" in c6, (
        "Rule must explicitly suggest Yes/No/Partial cells"
    )
    assert "NEVER invent specific numbers" in c6, (
        "Rule must forbid invented numbers in competitor columns"
    )


# ============================================================
# #3 — body_html sanitize fallback
# ============================================================

def test_body_html_sanitizes_eprolo_fallback(cells: dict) -> None:
    """When Designer's meta.short_description is empty, fallback uses
    raw EPROLO description which can contain HTML / <img> / EPROLO URLs.
    Must strip tags + collapse whitespace before inserting into <p>."""
    c6 = cells["ce20f070"]
    assert "_raw_short" in c6, "Sanitize block must use _raw_short intermediate"
    assert "re.sub(r'<[^>]+>', '', _raw_short)" in c6, (
        "Must strip HTML tags via regex"
    )
    assert r"re.sub(r'\s+', ' '" in c6 or 're.sub(r"\\s+", " "' in c6, (
        "Must collapse whitespace via regex"
    )


# ============================================================
# #4 — Augmented Product schema (JSON-LD)
# ============================================================

def test_product_schema_snippet_exists() -> None:
    snip = THEME / "snippets" / "wanelo-product-schema.liquid"
    assert snip.exists(), "wanelo-product-schema.liquid must exist"


def test_product_schema_has_required_jsonld_fields() -> None:
    snip = (THEME / "snippets" / "wanelo-product-schema.liquid").read_text(encoding="utf-8")
    # Schema.org Product fields Google requires for rich snippets
    for field in ('"@type": "Product"', '"name":', '"description":',
                  '"image":', '"brand":', '"offers":', '"price":',
                  '"priceCurrency":', '"availability":'):
        assert field in snip, f"JSON-LD must declare {field}"


def test_product_schema_does_not_emit_fake_aggregate_rating() -> None:
    """The custom.reviews metafield is AI-generated content for visual
    social proof. Emitting it as schema.org aggregateRating would be
    FTC fraud territory — only safe to do once real reviews are wired
    via Judge.me / Loox / Yotpo. Scope the check to the JSON-LD body,
    not the Liquid comment block (which explains WHY we don't emit)."""
    snip = (THEME / "snippets" / "wanelo-product-schema.liquid").read_text(encoding="utf-8")
    # Find the <script type="application/ld+json"> ... </script> block
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  snip, re.DOTALL)
    assert m, "JSON-LD <script> block not found in snippet"
    jsonld_body = m.group(1)
    assert '"aggregateRating"' not in jsonld_body, (
        "Schema body must NOT emit aggregateRating from AI-generated reviews"
    )


def test_product_schema_rendered_by_master_section() -> None:
    section = (THEME / "sections" / "wanelo-product-page.liquid").read_text(encoding="utf-8")
    assert "{% render 'wanelo-product-schema' %}" in section, (
        "Master section must render wanelo-product-schema"
    )


# ============================================================
# #6 — Image dedup in scrape_eprolo
# ============================================================

def test_scrape_dedups_image_urls(cells: dict) -> None:
    """EPROLO sometimes returns the same photo URL 2-3 times. Without
    dedup, carousel + photo_pack ZIP contain duplicates."""
    c2 = cells["b810afd7"]
    # Method: dict.fromkeys preserves order, drops duplicates
    assert "list(dict.fromkeys(top))" in c2, (
        "scrape_eprolo must dedup top_image_urls via dict.fromkeys"
    )
    assert "list(dict.fromkeys(desc))" in c2, (
        "scrape_eprolo must dedup desc_image_urls"
    )


# ============================================================
# #7 — MAX_DATAFORSEO_BUDGET env-configurable
# ============================================================

def test_dataforseo_budget_is_env_tunable(cells: dict) -> None:
    """TOTAL_BUDGET was hardcoded $15. Now env-tunable via
    MAX_DATAFORSEO_BUDGET so operator can cap big batches without
    code edits — same pattern as MAX_ANTHROPIC_BUDGET."""
    c1 = cells["477e495d"]
    assert "MAX_DATAFORSEO_BUDGET" in c1
    assert "_safe_env_float('MAX_DATAFORSEO_BUDGET'" in c1


# ============================================================
# #8 — Carousel reorder by Vision role
# ============================================================

def test_gallery_sorted_by_vision_role(cells: dict) -> None:
    """Before shopify_attach_media, gallery must be sorted by Vision-
    assigned role so 'hero' goes first in Shopify carousel — provides
    editorial first impression even before operator runs the photo_pack
    edit workflow."""
    c6 = cells["ce20f070"]
    assert "_ROLE_PRIORITY" in c6
    # Specifically hero=0 priority
    assert "'hero':0" in c6 or "'hero': 0" in c6
    assert "_role_by_index" in c6, (
        "Must build index→role lookup from stage1.images"
    )
    # And the sort must use the priority lookup
    assert "_gallery_raw.sort(" in c6


def test_gallery_sort_covers_main_roles(cells: dict) -> None:
    """Role priority dict must cover the main role enum values Vision
    can emit (hero / lifestyle / in_use / feature / detail / packaging)."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"_ROLE_PRIORITY\s*=\s*\{([^}]+)\}")
    m = pat.search(c6)
    assert m, "_ROLE_PRIORITY dict not found"
    body = m.group(1)
    for role in ("hero", "lifestyle", "in_use", "detail", "packaging"):
        assert f"'{role}'" in body, f"_ROLE_PRIORITY missing role {role!r}"


# ============================================================
# #10 — Real-time cost checkpoint every 25 products
# ============================================================

def test_cost_checkpoint_function_defined(cells: dict) -> None:
    """Dispatcher must define _print_cost_checkpoint so operator sees
    cumulative spend live during the batch, not only at end-of-batch."""
    c6 = cells["ce20f070"]
    assert "def _print_cost_checkpoint(" in c6, (
        "Checkpoint helper must be defined"
    )
    # 25-product cadence
    assert "% 25" in c6, "Checkpoint must fire every 25 finished products"


def test_cost_checkpoint_called_in_both_dispatcher_paths(cells: dict) -> None:
    """Both serial and concurrent dispatcher paths must call the
    checkpoint after each product completes."""
    c6 = cells["ce20f070"]
    # Serial path
    assert "_print_cost_checkpoint(_pi, len(pending))" in c6, (
        "Serial path must call checkpoint after _process_one"
    )
    # Concurrent path uses a counter dict
    assert "_finished_count" in c6, (
        "Concurrent path must track finished count for ordered checkpoint"
    )


# ============================================================
# #14 — Spec source-tracing rule in Designer prompt
# ============================================================

def test_spec_source_tracing_rule(cells: dict) -> None:
    """Designer must trace every spec value to a specific source
    (scrape.specs, vision.packaging_text, vision.physical). Prefer
    omitting a row over inventing the value."""
    c6 = cells["ce20f070"]
    assert "RULE (SPEC SOURCE-TRACING)" in c6
    assert "OMIT THE ROW" in c6, (
        "Rule must explicitly tell model to omit rows without sourced value"
    )
    # The 3 priority sources must be listed
    assert "scrape specs" in c6, "Rule must list scrape.specs as source"
    assert "packaging_text" in c6, "Rule must list packaging_text source"
    assert "physical" in c6.lower(), "Rule must list physical key_features source"
