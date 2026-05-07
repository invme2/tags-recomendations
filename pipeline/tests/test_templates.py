"""Template-system tests for per-product visual variants.

The pipeline supports 5 visual templates picked by Designer based on product
category. Each template is a coherent typography/density/accent preset
applied via `<div class="wanelo-page" data-template="...">`. CSS rules
under `.wanelo-page[data-template="X"]` override defaults.

Goal: products from different categories look DIFFERENT visually but stay
INTERNALLY CONSISTENT (one template per product).

Tests cover:
1. CSS — all 5 templates have selectors with at least one distinct override
2. Master section — reads palette.template, emits data-template attribute
3. Designer prompt — schema lists all 5 templates, instructions map
   categories to templates
4. Category fixtures — for each of ~6 product categories, simulate
   a designer JSON output and assert the chosen template fits
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
CSS_PATH = ROOT / "pipeline" / "theme_assets" / "assets" / "wanelo.css"
SECTION_PATH = ROOT / "pipeline" / "theme_assets" / "sections" / "wanelo-product-page.liquid"

TEMPLATES = ("editorial", "minimal", "warm", "vibrant", "luxury")


@pytest.fixture(scope="module")
def cells() -> dict:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    return {c.get("id"): c["source"] for c in nb.cells if c.cell_type == "code"}


@pytest.fixture(scope="module")
def css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def section() -> str:
    return SECTION_PATH.read_text(encoding="utf-8")


# ============================================================
# CSS — every template has selectors and unique overrides
# ============================================================

@pytest.mark.parametrize("tpl", TEMPLATES)
def test_css_has_template_selector(css: str, tpl: str) -> None:
    """Every template must have at least one selector applying its rules."""
    assert f'.wanelo-page[data-template="{tpl}"]' in css, (
        f"CSS missing selector for template '{tpl}'"
    )


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_css_template_has_typography_override(css: str, tpl: str) -> None:
    """Every template must override at least one typography property
    (font-family, font-weight, letter-spacing) — otherwise it's a no-op."""
    # Find the template's CSS block(s) and assert at least one rule mentions
    # one of these properties.
    pat = re.compile(
        rf'\.wanelo-page\[data-template="{re.escape(tpl)}"\][^{{]*\{{([^}}]+)\}}',
        re.DOTALL,
    )
    blocks = pat.findall(css)
    assert blocks, f"No CSS blocks found for [data-template={tpl}]"
    typo_props = ("font-family", "font-weight", "letter-spacing", "--gap-section",
                  "--r-sm", "transition-duration")
    has_override = any(any(prop in block for prop in typo_props) for block in blocks)
    assert has_override, (
        f"Template '{tpl}' has selectors but no typography/density override — "
        "it would render identical to default"
    )


def test_css_templates_are_visually_distinct(css: str) -> None:
    """Each template should differ from its peers in at least one font choice
    or density variable. Catches accidental copy-paste duplicates."""
    fingerprints = {}
    for tpl in TEMPLATES:
        pat = re.compile(
            rf'\.wanelo-page\[data-template="{re.escape(tpl)}"\][^{{]*\{{([^}}]+)\}}',
            re.DOTALL,
        )
        joined = " ".join(pat.findall(css))
        # Pull out font-family, --r-md, --gap-section, font-weight signals
        sig = []
        for prop in ("font-family", "--r-md", "--gap-section", "font-weight",
                     "letter-spacing", "transition-duration"):
            for m in re.finditer(rf"{re.escape(prop)}\s*:\s*([^;]+);", joined):
                sig.append(f"{prop}={m.group(1).strip()}")
        fingerprints[tpl] = "|".join(sorted(set(sig)))
    # All 5 fingerprints distinct
    assert len(set(fingerprints.values())) == len(TEMPLATES), (
        f"Some templates have identical CSS fingerprints:\n"
        + "\n".join(f"  {k}: {v}" for k, v in fingerprints.items())
    )


# ============================================================
# Master section — reads palette.template, emits data-template attr
# ============================================================

def test_master_section_reads_palette_template(section: str) -> None:
    assert "product.metafields.custom.palette.value" in section, (
        "Master section must read product.metafields.custom.palette.value"
    )
    assert "_template" in section or "template" in section
    assert "default: 'editorial'" in section, (
        "Must default to 'editorial' if palette.template missing"
    )


