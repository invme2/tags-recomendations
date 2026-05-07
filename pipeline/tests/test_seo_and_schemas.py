"""SEO + JSON-LD schema invariants tests for theme assets.

The pipeline writes 9 JSON metafields per product; the theme renders them via
one master section + 9 snippets in `pipeline/theme_assets/`. These tests pin
the contract between pipeline output and Liquid rendering:

- Master section loads CSS/JS assets and renders all 9 snippets.
- Each snippet reads from its own `custom.*` metafield and gates on `blank`.
- Master section does NOT emit a duplicate Product schema (theme handles that).
- FAQ snippet emits JSON-LD FAQPage schema for rich snippets.
- Reviews snippet splits items across 3 columns for the infinite-scroll wall.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LIQUID_SECTION_PATH = ROOT / "pipeline" / "theme_assets" / "sections" / "wanelo-product-page.liquid"
LIQUID_SNIPPETS_DIR = ROOT / "pipeline" / "theme_assets" / "snippets"


# ============================================================
# Master section
# ============================================================

def test_master_section_does_not_emit_product_schema() -> None:
    """Theme typically emits its own Product schema — duplication causes
    confusion in Google's structured-data parser. Our master section
    delegates schema emission to snippets (only FAQPage from wanelo-faq)."""
    liquid = LIQUID_SECTION_PATH.read_text(encoding="utf-8")
    assert '"@type": "Product"' not in liquid
    assert '"@type":"Product"' not in liquid


def test_master_section_loads_css_asset() -> None:
    liquid = LIQUID_SECTION_PATH.read_text(encoding="utf-8")
    assert "wanelo.css" in liquid
    assert "asset_url" in liquid
    assert "stylesheet_tag" in liquid


def test_master_section_loads_js_asset() -> None:
    liquid = LIQUID_SECTION_PATH.read_text(encoding="utf-8")
    assert "wanelo.js" in liquid
    assert "asset_url" in liquid


def test_master_section_renders_all_9_snippets() -> None:
    """Master section renders 9 sub-snippets: 1 palette + 8 content sections."""
    liquid = LIQUID_SECTION_PATH.read_text(encoding="utf-8")
    expected_snippets = [
        "wanelo-palette",
        "wanelo-hero",
        "wanelo-story",
        "wanelo-features",
        "wanelo-stats",
        "wanelo-reviews",
        "wanelo-faq",
        "wanelo-cta",
        "wanelo-interlinks",
    ]
    for s in expected_snippets:
        assert s in liquid, f"Master section missing render '{s}'"


# ============================================================
# Snippets
# ============================================================

def test_each_snippet_gates_on_metafield_blank() -> None:
    """Each content snippet must check `!= blank` (or similar) so a missing
    metafield doesn't emit broken HTML on products not yet processed."""
    snippets = [
        "wanelo-hero", "wanelo-story", "wanelo-features", "wanelo-stats",
        "wanelo-reviews", "wanelo-faq", "wanelo-cta", "wanelo-interlinks",
    ]
    for name in snippets:
        path = LIQUID_SNIPPETS_DIR / f"{name}.liquid"
        assert path.exists(), f"Snippet missing: {path}"
        content = path.read_text(encoding="utf-8")
        assert "{%- if " in content or "{% if " in content, (
            f"{name}: missing gate ({{% if ... %}}) — would emit broken markup on empty metafield"
        )


def test_each_snippet_reads_its_own_metafield() -> None:
    """Each section snippet reads from product.metafields.custom.<key>."""
    expected = {
        "wanelo-hero":       "custom.hero",
        "wanelo-story":      "custom.story",
        "wanelo-features":   "custom.features",
        "wanelo-stats":      "custom.stats",
        "wanelo-reviews":    "custom.reviews",
        "wanelo-faq":        "custom.faq",
        "wanelo-cta":        "custom.cta",
        "wanelo-interlinks": "custom.interlinks",
        "wanelo-palette":    "custom.palette",
    }
    for snippet, mf in expected.items():
        path = LIQUID_SNIPPETS_DIR / f"{snippet}.liquid"
        content = path.read_text(encoding="utf-8")
        assert mf in content, f"{snippet} should read product.metafields.{mf}"


def test_faq_snippet_emits_faqpage_schema() -> None:
    """The FAQ snippet should emit JSON-LD FAQPage schema for Google rich snippets."""
    content = (LIQUID_SNIPPETS_DIR / "wanelo-faq.liquid").read_text(encoding="utf-8")
    assert 'application/ld+json' in content
    assert '"@type": "FAQPage"' in content or '"@type":"FAQPage"' in content


def test_reviews_snippet_distributes_across_3_columns() -> None:
    """Reviews wall splits items into 3 columns by index mod 3 and duplicates
    each column for seamless infinite scroll."""
    content = (LIQUID_SNIPPETS_DIR / "wanelo-reviews.liquid").read_text(encoding="utf-8")
    assert "mod 3" in content, "should distribute by index mod 3"
    assert "(1..2)" in content or "1..2" in content, (
        "should duplicate each column for infinite-scroll loop"
    )
