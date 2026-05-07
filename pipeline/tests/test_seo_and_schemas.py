"""SEO + JSON-LD schema invariants tests.

Verify that:
- render_module sanitizes XSS-risky slot values (script/iframe/on*/javascript:)
- Allowed inline tags survive (em, strong, span.badge, a.wa-link)
- The metafield-prep regex preserves application/ld+json scripts but strips
  executable scripts (mirrors Cell 6 step-5 logic)
- The product-html-section.liquid does NOT emit a duplicate Product schema
- All 4 schema types (Product, FAQ, HowTo, VideoObject) survive metafield
  cleanup and would reach the rendered page
- The Liquid section still loads CSS asset, JS asset, and renders the metafield
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

import page_builder as pb  # noqa: E402

# Theme files migrated to JSON-driven architecture (commit 0d01d10).
# Path now points at the master section. Old liquid file removed.
LIQUID_SECTION_PATH = ROOT / "pipeline" / "theme_assets" / "sections" / "wanelo-product-page.liquid"
LIQUID_SNIPPETS_DIR = ROOT / "pipeline" / "theme_assets" / "snippets"

PALETTE = {
    "brand_1": "#ff9c70", "brand_2": "#aac9f5", "brand_3": "#a6d8be",
    "brand_soft": "#ffe9d6", "brand_deep": "#7a4520",
}


# ============================================================
# XSS sanitization in slot values
# ============================================================

def test_script_tag_in_slot_value_stripped() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "<script>alert(1)</script>Hello",
        "P": "P", "IMG_URL": "u", "IMG_ALT": "a"})
    assert "<script>" not in html
    assert "alert(1)" not in html
    assert "Hello" in html, "text after script should survive"


def test_iframe_in_slot_value_stripped() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "<iframe src=evil></iframe>Title",
        "P": "P", "IMG_URL": "u", "IMG_ALT": "a"})
    assert "<iframe" not in html
    assert "Title" in html


def test_onclick_attribute_stripped() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "Hi",
        "P": '<a href="x" onclick="alert(1)">Click</a>',
        "IMG_URL": "u", "IMG_ALT": "a"})
    assert "onclick" not in html
    assert 'href="x"' in html


def test_javascript_protocol_neutralized() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "Hi",
        "P": '<a href="javascript:alert(1)">Bad</a>',
        "IMG_URL": "u", "IMG_ALT": "a"})
    assert "javascript:" not in html


def test_data_protocol_neutralized() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "Hi",
        "P": '<a href="data:text/html,<script>alert(1)</script>">Bad</a>',
        "IMG_URL": "u", "IMG_ALT": "a"})
    assert "data:text/html" not in html
    assert "<script>" not in html


def test_em_tag_preserved() -> None:
    html = pb.render_module("hero1", {
        "KICKER": "K", "H1": "Hello <em>World</em>",
        "P": "P", "IMG_URL": "u", "IMG_ALT": "a"})
    assert "<em>World</em>" in html


def test_a_walink_preserved() -> None:
    """Inline /collections/ links from approved list pass through (designer is
    allowed up to 2 such links per page for SEO)."""
    html = pb.render_module(
        "m21",
        {"KICKER": "K", "H3": "H",
         "P": 'Try our <a class="wa-link" href="/collections/yoga-mats">non-slip yoga mats</a> today.',
         "IMG_URL": "u", "IMG_ALT": "a"})
    assert 'class="wa-link"' in html
    assert 'href="/collections/yoga-mats"' in html


def test_badge_html_preserved_via_render_badges() -> None:
    """render_badges helper produces <span class="badge solid">N</span>
    pre-rendered HTML for use inside slots that accept HTML."""
    html = pb.render_badges(["630nm", "USB-C", "30g"], solid_first=2)
    assert 'class="badge solid"' in html
    assert "630nm" in html
    assert html.count('class="badge solid"') == 2
    assert html.count('class="badge"') == 1  # remaining


# ============================================================
# Metafield-prep regex behavior (mirrored from Cell 6 step 5)
# ============================================================

def _prep_metafield(html: str) -> str:
    """Replicate the Cell 6 metafield-prep logic so we can test it here."""
    out = re.sub(r"<style[^>]*>.*?</style>", "", html,
                 flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(
        r'<script\b(?![^>]*type=["\']application/ld\+json["\'])[^>]*>.*?</script>',
        "", out, flags=re.DOTALL | re.IGNORECASE,
    )
    out = re.sub(r"<link[^>]*/?>", "", out, flags=re.IGNORECASE)
    return out


def test_metafield_prep_strips_executable_scripts() -> None:
    out = _prep_metafield('<div>OK<script>alert(1)</script>more</div>')
    assert "<script>" not in out
    assert "alert(1)" not in out
    assert "OK" in out and "more" in out


def test_metafield_prep_keeps_jsonld_scripts() -> None:
    src = (
        '<div>X<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product"}'
        "</script></div>"
    )
    out = _prep_metafield(src)
    assert '<script type="application/ld+json">' in out
    assert '"@type":"Product"' in out


def test_metafield_prep_strips_style_blocks() -> None:
    out = _prep_metafield('<div><style>body{display:none}</style>visible</div>')
    assert "<style>" not in out
    assert "display:none" not in out


def test_metafield_prep_strips_link_tags() -> None:
    out = _prep_metafield('<div><link rel="stylesheet" href="x.css">stuff</div>')
    assert "<link" not in out


def test_metafield_prep_keeps_all_4_schema_types() -> None:
    """Product / FAQ / HowTo / VideoObject — all survive cleanup."""
    src = (
        '<div>X'
        '<script type="application/ld+json">{"@type":"Product"}</script>'
        '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        '<script type="application/ld+json">{"@type":"HowTo"}</script>'
        '<script type="application/ld+json">{"@type":"VideoObject"}</script>'
        '<script>tracking()</script>'
        "</div>"
    )
    out = _prep_metafield(src)
    schemas = re.findall(
        r'<script type="application/ld\+json">\s*({[^<]+?})\s*</script>',
        out, re.DOTALL,
    )
    assert len(schemas) == 4
    types = [json.loads(s)["@type"] for s in schemas]
    assert types == ["Product", "FAQPage", "HowTo", "VideoObject"]
    assert "tracking()" not in out


def test_metafield_prep_strips_attribute_variants_of_script() -> None:
    """<script async>, <script src="evil.js">, etc. all get stripped — only
    application/ld+json with explicit type attribute survives."""
    src = (
        '<script async>x()</script>'
        '<script src="evil.js"></script>'
        '<script type="text/javascript">y()</script>'
        '<script type="application/ld+json">{"@type":"Product"}</script>'
    )
    out = _prep_metafield(src)
    # All 4 had <script>, only the ld+json one survives
    assert out.count("<script") == 1
    assert "application/ld+json" in out
    assert "x()" not in out and "y()" not in out


# ============================================================
# Liquid section: no duplicate schema, still loads assets
# ============================================================

def test_master_section_does_not_emit_product_schema() -> None:
    """Theme typically emits its own Product schema — duplication causes
    confusion in Google's structured-data parser. Our master section
    delegates schema-emission to snippets (only FAQPage from wanelo-faq)."""
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
    """Master section delegates rendering to 8 sub-snippets (palette is loaded
    once; the other 8 are content sections)."""
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
    assert "(1..2)" in content or "1..2" in content, "should duplicate each column for infinite-scroll loop"


# ============================================================
# assemble_page output sanity for SEO
# ============================================================

def test_assembled_page_has_exactly_one_h1() -> None:
    """One h1 per page is the SEO/a11y rule. Hero modules emit h1, body
    modules use h2/h3."""
    layout = ["hero1", "m21", "m32", "m41", "m51"]
    slots = [{s: f"S{s}" for s in pb.MODULE_CATALOG[m]["slots"]} for m in layout]
    out = pb.assemble_page(layout, slots, PALETTE)
    h1_count = len(re.findall(r"<h1\b", out))
    assert h1_count == 1, f"Expected exactly 1 h1, got {h1_count}"


def test_assembled_page_no_duplicate_collections_section_with_modular() -> None:
    """assemble_page appends ONE collections section when interlinks given."""
    layout = ["hero1", "m51"]
    slots = [{s: f"S{s}" for s in pb.MODULE_CATALOG[m]["slots"]} for m in layout]
    interlinks = [
        {"title": "X", "handle": "x", "anchors": ["alpha"]},
        {"title": "Y", "handle": "y", "anchors": ["beta"]},
    ]
    out = pb.assemble_page(layout, slots, PALETTE, interlinks=interlinks)
    explore_count = out.count("Explore more")
    assert explore_count == 1, f"Expected 1 'Explore more' section, got {explore_count}"


# ============================================================
# Image loading optimizations (Core Web Vitals)
# ============================================================

@pytest.mark.parametrize("hero_id", ["hero1"])
def test_hero_image_eager_with_fetchpriority(hero_id: str) -> None:
    """Hero is the LCP element on most product pages — must load with high
    priority so Chrome doesn't deprioritize it behind below-fold assets."""
    html = pb._MODULE_HTML[hero_id]
    assert 'loading="eager"' in html, f"{hero_id} hero <img> should be loading=eager"
    assert 'fetchpriority="high"' in html, f"{hero_id} hero <img> should be fetchpriority=high"
    assert 'decoding="async"' in html, f"{hero_id} hero <img> should be decoding=async"