def test_master_section_emits_data_template_attr(section: str) -> None:
    assert 'data-template="{{ _template }}"' in section, (
        "Master section must render <div ... data-template=\"{{ _template }}\">"
    )


# ============================================================
# Designer prompt — schema + category mapping
# ============================================================

def test_designer_palette_schema_has_template(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert '"template":"editorial|minimal|warm|vibrant|luxury"' in c6, (
        "Designer palette schema must list template enum with all 5 options"
    )


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_designer_instructions_mention_each_template(cells: dict, tpl: str) -> None:
    """Designer prompt must list each template by name with category guidance."""
    c6 = cells["ce20f070"]
    assert f'\\"{tpl}\\"' in c6, (
        f"Designer prompt must reference template '{tpl}' by name in instructions"
    )


def test_designer_instructions_map_categories_to_templates(cells: dict) -> None:
    """Spot-check that key category keywords are mentioned alongside template hints."""
    c6 = cells["ce20f070"]
    expected_pairs = [
        ("editorial",  ["beauty", "skincare", "wellness"]),
        ("minimal",    ["tech", "electronics", "gadgets"]),
        ("warm",       ["home", "kitchen", "pet"]),
        ("vibrant",    ["sport", "fitness", "kids"]),
        ("luxury",     ["premium", "jewelry", "fragrance"]),
    ]
    # Search for each template line and verify keywords appear near it.
    for tpl, keywords in expected_pairs:
        pat = re.compile(rf'\\"{tpl}\\"[^\n]*?\\n', re.DOTALL)
        lines = pat.findall(c6)
        assert lines, f"Template '{tpl}' not in instructions"
        joined = " ".join(lines).lower()
        matched = [k for k in keywords if k in joined]
        assert matched, (
            f"Template '{tpl}' has no category hint — expected one of "
            f"{keywords} on the same line. Got: {lines[0][:200]}"
        )


# ============================================================
# Category fixtures — simulate Designer outputs and assert structure
# ============================================================

CATEGORY_FIXTURES = [
    {
        "category": "Skincare / Anti-aging serum",
        "voice": "editorial-thoughtful",
        "expected_template": "editorial",
        "palette_hint": {
            "brand_1":   "#ffe9d6",
            "brand_2":   "#aac9f5",
            "brand_3":   "#a6d8be",
            "brand_soft":"#fdf6ee",
            "brand_deep":"#ffc8b0",
            "template":  "editorial",
        },
    },
    {
        "category": "Smart watch / fitness tracker",
        "voice": "clinical-precise",
        "expected_template": "minimal",
        "palette_hint": {
            "brand_1":   "#e0e0e0",
            "brand_2":   "#d0d8e0",
            "brand_3":   "#cccccc",
            "brand_soft":"#f7f7f7",
            "brand_deep":"#a8a8a8",
            "template":  "minimal",
        },
    },
    {
        "category": "Kitchen tool / silicone spatula set",
        "voice": "warm-confidant",
        "expected_template": "warm",
        "palette_hint": {
            "brand_1":   "#f5e9c8",
            "brand_2":   "#e8efe5",
            "brand_3":   "#fae0d4",
            "brand_soft":"#fff5f0",
            "brand_deep":"#d4b896",
            "template":  "warm",
        },
    },
    {
        "category": "Yoga mat / fitness gear",
        "voice": "witty-irreverent",
        "expected_template": "vibrant",
        "palette_hint": {
            "brand_1":   "#aac9f5",
            "brand_2":   "#a6d8be",
            "brand_3":   "#ffe9d6",
            "brand_soft":"#f0e8d0",
            "brand_deep":"#88a8c8",
            "template":  "vibrant",
        },
    },
    {
        "category": "Premium fragrance / eau de parfum",
        "voice": "aspirational-luxury",
        "expected_template": "luxury",
        "palette_hint": {
            "brand_1":   "#e7e0d6",
            "brand_2":   "#ddd6e3",
            "brand_3":   "#f0e8d0",
            "brand_soft":"#fdf6ee",
            "brand_deep":"#a89880",
            "template":  "luxury",
        },
    },
    {
        "category": "Pet — interactive cat toy",
        "voice": "down-to-earth-honest",
        "expected_template": "warm",
        "palette_hint": {
            "brand_1":   "#f5e9c8",
            "brand_2":   "#e8efe5",
            "brand_3":   "#ddd6e3",
            "brand_soft":"#fff5f0",
            "brand_deep":"#d4b896",
            "template":  "warm",
        },
    },
]


@pytest.mark.parametrize("fixture", CATEGORY_FIXTURES, ids=lambda f: f["category"])
def test_category_fixture_palette_is_valid_json(fixture) -> None:
    """Fixture palettes must be valid JSON the wanelo-palette snippet can parse."""
    payload = json.dumps(fixture["palette_hint"])
    parsed = json.loads(payload)
    assert parsed["template"] == fixture["expected_template"]
    # All 5 brand colors are hex
    for k in ("brand_1", "brand_2", "brand_3", "brand_soft", "brand_deep"):
        assert re.match(r"^#[0-9a-fA-F]{6}$", parsed[k]), (
            f"{k} not a 6-digit hex color"
        )


@pytest.mark.parametrize("fixture", CATEGORY_FIXTURES, ids=lambda f: f["category"])
def test_category_fixture_template_is_supported(fixture, css: str) -> None:
    """Every fixture's expected_template must be a real CSS variant."""
    tpl = fixture["expected_template"]
    assert tpl in TEMPLATES
    assert f'.wanelo-page[data-template="{tpl}"]' in css


def test_category_fixtures_cover_all_templates() -> None:
    """Fixture set must exercise all 5 templates so a CSS regression in any
    one of them is caught by at least one category fixture."""
    covered = {f["expected_template"] for f in CATEGORY_FIXTURES}
    assert covered == set(TEMPLATES), (
        f"Fixtures cover {covered}, missing {set(TEMPLATES) - covered}"
    )


@pytest.mark.parametrize("fixture", CATEGORY_FIXTURES, ids=lambda f: f["category"])
def test_category_fixture_voice_is_valid(fixture, cells: dict) -> None:
    """The fixture's voice must be one of the 6 voices the strategy prompt allows."""
    c5 = cells["ea617348"]
    voices = ["warm-confidant", "witty-irreverent", "clinical-precise",
              "editorial-thoughtful", "aspirational-luxury", "down-to-earth-honest"]
    assert fixture["voice"] in voices
    for v in voices:
        assert v in c5  # sanity: all voices present in strategy prompt


# ============================================================
# Pastel constraint still holds across all template fixtures
# ============================================================

def _luminance(hex_color: str) -> float:
    """Crude perceptual luminance for the pastel rule."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@pytest.mark.parametrize("fixture", CATEGORY_FIXTURES, ids=lambda f: f["category"])
def test_category_fixture_palette_is_pastel(fixture) -> None:
    """All 5 brand colors must be pastel per Designer rule. brand_soft is the
    lightest (cream/off-white, allowed up to ~1.0); brand_deep is darkest
    accent. The other three are mid-pastel. No template overrides this —
    pastel principle is shared, only typography/density varies per template."""
    p = fixture["palette_hint"]
    # brand_soft: lightest tier, up to near-white
    soft_lum = _luminance(p["brand_soft"])
    assert 0.85 <= soft_lum <= 1.0, (
        f"[{fixture['category']}] brand_soft={p['brand_soft']} lum {soft_lum:.2f} "
        "outside lightest-pastel range 0.85-1.0"
    )
    # brand_deep: darker tier (still pastel, not near-black)
    deep_lum = _luminance(p["brand_deep"])
    assert 0.55 <= deep_lum <= 0.85, (
        f"[{fixture['category']}] brand_deep={p['brand_deep']} lum {deep_lum:.2f} "
        "outside darker-pastel range 0.55-0.85"
    )
    # brand_1/2/3: mid-pastel
    for k in ("brand_1", "brand_2", "brand_3"):
        lum = _luminance(p[k])
        assert 0.65 <= lum <= 0.95, (
            f"[{fixture['category']}] {k}={p[k]} lum {lum:.2f} "
            "outside mid-pastel range 0.65-0.95"
        )
    # brand_soft must still be lighter than brand_deep
    assert soft_lum > deep_lum, (
        f"brand_soft (lum {soft_lum:.2f}) must be lighter than brand_deep (lum {deep_lum:.2f})"
    )
