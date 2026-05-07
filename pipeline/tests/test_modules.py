"""Tests for 7 new optional modules added to the JSON-metafield architecture.

All 16 metafields now: 9 always-on (hero, story, features, stats, reviews, faq,
cta, palette, interlinks) + 7 optional (how_to, specs, whats_included,
ingredients, timeline, trust, compare). Designer fills optional modules ONLY
when relevant to product category; skip-if-blank gating in each Liquid snippet
hides empty sections at render time.
"""
from __future__ import annotations

import re
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
SNIPPETS_DIR = ROOT / "pipeline" / "theme_assets" / "snippets"
SECTION_PATH = ROOT / "pipeline" / "theme_assets" / "sections" / "wanelo-product-page.liquid"
CSS_PATH = ROOT / "pipeline" / "theme_assets" / "assets" / "wanelo.css"

ALL_MODULES = [
    "hero", "story", "features", "stats", "reviews", "faq", "cta", "palette", "interlinks",
    "how_to", "specs", "whats_included", "ingredients", "timeline", "trust", "compare",
]

OPTIONAL_MODULES = [
    "how_to", "specs", "whats_included", "ingredients", "timeline", "trust", "compare",
]

# Snippet filenames use kebab-case for compound module names
SNIPPET_FILE = {
    "hero": "wanelo-hero", "story": "wanelo-story", "features": "wanelo-features",
    "stats": "wanelo-stats", "reviews": "wanelo-reviews", "faq": "wanelo-faq",
    "cta": "wanelo-cta", "palette": "wanelo-palette", "interlinks": "wanelo-interlinks",
    "how_to": "wanelo-how-to",
    "specs": "wanelo-specs",
    "whats_included": "wanelo-whats-included",
    "ingredients": "wanelo-ingredients",
    "timeline": "wanelo-timeline",
    "trust": "wanelo-trust",
    "compare": "wanelo-compare",
}


@pytest.fixture(scope="module")
def cells() -> dict:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    return {c.get("id"): c["source"] for c in nb.cells if c.cell_type == "code"}


@pytest.fixture(scope="module")
def section() -> str:
    return SECTION_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


# ============================================================
# Snippet files exist
# ============================================================

@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_snippet_file_exists(module: str) -> None:
    path = SNIPPETS_DIR / f"{SNIPPET_FILE[module]}.liquid"
    assert path.exists(), f"Snippet file missing: {path}"


# ============================================================
# Snippet reads its own metafield + has skip-if-blank gate
# ============================================================

@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_snippet_reads_metafield(module: str) -> None:
    path = SNIPPETS_DIR / f"{SNIPPET_FILE[module]}.liquid"
    content = path.read_text(encoding="utf-8")
    assert f"product.metafields.custom.{module}" in content, (
        f"{module}: snippet must read product.metafields.custom.{module}.value"
    )


@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_snippet_has_blank_gate(module: str) -> None:
    """Every snippet must check the metafield is present + has items before rendering."""
    path = SNIPPETS_DIR / f"{SNIPPET_FILE[module]}.liquid"
    content = path.read_text(encoding="utf-8")
    assert "{%- if " in content or "{% if " in content, (
        f"{module}: missing if-gate — would emit broken markup on empty metafield"
    )


@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_snippet_uses_kebab_module_class(module: str) -> None:
    """Snippet root section must have a wanelo-<module> CSS class for styling."""
    path = SNIPPETS_DIR / f"{SNIPPET_FILE[module]}.liquid"
    content = path.read_text(encoding="utf-8")
    # Translate kebab; e.g. how_to → howto, whats_included → whatsincluded
    css_class = "wanelo-" + module.replace("_", "")
    assert css_class in content, (
        f"{module}: snippet should have CSS class '{css_class}' on its root <section>"
    )


# ============================================================
# Master section renders all 16 modules in order
# ============================================================

@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_master_section_renders_module(section: str, module: str) -> None:
    snippet = SNIPPET_FILE[module]
    assert f"render '{snippet}'" in section, (
        f"Master section must include {{% render '{snippet}' %}}"
    )


def test_master_section_renders_all_16(section: str) -> None:
    for m in ALL_MODULES:
        snippet = SNIPPET_FILE[m]
        assert snippet in section, f"missing render for module {m}"


# ============================================================
# CSS has rules for new modules
# ============================================================

@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_css_has_module_rules(css: str, module: str) -> None:
    css_class = ".wanelo-" + module.replace("_", "")
    assert css_class in css, f"CSS missing rule for class '{css_class}'"


# ============================================================
# Cell 2 metafield definitions cover all 16
# ============================================================