@pytest.mark.parametrize("body_id", ["m21", "m22"])
def test_below_fold_images_lazy_loaded(body_id: str) -> None:
    """Below-the-fold images get loading=lazy so they don't block initial paint."""
    html = pb._MODULE_HTML[body_id]
    assert 'loading="lazy"' in html, f"{body_id} <img> should be loading=lazy"
    assert 'decoding="async"' in html, f"{body_id} <img> should be decoding=async"


def test_no_module_image_lacks_loading_attribute() -> None:
    """Every <img> in the module catalog should have an explicit loading
    attribute (eager for above-fold, lazy for below). Missing attribute
    means browser default of 'eager' which hurts performance."""
    for mid, html in pb._MODULE_HTML.items():
        for img_tag in re.findall(r"<img[^>]*>", html):
            assert "loading=" in img_tag, (
                f"[{mid}] <img> without loading attribute: {img_tag[:100]}"
            )


# ============================================================
# Module template integrity
# ============================================================

def test_every_template_slot_is_in_catalog() -> None:
    """Every {SLOT} placeholder in a module template must be declared in
    MODULE_CATALOG[mid]['slots']. Mismatch → assemble_page can't fill it
    properly because slots dict won't have the key."""
    for mid, html in pb._MODULE_HTML.items():
        declared = set(pb.MODULE_CATALOG[mid]["slots"])
        in_template = set(re.findall(r"\{(\w+)\}", html))
        extra = in_template - declared
        missing = declared - in_template
        assert not extra, f"[{mid}] template uses undeclared slots: {extra}"
        assert not missing, f"[{mid}] catalog declares unused slots: {missing}"


def test_every_module_class_has_css_rule() -> None:
    """Every CSS class referenced in a module template must have a rule in
    BASE_CSS, otherwise the element renders unstyled."""
    helper_classes = {"reveal", "in", "words", "mask", "visible"}  # JS-controlled
    for mid, html in pb._MODULE_HTML.items():
        for cls_attr in re.findall(r'class="([^"]+)"', html):
            for cls in cls_attr.split():
                if cls in helper_classes:
                    continue
                assert re.search(rf"\.{re.escape(cls)}\b", pb.BASE_CSS), (
                    f"[{mid}] class '{cls}' has no rule in BASE_CSS"
                )
