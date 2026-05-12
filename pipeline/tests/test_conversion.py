"""Tests for conversion-optimization features added for cold paid traffic:

  - RETAIL_MARKUP / COMPARE_AT_MARKUP env vars (compare-at price anchor)
  - wanelo-guarantee snippet (risk-reversal block, always-on)
  - Hero inline CTA button + trust line (above-fold conversion driver)
  - Mobile sticky ATC bar (wanelo.js + wanelo.css)
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
# Retail-markup env vars — compare_at_price anchor for cold traffic
# ============================================================

def test_cell1_declares_retail_markup_env_vars(cells: dict) -> None:
    """Cell 1 must expose RETAIL_MARKUP + COMPARE_AT_MARKUP via env vars so
    operator can tune pricing per category without editing code."""
    c1 = cells["477e495d"]
    assert "RETAIL_MARKUP" in c1, "RETAIL_MARKUP env var declaration missing"
    assert "COMPARE_AT_MARKUP" in c1, "COMPARE_AT_MARKUP env var declaration missing"
    assert "os.environ.get('RETAIL_MARKUP'" in c1, (
        "RETAIL_MARKUP must read from os.environ.get with a default"
    )
    assert "os.environ.get('COMPARE_AT_MARKUP'" in c1


def test_calc_price_uses_retail_markup_constant(cells: dict) -> None:
    """calc_price must reference RETAIL_MARKUP — not the hardcoded `* 5`
    it had before. Without this, operator can't tune pricing per batch."""
    c2 = cells["b810afd7"]
    assert "cost * RETAIL_MARKUP" in c2, (
        "calc_price must multiply cost by RETAIL_MARKUP (not hardcoded 5)"
    )


def test_calc_compare_price_uses_compare_markup_constant(cells: dict) -> None:
    """calc_compare_price must reference COMPARE_AT_MARKUP — drives the
    strike-through anchor that lifts perceived discount."""
    c2 = cells["b810afd7"]
    assert "cost * COMPARE_AT_MARKUP" in c2, (
        "calc_compare_price must multiply by COMPARE_AT_MARKUP (not hardcoded 8)"
    )


# ============================================================
# wanelo-guarantee snippet — risk-reversal block (always-on)
# ============================================================

def test_guarantee_snippet_exists() -> None:
    """Snippet file must exist."""
    snip = THEME / "snippets" / "wanelo-guarantee.liquid"
    assert snip.exists(), "wanelo-guarantee.liquid snippet missing"


def test_guarantee_snippet_has_three_pillars() -> None:
    """Snippet must cover the three cold-traffic trust pillars:
    return policy, shipping, secure checkout."""
    snip = (THEME / "snippets" / "wanelo-guarantee.liquid").read_text(encoding="utf-8")
    # Default-fallback labels (used when shop metafield isn't set)
    assert "money-back" in snip.lower() or "return" in snip.lower()
    assert "shipping" in snip.lower()
    assert "secure" in snip.lower() or "ssl" in snip.lower()


def test_guarantee_snippet_reads_shop_metafields_for_override() -> None:
    """Operator should be able to override defaults via shop-level metafields
    (configured ONCE in Shopify Admin → Settings → Custom data → Shop).
    Pipeline does NOT write these — they're store-wide config."""
    snip = (THEME / "snippets" / "wanelo-guarantee.liquid").read_text(encoding="utf-8")
    assert "shop.metafields.wanelo" in snip, (
        "Guarantee must read shop.metafields.wanelo.* for operator override"
    )
    # And must use Liquid `default:` filter as fallback
    assert "| default:" in snip, (
        "Each guarantee field must have a sensible default if shop metafield unset"
    )


def test_guarantee_in_master_section_render_list() -> None:
    """Master section must render wanelo-guarantee right after wanelo-hero,
    so risk-reversal appears above-the-fold area for cold-traffic visitors."""
    section = (THEME / "sections" / "wanelo-product-page.liquid").read_text(encoding="utf-8")
    assert "{% render 'wanelo-guarantee' %}" in section, (
        "Master section must render wanelo-guarantee snippet"
    )
    # Must come AFTER hero render
    hero_idx = section.find("{% render 'wanelo-hero' %}")
    guar_idx = section.find("{% render 'wanelo-guarantee' %}")
    assert hero_idx != -1 and guar_idx != -1
    assert guar_idx > hero_idx, "guarantee must render after hero"
    # Should come BEFORE story (high in funnel)
    story_idx = section.find("{% render 'wanelo-story' %}")
    if story_idx != -1:
        assert guar_idx < story_idx, "guarantee should render before story"


