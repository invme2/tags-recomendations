"""Tests for the photo_pack feature — ZIP archive of EPROLO photos + ChatGPT
prompt.txt, uploaded to Shopify Files, URL stored in custom.photo_pack metafield.

Workflow this enables:
  1. Pipeline creates ZIP per product after Designer finishes
  2. URL stored in custom.photo_pack JSON metafield
  3. User downloads ZIP, runs through ChatGPT-UI (multi-image conversation
     preserves style across all photos — better than per-image API calls)
  4. User uploads edited photos back to Shopify product manually

Tests verify the structural pieces without running the pipeline.
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
# Cell 2: metafield definition + upload helper
# ============================================================

def test_cell2_creates_photo_pack_definition(cells: dict) -> None:
    c2 = cells["b810afd7"]
    assert "('photo_pack'," in c2, (
        "Cell 2 must create custom.photo_pack metafield definition"
    )
    assert "'Wanelo · Photo Pack'" in c2


def test_cell2_has_shopify_upload_file_helper(cells: dict) -> None:
    """Helper must exist for non-image file uploads (ZIPs, generic FILE type)."""
    c2 = cells["b810afd7"]
    assert "async def shopify_upload_file(" in c2, (
        "Cell 2 must define shopify_upload_file(file_bytes, filename, mime_type, alt) helper"
    )
    assert '"contentType":"FILE"' in c2 or '"contentType": "FILE"' in c2, (
        "Helper must use fileCreate with contentType FILE (not IMAGE) for ZIPs"
    )


def test_cell2_helper_uses_staged_uploads(cells: dict) -> None:
    """Shopify ≥40 MB files require stagedUploadsCreate handshake."""
    c2 = cells["b810afd7"]
    assert "stagedUploadsCreate" in c2
    assert 'GenericFile' in c2, (
        "Helper must request GenericFile.url from fileCreate response (not MediaImage)"
    )


# ============================================================
# Cell 6: Designer outputs visual_style for ChatGPT prompt
# ============================================================

def test_designer_schema_has_visual_style(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert '"visual_style":' in c6, (
        "Designer JSON schema must have visual_style field "
        "(used as photo-edit prompt in photo_pack ZIP)"
    )


def test_designer_extracts_visual_style_into_meta(cells: dict) -> None:
    """visual_style must be tucked into meta so STEP 4.5 can read it."""
    c6 = cells["ce20f070"]
    assert "meta['visual_style']" in c6, (
        "Designer step must save visual_style into meta dict"
    )


# ============================================================
# Cell 6: STEP 4.5 photo_pack packaging
# ============================================================

def test_step45_block_exists(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "STEP 4.5: PHOTO PACK" in c6, (
        "Cell 6 must have a STEP 4.5: PHOTO PACK block between html_ready and Step 5"
    )


def test_step45_triggers_on_html_ready(cells: dict) -> None:
    c6 = cells["ce20f070"]
    pat = re.compile(r"# ═══ STEP 4\.5: PHOTO PACK.*?if pstatus == '(\w+)':", re.DOTALL)
    m = pat.search(c6)
    assert m, "STEP 4.5 trigger not found"
    assert m.group(1) == "html_ready", (
        f"STEP 4.5 must trigger on html_ready, got '{m.group(1)}'"
    )


def test_step45_uses_zipfile(cells: dict) -> None:
    """Pipeline packs in-memory ZIP using stdlib zipfile."""
    c6 = cells["ce20f070"]
    assert "import zipfile as _zf" in c6
    assert "_zf.ZIP_DEFLATED" in c6
    assert "writestr('prompt.txt'" in c6, (
        "ZIP must include prompt.txt — the ChatGPT edit-prompt"
    )
    assert "writestr(f'photos/" in c6, (
        "ZIP must include photos/ directory with EPROLO sources"
    )


def test_step45_calls_upload_helper(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "shopify_upload_file(" in c6, (
        "STEP 4.5 must call shopify_upload_file helper"
    )
    assert "'application/zip'" in c6, (
        "Upload must specify application/zip MIME type"
    )


def test_step45_payload_shape(cells: dict) -> None:
    """photo_pack metafield JSON must have url + size_kb + photo_count + created_at."""
    c6 = cells["ce20f070"]
    for field in ("'url':", "'size_kb':", "'photo_count':", "'created_at':", "'instructions':"):
        assert field in c6, f"photo_pack payload missing field: {field}"


def test_step45_injects_into_final_html(cells: dict) -> None:
    """photo_pack stored in sections dict so Step 5 metafieldsSet picks it up."""
    c6 = cells["ce20f070"]
    assert "['photo_pack'] = _photo_pack" in c6


def test_step45_failure_is_non_blocking(cells: dict) -> None:
    """ZIP failure must not block product publication — wrapped in try/except."""
    c6 = cells["ce20f070"]
    pat = re.compile(
        r"# ═══ STEP 4\.5: PHOTO PACK.*?# ═══ STEP 5",
        re.DOTALL,
    )
    block = pat.search(c6)
    assert block, "STEP 4.5 block not found"
    body = block.group(0)
    assert "try:" in body and "except Exception" in body, (
        "STEP 4.5 must be wrapped in try/except so a ZIP failure doesn't kill the run"
    )


# ============================================================
# Step 5: photo_pack pushed to Shopify metafields
# ============================================================

def test_photo_pack_in_wanelo_keys(cells: dict) -> None:
    c6 = cells["ce20f070"]
    pat = re.compile(r"_wanelo_keys = \[(.*?)\]", re.DOTALL)
    m = pat.search(c6)
    assert m, "_wanelo_keys not found"
    assert "'photo_pack'" in m.group(1), (
        "_wanelo_keys must include 'photo_pack' — otherwise URL doesn't reach Shopify"
    )


# ============================================================
# Prompt.txt content quality
# ============================================================

def test_prompt_txt_contains_workflow_steps(cells: dict) -> None:
    """prompt.txt must explain the ChatGPT-UI workflow so the user knows what to do."""
    c6 = cells["ce20f070"]
    # Locate prompt_txt section by anchoring on '_prompt_txt = (' and the
    # closing matched paren — search next ~3000 chars (large enough for prompt body).
    idx = c6.find("_prompt_txt = (")
    assert idx != -1, "_prompt_txt construction not found"
    txt = c6[idx:idx + 3000]
    assert "Visual style" in txt or "visual style" in txt, "missing 'Visual style'"
    assert "ChatGPT" in txt, "missing 'ChatGPT' reference"
    assert "carousel" in txt.lower() or "gallery" in txt.lower()


def test_prompt_txt_includes_source_urls(cells: dict) -> None:
    """User may want originals — list source URLs in prompt.txt."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_txt = (")
    assert idx != -1
    txt = c6[idx:idx + 3000]
    assert "Source URLs" in txt or "source URL" in txt.lower()
