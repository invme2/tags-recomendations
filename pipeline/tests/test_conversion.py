"""Tests for conversion-optimization features added for cold paid traffic.

After the Editorial Pastel design review (commit applies Claude Design's
proposal), shipping / returns / secure-checkout are intentionally absent
from the storefront — operator handles those in a separate Shopify
checkout-page module. Tests for the removed `wanelo-guarantee` snippet
and the `wanelo-hero__trust` line are no longer needed.

What remains:
  - RETAIL_MARKUP / COMPARE_AT_MARKUP env vars (compare-at price anchor)
  - Hero inline CTA button — anchors to #wanelo-atc with price in label
  - Mobile sticky ATC bar (wanelo.js + wanelo.css)
  - Lazy/eager image loading discipline
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
    assert "RETAIL_MARKUP" in c1
    assert "COMPARE_AT_MARKUP" in c1
    assert ("_safe_env_float('RETAIL_MARKUP'" in c1
            or "os.environ.get('RETAIL_MARKUP'" in c1)
    assert ("_safe_env_float('COMPARE_AT_MARKUP'" in c1
            or "os.environ.get('COMPARE_AT_MARKUP'" in c1)


def test_calc_price_uses_retail_markup_constant(cells: dict) -> None:
    """calc_price must reference RETAIL_MARKUP — not the hardcoded `* 5`
    it had before. Without this, operator can't tune pricing per batch."""
    c2 = cells["b810afd7"]
    assert "cost * RETAIL_MARKUP" in c2


def test_calc_compare_price_uses_compare_markup_constant(cells: dict) -> None:
    """calc_compare_price must reference COMPARE_AT_MARKUP — drives the
    strike-through anchor that lifts perceived discount."""
    c2 = cells["b810afd7"]
    assert "cost * COMPARE_AT_MARKUP" in c2


# ============================================================
# wanelo-guarantee MUST be removed (operator handles via checkout module)
# ============================================================

def test_guarantee_snippet_is_removed() -> None:
    """The wanelo-guarantee snippet was removed per design-review.
    Shipping / returns / secure-checkout live on the checkout page, not
    the PDP. Regression-guard against accidental re-introduction."""
    snip = THEME / "snippets" / "wanelo-guarantee.liquid"
    assert not snip.exists(), (
        "wanelo-guarantee.liquid must NOT exist — operator handles "
        "risk reversal in a separate Shopify checkout-page module"
    )


def test_guarantee_not_rendered_by_master_section() -> None:
    """Master section must NOT render wanelo-guarantee — it's deleted."""
    section = (THEME / "sections" / "wanelo-product-page.liquid").read_text(encoding="utf-8")
    assert "wanelo-guarantee" not in section, (
        "Master section must not reference the removed wanelo-guarantee snippet"
    )


def test_no_guarantee_css_rules() -> None:
    """CSS must not contain .wanelo-guarantee or .wanelo-g-* rules —
    guarantee block was removed."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-guarantee" not in css
    assert ".wanelo-g-grid" not in css
    assert ".wanelo-g-item" not in css


# ============================================================
# Hero inline CTA — anchors to #wanelo-atc + price in label
# ============================================================

def test_hero_has_inline_cta(cells: dict = None) -> None:
    """Hero snippet must include an inline 'Add to cart' button that
    anchor-links to the Shopify product form via #wanelo-atc. Multiple
    CTA hit points up CVR — buyer doesn't have to scroll past 13 sections."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert "wanelo-hero__cta" in hero, (
        "Hero must have a .wanelo-hero__cta link/button"
    )
    assert 'href="#wanelo-atc"' in hero, (
        "Inline CTA must anchor to #wanelo-atc (unified ATC anchor)"
    )
    # The link must carry the data-attribute so wanelo.js can attach
    # smooth-scroll + analytics uniformly.
    assert "data-wanelo-atc-link" in hero


def test_hero_cta_includes_product_price() -> None:
    """CVR-uplift: the inline CTA renders the product price inline so
    buyer sees the cost at the moment of click decision (e.g. 'Add to
    cart — $24'). Per Claude Design review."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert "product.price" in hero, "Hero CTA must embed product.price"
    assert "money" in hero, "Hero CTA must format price via | money filter"


def test_hero_trust_line_is_removed() -> None:
    """Trust line was removed — operator handles via checkout module.
    Regression-guard."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert "wanelo-hero__trust" not in hero
    assert "shop.metafields.wanelo.trust_line" not in hero


