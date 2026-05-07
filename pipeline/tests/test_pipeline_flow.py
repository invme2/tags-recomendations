"""Pipeline-flow conflict tests for the merged-designer architecture.

The pipeline is:
    pending → scraped → images_uploaded → vision_done → strategy_done
    → html_ready (designer wrote content + briefs)
    → images_generated (gpt-image-2 generated all briefs, URLs substituted)
    → done (Shopify product + 5 gallery photos pushed)

These tests validate the STRUCTURE of the notebook without running it.
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
    "images_generated",
    "done",
    "error",
]


def test_all_pipeline_statuses_present(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for status in EXPECTED_STATUSES:
        if status in ("pending", "error"):
            continue
        assert status in c6, f"Status '{status}' not used in Cell 6"


def test_old_image_plan_status_removed(cells: dict) -> None:
    """The legacy 'image_plan_done' status must not appear after the merge."""
    c6 = cells["ce20f070"]
    assert "'image_plan_done'" not in c6, (
        "Legacy 'image_plan_done' status leaked into Cell 6 — Image Strategy was supposed to be merged into Designer"
    )


def test_status_transitions_cover_each_step(cells: dict) -> None:
    c6 = cells["ce20f070"]
    transitions = [
        ("pstatus == 'pending'",          "scrape"),
        ("pstatus == 'scraped'",          "images"),
        ("pstatus == 'images_uploaded'",  "vision"),
        ("pstatus == 'vision_done'",      "strategy"),
        ("pstatus == 'strategy_done'",    "designer"),
        ("pstatus == 'html_ready'",       "image gen"),
        ("pstatus == 'images_generated'", "shopify"),
    ]
    for guard, label in transitions:
        assert guard in c6, f"Missing status guard '{guard}' (step: {label})"


def test_no_orphan_status_writes(cells: dict) -> None:
    c6 = cells["ce20f070"]
    found = re.findall(r"db_update_status\(pid,\s*['\"](\w+)['\"]", c6)
    unknown = set(found) - set(EXPECTED_STATUSES)
    assert not unknown, f"db_update_status uses unknown statuses: {unknown}"


# ============================================================
# Cell 1: config + DB schema
# ============================================================

def test_cell1_drops_image_strategy_model(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert "MODEL_IMAGE_STRATEGY" not in c1, (
        "MODEL_IMAGE_STRATEGY constant should be removed (Image Strategy agent merged into Designer)"
    )


def test_cell1_keeps_strategy_model(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert 'MODEL_STRATEGY        = "claude-opus-4-7"' in c1, (
        "MODEL_STRATEGY (Opus 4.7) must remain — Strategy agent kept for marketing positioning"
    )


def test_cell1_alter_includes_new_columns(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert "strategy_json" in c1, "strategy_json column missing from ALTER list"
    assert "assets_json" in c1, "assets_json column missing from ALTER list"
    assert "image_plan_json" not in c1, (
        "image_plan_json column should be removed (replaced by assets_json)"
    )


def test_cell1_gallery_photo_count_constant(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert "GALLERY_PHOTO_COUNT" in c1, "GALLERY_PHOTO_COUNT constant missing"
    m = re.search(r"GALLERY_PHOTO_COUNT\s*=\s*(\d+)", c1)
    assert m, "GALLERY_PHOTO_COUNT not assigned a number"
    assert int(m.group(1)) == 5, f"GALLERY_PHOTO_COUNT must be 5, got {m.group(1)}"


def test_cell1_image_gen_quality_documented(cells: dict) -> None:
    c1 = cells["477e495d"]
    assert "IMAGE_GEN_QUALITY" in c1
    assert "MODEL_IMAGE_GEN" in c1
    assert "USE_IMAGE_GEN" in c1


# ============================================================
# Cell 5: prompts
# ============================================================

def test_image_strategy_prompt_removed(cells: dict) -> None:
    c5 = cells["ea617348"]
    assert "IMAGE_STRATEGY_SYSTEM_PROMPT" not in c5, (
        "IMAGE_STRATEGY_SYSTEM_PROMPT block should be removed (merged into designer)"
    )


def test_strategy_prompt_kept(cells: dict) -> None:
    c5 = cells["ea617348"]
    assert "STRATEGY_SYSTEM_PROMPT" in c5
    for field in ["selling_idea", "narrative_arc", "differentiator", "voice", "key_objections"]:
        assert field in c5, f"Strategy prompt missing field '{field}'"


# ============================================================
# Cell 6: Designer outputs gallery_briefs + metafield_briefs
# ============================================================

def test_designer_schema_has_gallery_briefs(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "gallery_briefs" in c6, "Designer prompt must list gallery_briefs in output schema"
    assert "EXACTLY 5 briefs" in c6 or "EXACTLY 5" in c6, (
        "Designer prompt must specify EXACTLY 5 gallery briefs"
    )


def test_designer_schema_has_metafield_briefs(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "metafield_briefs" in c6, "Designer prompt must list metafield_briefs in output schema"


def test_designer_uses_image_id_placeholders(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert '"image_id":"metafield/hero"' in c6, (
        "Designer schema must use image_id placeholders for hero (resolved by Step 3.7)"
    )
    assert '"image_id":"metafield/story_1"' in c6, (
        "Designer schema must use image_id placeholders for story chapters"
    )


def test_designer_brief_keys_documented(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for key in ["edit_instructions", "source_image_index", "aspect_ratio", "concept", "purpose"]:
        assert key in c6, f"Brief schema field '{key}' missing from designer prompt"


def test_designer_loaded_strategy_from_db(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "SELECT strategy_json FROM products WHERE id=?" in c6, (
        "Designer step must SELECT strategy_json from DB (Step 3.5 output)"
    )


def test_designer_does_not_load_image_plan(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "image_plan_json" not in c6, (
        "Designer step must not load image_plan_json (Image Strategy agent removed)"
    )


def test_designer_passes_eprolo_source_list(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "EPROLO SOURCE PHOTOS" in c6, (
        "Designer user message must show EPROLO source photo list (for source_image_index)"
    )
    assert "_eprolo_list" in c6


def test_designer_strategy_fields_referenced(cells: dict) -> None:
    c6 = cells["ce20f070"]
    for field in ["strategy.selling_idea", "strategy.narrative_arc",
                  "strategy.differentiator", "strategy.key_objections", "strategy.voice"]:
        assert field in c6, f"Designer prompt references '{field}'"


def test_designer_persists_assets_json(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "assets_json=json.dumps(_assets_initial" in c6, (
        "Designer must save initial assets_json (briefs without URLs yet)"
    )


# ============================================================
# Cell 6: STEP 3.7 image generation
# ============================================================

def test_image_gen_step_triggers_on_html_ready(cells: dict) -> None:
    c6 = cells["ce20f070"]
    # Find the STEP 3.7 block
    m = re.search(r"# ═══ STEP 3\.7: IMAGE GENERATION.*?(?=# ═══ STEP 5)", c6, re.DOTALL)
    assert m, "STEP 3.7 block not found"
    block = m.group(0)
    assert "if pstatus == 'html_ready':" in block, (
        "Image gen step must trigger after designer (html_ready)"
    )


def test_image_gen_substitutes_image_ids(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_sub_ids" in c6, "Image gen step must walk content and substitute image_id → image_url"
    assert "url_map[_iid]" in c6, "Image gen substitution must use url_map[id]"


def test_image_gen_handles_use_image_gen_false(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "if not USE_IMAGE_GEN or openai_client is None:" in c6, (
        "Image gen step must short-circuit when USE_IMAGE_GEN is False"
    )
    # Fallback path must still strip image_id placeholders so theme renders
    assert "_strip_ids" in c6


def test_image_gen_aspect_ratio_map(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_SIZE_MAP" in c6
    for ratio in ["1:1", "4:5", "16:9"]:
        assert f"'{ratio}'" in c6, f"_SIZE_MAP must cover ratio '{ratio}'"


def test_image_gen_quality_cost_map(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_COST_MAP" in c6
    for q in ["low", "medium", "high"]:
        assert f"'{q}'" in c6


def test_image_gen_uploads_to_shopify(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "openai_client.images.edit" in c6
    assert "upload_to_shopify(_upload_payload" in c6


def test_image_gen_fallback_to_eprolo_on_fail(cells: dict) -> None:
    c6 = cells["ce20f070"]
    # Failure inside per-brief loop must populate url_map with EPROLO URL as fallback.
    assert "url_map[_bid] = _src_url" in c6, (
        "On image gen failure, brief id must fallback-map to EPROLO source URL"
    )


def test_image_gen_skips_step5_double_run(cells: dict) -> None:
    """Step 5 must not start until images_generated is set."""
    c6 = cells["ce20f070"]
    # Find STEP 5 trigger
    m = re.search(r"# ═══ STEP 5: Shopify.*?if pstatus == '(\w+)':", c6, re.DOTALL)
    assert m, "STEP 5 trigger not found"
    assert m.group(1) == "images_generated", (
        f"STEP 5 must trigger on images_generated, got '{m.group(1)}'"
    )


# ============================================================
# Cell 6: STEP 5 gallery upload
# ============================================================

def test_step5_prefers_ai_gallery(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "_ai_gallery = _assets_pub.get('gallery_urls')" in c6, (
        "Step 5 must prefer AI-generated gallery_urls from assets_json"
    )
    assert "shopify_attach_media(shop_pid, gallery" in c6


def test_step5_fallback_to_eprolo(cells: dict) -> None:
    c6 = cells["ce20f070"]
    # When _ai_gallery is empty, fall back to EPROLO top photos.
    assert "img_data.get('top'" in c6, "Step 5 must keep EPROLO fallback for gallery"


# ============================================================
# Cross-cell consistency
# ============================================================

def test_palette_pastel_rules_consistent(cells: dict) -> None:
    """Both designer prompt and the strategy prompt should reference pastel rules."""
    c6 = cells["ce20f070"]
    assert "pastel" in c6.lower() or "PASTEL" in c6


def test_voice_options_consistent(cells: dict) -> None:
    """Voice values listed in strategy prompt and consumed in designer."""
    c5 = cells["ea617348"]
    c6 = cells["ce20f070"]
    voices = ["warm-confidant", "witty-irreverent", "clinical-precise",
              "editorial-thoughtful", "aspirational-luxury", "down-to-earth-honest"]
    for v in voices:
        assert v in c5, f"Voice '{v}' missing from strategy prompt"
    assert "strategy.voice" in c6


def test_no_legacy_image_strategy_remnants(cells: dict) -> None:
    """No code path should still reference the old image strategy concept."""
    for cid in ("477e495d", "ea617348", "ce20f070"):
        c = cells[cid]
        assert "MODEL_IMAGE_STRATEGY" not in c, f"[{cid}] still references MODEL_IMAGE_STRATEGY"
        assert "IMAGE_STRATEGY_SYSTEM_PROMPT" not in c, f"[{cid}] still references IMAGE_STRATEGY_SYSTEM_PROMPT"


# ============================================================
# Photo count: where 5 + N is enforced
# ============================================================

def test_designer_prompt_specifies_5_gallery(cells: dict) -> None:
    c6 = cells["ce20f070"]
    # Could be inline comment "EXACTLY 5" or schema mentioning 5
    assert ("EXACTLY 5" in c6) or ("Required slots: 1=" in c6), (
        "Designer prompt must specify EXACTLY 5 gallery briefs (Shopify carousel)"
    )


def test_image_gen_caps_gallery_to_constant(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "gallery_urls[:GALLERY_PHOTO_COUNT]" in c6, (
        "Image gen step must cap gallery_urls to GALLERY_PHOTO_COUNT (5)"
    )


def test_image_gen_warns_on_wrong_brief_count(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "expected {GALLERY_PHOTO_COUNT}" in c6, (
        "Designer step must warn when gallery brief count != GALLERY_PHOTO_COUNT"
    )
