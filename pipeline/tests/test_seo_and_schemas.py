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

LIQUID_PATH = ROOT / "pipeline" / "theme_assets" / "product-html-section.liquid"

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


def test_badge_html_preserved() -> None:
    """BADGES_HTML slot is supposed to contain <span class="badge">…</span>
    pre-rendered HTML — those must pass through."""
    badges = '<span class="badge solid">630nm</span><span class="badge">USB-C</span>'
    html = pb.render_module(
        "m16",
        {"KICKER": "K", "H3": "H", "P": "P",
         "IMG_URL": "u", "IMG_ALT": "a", "BADGES_HTML": badges})
    assert 'class="badge solid"' in html
    assert "630nm" in html


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

def test_liquid_section_does_not_emit_product_schema() -> None:
    """Theme typically emits its own Product schema — duplication causes
    confusion in Google's structured-data parser."""
    liquid = LIQUID_PATH.read_text(encoding="utf-8")
    # Ensure no Product schema construction in Liquid
    assert '"@type": "Product"' not in liquid
    assert '"@type":"Product"' not in liquid


def test_liquid_section_loads_css_asset() -> None:
    liquid = LIQUID_PATH.read_text(encoding="utf-8")
    assert "wanelo-product.css" in liquid
    assert "asset_url" in liquid
    assert "stylesheet_tag" in liquid


def test_liquid_section_loads_js_asset() -> None:
    liquid = LIQUID_PATH.read_text(encoding="utf-8")
    assert "wanelo-product.js" in liquid
    assert "script_tag" in liquid


def test_liquid_section_renders_metafield() -> None:
    liquid = LIQUID_PATH.read_text(encoding="utf-8")
    assert "product.metafields.custom.html_description" in liquid


def test_liquid_section_gates_on_metafield_blank() -> None:
    """Don't emit anything if the metafield is empty — prevents broken layouts
    on products that haven't been processed yet."""
    liquid = LIQUID_PATH.read_text(encoding="utf-8")
    assert "!= blank" in liquid


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