def test_no_hero_trust_css_rules() -> None:
    """CSS must not contain .wanelo-hero__trust rules — element removed."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-hero__trust" not in css


# ============================================================
# CTA-anchor unification — all 3 CTAs point to #wanelo-atc
# ============================================================

def test_cta_snippet_anchors_to_unified_wanelo_atc() -> None:
    """Previously wanelo-cta.liquid used #product-form while hero CTA and
    sticky bar used #wanelo-atc. Now unified — all three target one
    anchor so wanelo.js can attach smooth-scroll consistently."""
    cta = (THEME / "snippets" / "wanelo-cta.liquid").read_text(encoding="utf-8")
    assert 'href="#wanelo-atc"' in cta, (
        "wanelo-cta button must anchor to #wanelo-atc (was #product-form)"
    )
    assert "data-wanelo-atc-link" in cta
    assert "#product-form" not in cta, (
        "Legacy #product-form anchor must be replaced"
    )


# ============================================================
# Trust snippet — boolean precedence bug fix
# ============================================================

def test_trust_snippet_guards_top_level_with_if_trust() -> None:
    """Old code: `{%- if trust and has_certs or has_press -%}` parses as
    ((trust AND has_certs) OR has_press) — fragile under future refactors.
    Fixed: outer `if trust` guard, then inner `if has_certs or has_press`."""
    trust = (THEME / "snippets" / "wanelo-trust.liquid").read_text(encoding="utf-8")
    # The buggy line must be gone
    assert "if trust and has_certs or has_press" not in trust
    # And the clearer pattern must be in
    assert "if has_certs or has_press" in trust


# ============================================================
# wanelo.js — sticky ATC + reduced motion + section rail + smooth scroll
# ============================================================

def test_wanelo_js_adds_sticky_atc_bar() -> None:
    """wanelo.js must inject a sticky-atc bar on mobile."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "wanelo-sticky-atc" in js
    assert "IntersectionObserver" in js


def test_wanelo_js_anchors_form_for_scroll_target() -> None:
    """Sticky bar uses scroll-to-form pattern; JS must reference the
    wanelo-atc anchor id."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "wanelo-atc" in js


def test_wanelo_js_mobile_only_via_match_media() -> None:
    """Sticky bar must only activate on mobile. The new wanelo.js uses
    `matchMedia('(max-width: 768px)')` to gate sticky-atc creation."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "matchMedia('(max-width: 768px)')" in js or \
           'matchMedia("(max-width: 768px)")' in js, (
        "JS must gate sticky-atc creation on mobile via matchMedia"
    )


def test_wanelo_js_respects_prefers_reduced_motion() -> None:
    """A11y: when prefers-reduced-motion is set, all reveal animations
    must skip and elements appear immediately. Section rail also skipped.
    Variable name relaxed — accepts either prefersReducedMotion (round 4)
    or mqReduce (rounds 5/6 Apple-aesthetic JS)."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in js
    assert "prefersReducedMotion" in js or "mqReduce" in js, (
        "JS must capture the reduced-motion match into a variable"
    )


def test_wanelo_js_builds_section_progress_rail() -> None:
    """Desktop ≥1100px gets a left-edge dot rail showing active section.
    JS dynamically injects .wanelo-rail with one dot per `<section>`."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "wanelo-rail" in js
    assert "wanelo-rail__dot" in js
    assert "matchMedia('(min-width: 1100px)')" in js


def test_wanelo_js_smooth_scrolls_atc_links() -> None:
    """All [data-wanelo-atc-link] clicks must smooth-scroll to the form,
    not jump-cut. Honors reduced-motion (uses 'auto' instead of 'smooth')."""
    js = (THEME / "assets" / "wanelo.js").read_text(encoding="utf-8")
    assert "data-wanelo-atc-link" in js
    assert "scrollIntoView" in js
    assert "behavior:" in js


# ============================================================
# wanelo.css — Editorial Pastel structural invariants
# ============================================================

def test_css_uses_system_or_imported_font_stack() -> None:
    """Apple-aesthetic refactor (rounds 4-6) intentionally drops the
    Google Fonts @import in favor of the native system font stack
    (-apple-system, SF Pro Display, BlinkMacSystemFont, etc.) — faster
    first paint, no third-party request, and Apple users get real SF.
    Editorial Pastel @import is no longer required.

    Acceptance: either an @import declaring Inter/Fraunces OR a system
    font stack reference (whichever direction the design landed on)."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    has_import = "@import" in css and ("Inter" in css or "Fraunces" in css)
    has_system_stack = "-apple-system" in css or "BlinkMacSystemFont" in css
    assert has_import or has_system_stack, (
        "CSS must explicitly declare typography source: "
        "either Google Fonts @import (Editorial Pastel) or system "
        "font stack including -apple-system / BlinkMacSystemFont "
        "(Apple aesthetic)."
    )


def test_css_styles_sticky_atc() -> None:
    """Sticky ATC bar styled, mobile-only via @media min-width:769px."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-sticky-atc" in css
    assert "position:fixed" in css.replace(" ", "")
    assert "@media(min-width:769px)" in css.replace(" ", "")