@pytest.mark.parametrize("module", ALL_MODULES)
def test_cell2_creates_metafield_definition(cells: dict, module: str) -> None:
    c2 = cells["b810afd7"]
    assert f"('{module}'," in c2, (
        f"Cell 2 must create metafield definition for custom.{module}"
    )


# ============================================================
# Designer schema in Cell 6 mentions all 7 new modules
# ============================================================

@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_designer_schema_mentions_module(cells: dict, module: str) -> None:
    c6 = cells["ce20f070"]
    assert f'"{module}":' in c6, (
        f"Designer JSON schema must include '{module}' field"
    )


@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_designer_extracts_module(cells: dict, module: str) -> None:
    c6 = cells["ce20f070"]
    assert f"designer_resp.get('{module}')" in c6, (
        f"Designer step must extract '{module}' from response into sections dict"
    )


@pytest.mark.parametrize("module", OPTIONAL_MODULES)
def test_designer_instructions_mention_module(cells: dict, module: str) -> None:
    c6 = cells["ce20f070"]
    assert f"- {module}:" in c6, (
        f"Designer instructions must have '- {module}:' guidance line "
        "explaining when to fill / when to skip"
    )


# ============================================================
# Cell 6 Step 5 includes all 16 keys in metafieldsSet
# ============================================================

@pytest.mark.parametrize("module", ALL_MODULES)
def test_step5_pushes_module(cells: dict, module: str) -> None:
    c6 = cells["ce20f070"]
    # _wanelo_keys list contains the module
    pat = re.compile(r"_wanelo_keys = \[(.*?)\]", re.DOTALL)
    m = pat.search(c6)
    assert m, "_wanelo_keys list not found in Cell 6"
    keys_block = m.group(1)
    assert f"'{module}'" in keys_block, (
        f"_wanelo_keys must include '{module}' so it gets pushed to Shopify"
    )


# ============================================================
# Optional-module fixtures: realistic JSON shapes per category
# ============================================================

# When designer fills optional modules for these categories, the JSON
# must conform to what each snippet expects. Tests parse fixture JSON
# and assert the structural fields are present.

CATEGORY_MODULE_FIXTURES = {
    "skincare-anti-aging": {
        "filled": ["hero", "story", "features", "ingredients", "how_to",
                   "timeline", "stats", "reviews", "faq", "cta", "palette",
                   "interlinks", "trust"],
        "skipped": ["specs", "whats_included", "compare"],
        "ingredients": {
            "head": {"kicker": "KEY ACTIVES", "h2": "Clinical formulation", "desc": ""},
            "items": [
                {"name": "Hyaluronic Acid", "role": "deep hydrator", "badge": "HERO"},
                {"name": "Niacinamide", "role": "barrier repair", "badge": ""},
                {"name": "Peptide-3", "role": "wrinkle smoother", "badge": "CLINICAL"},
            ],
        },
        "timeline": {
            "head": {"kicker": "RESULTS", "h2": "Your skin journey", "desc": ""},
            "items": [
                {"when": "DAY 1", "h4": "Instant glow", "p": "Skin feels visibly hydrated"},
                {"when": "DAY 14", "h4": "Texture refined", "p": "Pores look smaller, tone evens"},
                {"when": "DAY 30", "h4": "Firm + plump", "p": "Fine lines reduced 23%"},
            ],
        },
    },
    "tech-smartwatch": {
        "filled": ["hero", "features", "specs", "stats", "reviews", "faq",
                   "cta", "palette", "interlinks", "compare"],
        "skipped": ["story", "ingredients", "how_to", "timeline",
                    "whats_included", "trust"],
        "specs": {
            "head": {"kicker": "SPECIFICATIONS", "h2": "Built for the wrist", "desc": ""},
            "items": [
                {"label": "Display", "value": "1.78\" AMOLED, 1000 nits"},
                {"label": "Battery", "value": "Up to 14 days"},
                {"label": "Water resistance", "value": "5 ATM (50m)"},
                {"label": "Weight", "value": "32 g"},
                {"label": "Sensors", "value": "HR · SpO₂ · GPS · Accel"},
                {"label": "Compatibility", "value": "iOS 14+ / Android 8+"},
            ],
        },
        "compare": {
            "head": {"kicker": "VS. ALTERNATIVES", "h2": "How it stacks up", "desc": ""},
            "columns": [
                {"name": "This", "badge": "BEST"},
                {"name": "Generic", "badge": ""},
                {"name": "Premium", "badge": ""},
            ],
            "rows": [
                {"label": "Battery (days)", "values": ["14", "3", "10"]},
                {"label": "AMOLED", "values": ["✓", "✗", "✓"]},
                {"label": "Built-in GPS", "values": ["✓", "✗", "✓"]},
                {"label": "Price tier", "values": ["$", "$", "$$$"]},
            ],
        },
    },
    "kitchen-knife-set": {
        "filled": ["hero", "story", "features", "specs", "whats_included",
                   "stats", "reviews", "faq", "cta", "palette", "interlinks", "trust"],
        "skipped": ["ingredients", "how_to", "timeline", "compare"],
        "whats_included": {
            "head": {"kicker": "WHAT'S IN THE BOX", "h2": "Your complete set", "desc": ""},
            "items": [
                {"glyph": "🔪", "name": "Chef knife", "qty": "1", "note": "8\""},
                {"glyph": "🔪", "name": "Paring knife", "qty": "1", "note": "3.5\""},
                {"glyph": "🔪", "name": "Bread knife", "qty": "1", "note": "10\""},
                {"glyph": "📦", "name": "Magnetic block", "qty": "1", "note": "Bamboo"},
                {"glyph": "💎", "name": "Honing rod", "qty": "1", "note": "Diamond-tipped"},
            ],
        },
    },
    "supplement-vitamin-d": {
        "filled": ["hero", "story", "features", "ingredients", "how_to",
                   "stats", "reviews", "faq", "cta", "palette", "interlinks", "trust"],
        "skipped": ["specs", "whats_included", "timeline", "compare"],
        "trust": {
            "head": {"kicker": "TESTED & VERIFIED", "h2": "Quality you can trust", "desc": ""},
            "certs": [
                {"label": "GMP-certified", "sub": "Manufacturing standard"},
                {"label": "Third-party tested", "sub": "Every batch"},
                {"label": "Non-GMO", "sub": "Verified ingredients"},
            ],
            "press": [
                {"label": "Wellness+", "sub": "2024 best of"},
                {"label": "Healthline", "sub": "editor's pick"},
            ],
        },
    },
    "gift-spa-set": {
        "filled": ["hero", "story", "features", "whats_included",
                   "ingredients", "stats", "reviews", "faq", "cta", "palette", "interlinks"],
        "skipped": ["specs", "how_to", "timeline", "trust", "compare"],
    },
}