# ============================================================
# Hero inline CTA + trust line — above-fold conversion drivers
# ============================================================

def test_hero_has_inline_cta() -> None:
    """Hero snippet must include an inline 'Add to cart' button that
    anchor-links to the Shopify product form (#wanelo-atc). Multiple CTA
    hit points up CVR — buyer doesn't have to scroll past 13 sections."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert "wanelo-hero__cta" in hero, (
        "Hero must have a .wanelo-hero__cta link/button"
    )
    assert 'href="#wanelo-atc"' in hero, (
        "Inline CTA must anchor to #wanelo-atc (Shopify product form)"
    )


def test_hero_has_trust_line() -> None:
    """Above-fold trust line under H1 — '30-day returns · Free shipping ·
    Secure checkout' style. Reads shop.metafields.wanelo.trust_line with
    a hardcoded fallback so it always renders."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert "wanelo-hero__trust" in hero, (
        "Hero must include a .wanelo-hero__trust element"
    )
    assert "shop.metafields.wanelo.trust_line" in hero, (
        "Trust line must read shop.metafields.wanelo.trust_line"
    )
    assert "| default:" in hero, "trust_line must have a fallback default"


# ============================================================
# Mobile sticky ATC — wanelo.js + wanelo.css
# ============================================================

def test_wanelo_js_adds_sticky_atc_bar() -> None:
    """wanelo.js must inject a sticky-atc bar on mobile when the product
    form scrolls off-screen. One-tap re-access from anywhere on page is
    the single biggest mobile-CVR win."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "wanelo-sticky-atc" in js, "sticky-atc class must be referenced in JS"
    assert 'form[action*="/cart/add"]' in js, (
        "JS must locate the Shopify product form to observe"
    )
    assert "IntersectionObserver" in js, "Visibility toggle must use IntersectionObserver"


def test_wanelo_js_anchors_form_for_scroll_target() -> None:
    """Sticky bar uses scroll-to-form pattern; JS must ensure the form has
    an id (defaults to 'wanelo-atc' if theme didn't set one)."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "wanelo-atc" in js, "JS must reference the wanelo-atc anchor id"


def test_wanelo_js_mobile_only_via_match_media() -> None:
    """Sticky bar must only activate on mobile (≤768px) — desktop has the
    right-column ATC already visible. JS uses matchMedia to gate."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "matchMedia('(min-width: 769px)')" in js or \
           'matchMedia("(min-width: 769px)")' in js, (
        "JS must gate sticky-atc setup on mobile via matchMedia"
    )


def test_wanelo_css_styles_sticky_atc() -> None:
    """CSS must define .wanelo-sticky-atc rules — fixed position, bottom,
    transform-on-hide for slide-in animation."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-sticky-atc" in css, "CSS must style .wanelo-sticky-atc"
    assert "position:fixed" in css.replace(" ", ""), "Sticky bar must be position:fixed"
    # Mobile-only via media query
    assert "@media(min-width:769px)" in css.replace(" ", "") or \
           "@media (min-width: 769px)" in css, (
        "Sticky bar must be hidden on desktop via min-width:769px"
    )


def test_wanelo_css_styles_hero_cta_and_trust() -> None:
    """CSS must style the new hero-cta button + trust line."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-hero__cta" in css, "Hero CTA must have CSS rules"
    assert ".wanelo-hero__trust" in css, "Trust line must have CSS rules"


def test_wanelo_css_styles_guarantee_block() -> None:
    """Guarantee block must have CSS — grid layout, icons, copy."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-guarantee" in css, "Guarantee section must have CSS"
    assert ".wanelo-g-grid" in css or ".wanelo-g-item" in css, (
        "Guarantee grid items must have CSS rules"
    )


# ============================================================
# Storefront image loading — above-fold eager, below-fold lazy
# ============================================================

def test_hero_image_loads_eager_with_priority() -> None:
    """Hero image is the LCP (Largest Contentful Paint) candidate — must
    have loading='eager' + fetchpriority='high' to maximize page-speed
    score and start ad-traffic clicks fast."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert 'loading="eager"' in hero
    assert 'fetchpriority="high"' in hero


def test_below_fold_images_lazy() -> None:
    """Story chapter images (below fold) must use loading='lazy' so
    initial page load isn't bloated by 3 inline photos."""
    story = (THEME / "snippets" / "wanelo-story.liquid").read_text(encoding="utf-8")
    assert 'loading="lazy"' in story, (
        "Story chapter <img> tags must be loading=lazy"
    )