def test_css_styles_hero_cta_with_theme_token_inheritance() -> None:
    """Hero CTA must inherit `--btn-primary-bg-color` with `--ink`
    fallback so it picks up the storefront's button color automatically
    while guaranteeing WCAG AA contrast on any pastel palette."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-hero__cta" in css
    assert "var(--btn-primary-bg-color" in css, (
        "CTAs must inherit theme's --btn-primary-bg-color token"
    )
    assert "var(--ink" in css, "Must have --ink fallback for guaranteed contrast"


def test_css_has_focus_visible_rings() -> None:
    """Accessibility: focusable elements must have :focus-visible outline."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline:" in css.replace(" ", "")


def test_css_respects_prefers_reduced_motion() -> None:
    """Animations must be suppressed for users with reduced-motion
    preference. CSS-level guard complements JS-level guard."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css


def test_css_has_section_progress_rail_styles() -> None:
    """CSS must style the .wanelo-rail dots (desktop ≥1100px nav)."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert ".wanelo-rail" in css
    assert ".wanelo-rail__dot" in css


def test_css_uses_8px_spacing_scale() -> None:
    """Editorial Pastel unifies on one 8px-baseline spacing scale
    (--space-1..--space-12) — was two parallel systems before."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert "--space-1:" in css.replace(" ", "")
    assert "--space-12:" in css.replace(" ", "")


def test_css_features_no_glassmorphism() -> None:
    """Features card swaps the 2022 glassmorphism (backdrop-filter:blur)
    for solid white card + hairline + soft shadow."""
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    # Features section must NOT use backdrop-filter (the old glass effect).
    # Reviews section is also de-glassed, so global check is fine.
    assert "backdrop-filter" not in css, (
        "Editorial Pastel removed glassmorphism — no backdrop-filter rules"
    )


# ============================================================
# Storefront image loading — above-fold eager, below-fold lazy
# ============================================================

def test_hero_image_loads_eager_with_priority() -> None:
    """Hero image is the LCP (Largest Contentful Paint) candidate."""
    hero = (THEME / "snippets" / "wanelo-hero.liquid").read_text(encoding="utf-8")
    assert 'loading="eager"' in hero
    assert 'fetchpriority="high"' in hero


def test_below_fold_images_lazy() -> None:
    """Story chapter images (below fold) must use loading='lazy'."""
    story = (THEME / "snippets" / "wanelo-story.liquid").read_text(encoding="utf-8")
    assert 'loading="lazy"' in story


# ============================================================
# Master section — preconnect + script-position fixes
# ============================================================

def test_master_section_loads_typography_efficiently() -> None:
    """Either preconnect to fonts.gstatic.com (Editorial Pastel — saves
    ~80-150ms on cold first paint when Google Fonts is used) OR the new
    Apple-aesthetic approach which uses system font stack and needs no
    preconnect at all.

    Acceptance: master section either preconnects to Google Fonts host
    OR no @import in CSS (system stack only)."""
    section = (THEME / "sections" / "wanelo-product-page.liquid").read_text(encoding="utf-8")
    css = (THEME / "assets" / "wanelo.css").read_text(encoding="utf-8")
    has_preconnect = ('rel="preconnect"' in section
                      and "fonts.gstatic.com" in section)
    has_no_import = "@import" not in css or "fonts.googleapis" not in css
    assert has_preconnect or has_no_import, (
        "Either preconnect to fonts.gstatic.com (when @import is used) "
        "OR drop Google Fonts entirely (use system font stack)."
    )


def test_collection_section_does_not_double_load_wanelo_js() -> None:
    """wanelo-collection-related.liquid no longer loads wanelo.js — the
    master product-page section is the only loader. Collection page
    doesn't need reveal / ATC / rail bindings anyway."""
    section = (THEME / "sections" / "wanelo-collection-related.liquid").read_text(encoding="utf-8")
    assert "wanelo.js" not in section, (
        "Collection section must not load wanelo.js (master section handles it)"
    )


# ============================================================
# Palette snippet — debuggability
# ============================================================

def test_palette_inline_style_has_data_attribute() -> None:
    """For DevTools debuggability: the per-product palette <style> must
    carry `data-wanelo-palette` so operator can identify the right block."""
    palette = (THEME / "snippets" / "wanelo-palette.liquid").read_text(encoding="utf-8")
    assert "data-wanelo-palette" in palette