@pytest.mark.parametrize("category,fx", list(CATEGORY_MODULE_FIXTURES.items()))
def test_category_fixture_has_filled_and_skipped(category: str, fx: dict) -> None:
    """Every fixture splits modules into 'filled' (relevant) vs 'skipped' (omit)."""
    filled = set(fx["filled"])
    skipped = set(fx["skipped"])
    assert filled & skipped == set(), (
        f"[{category}] fixture has overlap between filled and skipped: {filled & skipped}"
    )
    # Together they should cover ALL modules — no module forgotten
    assert filled | skipped == set(ALL_MODULES), (
        f"[{category}] missing decision for: {set(ALL_MODULES) - (filled | skipped)}"
    )


def test_optional_modules_used_at_least_once_across_fixtures() -> None:
    """Every optional module must appear in 'filled' set of at least one
    category fixture — otherwise the module is dead weight."""
    used = set()
    for fx in CATEGORY_MODULE_FIXTURES.values():
        used |= set(fx["filled"])
    for m in OPTIONAL_MODULES:
        assert m in used, (
            f"Optional module '{m}' is not 'filled' in any category fixture — "
            "either fixture set is incomplete or the module doesn't fit any product type"
        )


def test_category_fixture_module_payloads_are_valid(_=None) -> None:
    """Sample payloads in fixtures must have the structural keys snippets read."""
    fx_keys_required = {
        "ingredients":    {"items": ["name"]},
        "timeline":       {"items": ["when", "h4", "p"]},
        "specs":          {"items": ["label", "value"]},
        "compare":        {"columns": ["name"], "rows": ["label", "values"]},
        "whats_included": {"items": ["name"]},
        "trust":          {"certs": ["label"]},
    }
    for cat, fx in CATEGORY_MODULE_FIXTURES.items():
        for module, payload_spec in fx_keys_required.items():
            if module not in fx:
                continue
            payload = fx[module]
            for top_key, item_keys in payload_spec.items():
                assert top_key in payload, (
                    f"[{cat}] {module}: payload missing top-level '{top_key}'"
                )
                for item in payload[top_key]:
                    for k in item_keys:
                        assert k in item, (
                            f"[{cat}] {module}.{top_key}[].{k} missing in fixture"
                        )
