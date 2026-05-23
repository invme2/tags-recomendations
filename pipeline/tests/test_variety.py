"""Anti-templating / variety tests for Designer system prompt.

The Designer (Sonnet 4.6) writes content per product. Over many products the
risk is templated rhythm — same kickers, same review-name format, same CTA
label. These checks assert the Designer prompt contains explicit variety
guidance that pushes the model OFF the predictable AI-tell defaults.
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
# Designer schema — counts relaxed for structural variety
# ============================================================

def test_features_count_relaxed_to_range(cells: dict) -> None:
    """features should allow 2-4 items, not be fixed at exactly 3 — otherwise
    every product has the same 3-card grid rhythm."""
    c6 = cells["ce20f070"]
    assert "exactly 3 items" not in c6, (
        "features count must not be hardcoded 'exactly 3'"
    )
    assert "2-4 items" in c6, "features schema must allow 2-4 items"


def test_stats_count_relaxed_to_range(cells: dict) -> None:
    """stats should allow 3-5 cells, not fixed 4."""
    c6 = cells["ce20f070"]
    assert "exactly 4 items" not in c6
    assert "3-5 items" in c6


def test_story_chapters_count_allows_skip(cells: dict) -> None:
    """story should allow 0-4 chapters — 0 means skip story entirely (simple
    utility products don't need a narrative), 4 for transformations."""
    c6 = cells["ce20f070"]
    assert "1-3 chapters" not in c6
    assert "0-4 chapters" in c6


# ============================================================
# Kicker variety pool — anti-AI-tell critical
# ============================================================

def test_designer_prompt_has_variety_kickers_block(cells: dict) -> None:
    """Designer prompt must declare an explicit VARIETY — KICKERS section
    so the model picks contextually rather than defaulting to schema hints."""
    c6 = cells["ce20f070"]
    assert "VARIETY — KICKERS" in c6 or "VARIETY — KICKERS" in c6, (
        "Designer prompt must contain a VARIETY — KICKERS block"
    )


def test_variety_block_has_pool_for_core_sections(cells: dict) -> None:
    """Core always-on sections (story / features / stats / reviews / faq /
    cta / interlinks) must each have an enumerated kicker pool of 4+ options."""
    c6 = cells["ce20f070"]
    # Find variety block — between VARIETY-KICKERS and the next major header
    start = c6.find("VARIETY — KICKERS")
    if start == -1:
        start = c6.find("VARIETY — KICKERS")
    assert start != -1
    end = c6.find("VARIETY — REVIEW NAME", start)
    if end == -1:
        end = c6.find("VARIETY — REVIEW NAME", start)
    assert end != -1
    block = c6[start:end]
    # Each section keyword should appear in the block
    for section in ("story:", "features:", "stats:", "reviews:", "faq:",
                    "cta:", "interlinks:"):
        assert section in block, (
            f"VARIETY block missing pool for section: {section!r}"
        )


def test_variety_block_has_pool_for_optional_sections(cells: dict) -> None:
    """Optional modules (how_to / specs / whats_included / ingredients /
    timeline / trust / compare / size_guide / care / dimensions / variants /
    gift_options) must each have a kicker pool — otherwise they always
    render with the schema-default kicker."""
    c6 = cells["ce20f070"]
    start = c6.find("VARIETY — KICKERS")
    if start == -1:
        start = c6.find("VARIETY — KICKERS")
    end = c6.find("VARIETY — REVIEW NAME", start)
    if end == -1:
        end = c6.find("VARIETY — REVIEW NAME", start)
    block = c6[start:end]
    for section in ("how_to:", "specs:", "whats_included:", "ingredients:",
                    "timeline:", "trust:", "compare:", "size_guide:",
                    "care:", "dimensions:", "variants:", "gift_options:"):
        assert section in block, (
            f"VARIETY block missing optional-module pool: {section!r}"
        )


def test_variety_block_warns_against_first_option(cells: dict) -> None:
    """The instruction must explicitly tell the model NOT to always pick the
    first option from each pool — otherwise variety collapses to one default."""
    c6 = cells["ce20f070"]
    # Look for wording that pushes toward 2nd-4th choices
    assert ("2nd, 3rd, or 4th" in c6 or "2nd or 3rd" in c6), (
        "Variety block must explicitly push picks away from option #1"
    )


# ============================================================
# Review name format variety — kills the biggest AI-tell
# ============================================================

def test_designer_prompt_has_review_name_variety(cells: dict) -> None:
    """Designer must be instructed to mix 3+ review-name formats across the
    9-12 reviews. 'firstname + lastinitial' for every single review is the
    single most-recognised AI generation tell."""
    c6 = cells["ce20f070"]
    assert ("VARIETY — REVIEW NAME" in c6 or
            "VARIETY — REVIEW NAME" in c6), (
        "Designer must include a review-name variety block"
    )
    assert "at LEAST 3 different formats" in c6 or \
           "at least 3 different formats" in c6.lower(), (
        "Must enforce at least 3 different name formats"
    )


def test_review_name_pool_has_six_distinct_patterns(cells: dict) -> None:
    """The pool must list at least 6 distinct name-formats so model has
    real choice. Few patterns → collapse to majority pattern again."""
    c6 = cells["ce20f070"]
    # Each pattern should be mentioned by name in the pool
    patterns = ["Standard", "Handle", "City", "Verified", "Initials", "Age"]
    found = sum(1 for p in patterns if p in c6)
    assert found >= 5, (
        f"At least 5 of 6 review-name format types must be enumerated; "
        f"found {found}: {[p for p in patterns if p in c6]}"
    )


def test_review_name_warns_explicitly_against_default_pattern(cells: dict) -> None:
    """Explicit warning against 'firstname + lastinitial for all'."""
    c6 = cells["ce20f070"]
    assert "firstname + lastinitial" in c6 or "AI tell" in c6, (
        "Must explicitly warn against the most-recognised AI name pattern"
    )


# ============================================================
# CTA label by voice — voice consistency + variety
# ============================================================

def test_cta_label_mapped_to_voice(cells: dict) -> None:
    """CTA button label must be derived from strategy.voice (not the schema
    default 'Add to cart')."""
    c6 = cells["ce20f070"]
    assert ("VARIETY — CTA BUTTON" in c6 or
            "VARIETY — CTA BUTTON" in c6), (
        "Designer must include CTA-by-voice variety block"
    )


def test_cta_block_covers_all_six_voices(cells: dict) -> None:
    """All six strategy.voice enum values must have a mapped CTA label."""
    c6 = cells["ce20f070"]
    voices = ['warm-confidant', 'witty-irreverent', 'clinical-precise',
              'editorial-thoughtful', 'aspirational-luxury', 'down-to-earth-honest']
    for v in voices:
        # Each voice should appear near a CTA label arrow
        pat = re.compile(rf"{re.escape(v)}\s*[→→]\s*'?[A-Z]")
        assert pat.search(c6), (
            f"CTA block missing mapping for voice {v!r}"
        )


def test_cta_block_warns_against_default_add_to_cart(cells: dict) -> None:
    """The block must explicitly say NOT default to 'Add to cart' unless
    voice is clinical-precise."""
    c6 = cells["ce20f070"]
    # 'NOT default' or "(NOT default 'Add to cart')" wording
    assert "NOT default" in c6 or "not default" in c6.lower(), (
        "Block must explicitly tell model not to default to 'Add to cart'"
    )
