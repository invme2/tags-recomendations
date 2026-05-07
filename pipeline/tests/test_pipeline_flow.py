"""Pipeline-flow conflict tests for the EPROLO-only architecture (post-imggen-removal).

The pipeline is:
    pending → scraped → images_uploaded → vision_done → strategy_done
    → html_ready (designer wrote content with EPROLO image_url's)
    → done (Shopify product + EPROLO gallery photos pushed)

No image generation. Designer picks image_url directly from the EPROLO
photo list passed in its user message. Step 5 attaches EPROLO top photos
to product carousel via shopify_attach_media.
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
# Status flow integrity
# ============================================================

EXPECTED_STATUSES = [
    "pending",
    "scraped",
    "images_uploaded",
    "vision_done",
    "strategy_done",
    "html_ready",
    "done",
    "error",
]


def test_all_pipeline_statuses_present(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for status in EXPECTED_STATUSES:
        if status in ("pending", "error"):
            continue
        assert status in c6, f"Status '{status}' not used in Cell 6"


def test_no_image_gen_statuses(cells: dict) -> None:
    """Verify image-gen-era statuses are gone."""
    c6 = cells["ce20f070"]
    assert "'image_plan_done'" not in c6, "Legacy 'image_plan_done' status leaked"
    assert "'images_generated'" not in c6, (
        "'images_generated' status should be removed — image gen feature was cut"
    )


def test_status_transitions_cover_each_step(cells: dict) -> None:
    c6 = cells["ce20f070"]
    transitions = [
        ("pstatus == 'pending'",          "scrape"),
        ("pstatus == 'scraped'",          "images"),
        ("pstatus == 'images_uploaded'",  "vision"),
        ("pstatus == 'vision_done'",      "strategy"),
        ("pstatus == 'strategy_done'",    "designer"),
        ("pstatus == 'html_ready'",       "shopify"),
    ]
    for guard, label in transitions:
        assert guard in c6, f"Missing status guard '{guard}' (step: {label})"


def test_no_orphan_status_writes(cells: dict) -> None:
    c6 = cells["ce20f070"]
    found = re.findall(r"db_update_status\(pid,\s*['\"](\w+)['\"]", c6)
    unknown = set(found) - set(EXPECTED_STATUSES)
    assert not unknown, f"db_update_status uses unknown statuses: {unknown}"


# ============================================================
# Cell 1: image gen artifacts removed
# ============================================================

def test_cell1_no_image_gen_constants(cells: dict) -> None:
    c1 = cells["477e495d"]
    for sym in ("USE_IMAGE_GEN", "MODEL_IMAGE_GEN", "IMAGE_GEN_QUALITY",
                "GALLERY_PHOTO_COUNT", "OPENAI_API_KEY"):
        assert sym not in c1, f"[{sym}] should be removed from Cell 1"


def test_cell1_no_openai_billing_link(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert "platform.openai.com" not in c1, (
        "OpenAI billing link should be removed from billing banner"
    )


def test_cell1_keeps_strategy_model(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert 'MODEL_STRATEGY        = "claude-opus-4-7"' in c1


def test_cell1_alter_keeps_strategy_json(cells: dict) -> None:
    """assets_json column may stay (harmless) but strategy_json must remain."""
    c1 = cells["477e495d"]
    assert "strategy_json" in c1


# ============================================================
# Cell 2: openai client init removed
# ============================================================

def test_cell2_no_openai_client(cells: dict) -> None:
    c2 = cells["b810afd7"]
    assert "openai_client" not in c2, "openai_client init should be removed"
    assert "_openai.OpenAI" not in c2
    assert "openai as _openai" not in c2


# ============================================================
# Cell 5: prompts (only Strategy remains)
# ============================================================

def test_image_strategy_prompt_removed(cells: dict) -> None:
    c5 = cells["ea617348"]
    assert "IMAGE_STRATEGY_SYSTEM_PROMPT" not in c5


def test_strategy_prompt_kept(cells: dict) -> None:
    c5 = cells["ea617348"]
    assert "STRATEGY_SYSTEM_PROMPT" in c5
    for field in ["selling_idea", "narrative_arc", "differentiator", "voice", "key_objections"]:
        assert field in c5


# ============================================================
# Cell 6: Designer writes image_url directly from EPROLO
# ============================================================

def test_designer_uses_image_url_not_id(cells: dict) -> None:
    c6 = cells["ce20f070"]
    # Schema lines must use image_url, not image_id
    assert '"image_url":"https://...exact EPROLO URL..."' in c6, (
        "Hero/story schema should embed image_url with EPROLO URL placeholder"
    )
    assert "image_id" not in c6, (
        "image_id placeholder system should be removed entirely"
    )


def test_designer_no_brief_schema(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for sym in ("gallery_briefs", "metafield_briefs", "visual_style"):
        assert sym not in c6, f"Designer schema should drop '{sym}'"


def test_designer_loaded_strategy_from_db(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "SELECT strategy_json FROM products WHERE id=?" in c6


def test_designer_passes_eprolo_source_list(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "EPROLO SOURCE PHOTOS" in c6
    assert "_eprolo_list" in c6


def test_designer_strategy_fields_referenced(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for field in ["strategy.selling_idea", "strategy.narrative_arc",
                  "strategy.differentiator", "strategy.key_objections", "strategy.voice"]:
        assert field in c6


def test_designer_does_not_save_assets_json(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_assets_initial" not in c6, (
        "Designer step should not build assets_json (no briefs to persist)"
    )


# ============================================================
# Cell 6: NO image gen step
# ============================================================

def test_no_step_3_7_image_gen(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "STEP 3.7" not in c6, "STEP 3.7 (image gen) should be removed"
    assert "openai_client.images.edit" not in c6
    assert "_SIZE_MAP" not in c6
    assert "_COST_MAP" not in c6


# ============================================================
# Cell 6: STEP 5 uses EPROLO photos
# ============================================================

def test_step5_uses_eprolo_top_photos(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "img_data.get('top'" in c6
    assert "shopify_attach_media(shop_pid, gallery" in c6


def test_step5_no_assets_json_lookup(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_ai_gallery" not in c6, "AI gallery lookup should be removed"
    assert "_assets_pub" not in c6


def test_step5_triggers_on_html_ready(cells: dict) -> None:
    c6 = cells["ce20f070"]
    m = re.search(r"# ═══ STEP 5: Shopify.*?if pstatus == '(\w+)':", c6, re.DOTALL)
    assert m, "STEP 5 trigger not found"
    assert m.group(1) == "html_ready", (
        f"STEP 5 must trigger on html_ready (got '{m.group(1)}')"
    )


# ============================================================
# Cross-cell consistency
# ============================================================

def test_palette_pastel_rules_consistent(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "pastel" in c6.lower() or "PASTEL" in c6


def test_voice_options_consistent(cells: dict) -> None:
    c5 = cells["ea617348"]
    c6 = cells["ce20f070"]
    voices = ["warm-confidant", "witty-irreverent", "clinical-precise",
              "editorial-thoughtful", "aspirational-luxury", "down-to-earth-honest"]
    for v in voices:
        assert v in c5
    assert "strategy.voice" in c6


def test_no_legacy_image_strategy_remnants(cells: dict) -> None:
    for cid in ("477e495d", "ea617348", "ce20f070"):
        c = cells[cid]
        assert "MODEL_IMAGE_STRATEGY" not in c
        assert "IMAGE_STRATEGY_SYSTEM_PROMPT" not in c
        assert "MODEL_IMAGE_GEN" not in c
        assert "gpt-image" not in c.lower(), f"[{cid}] mentions gpt-image"
