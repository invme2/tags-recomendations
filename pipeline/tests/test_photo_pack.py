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
# Admin-only access — photo_pack must NOT be exposed via Storefront API
# ============================================================

def test_definition_helper_supports_storefront_access(cells: dict) -> None:
    """shopify_ensure_metafield_definition must accept a visible_to_storefront
    flag and pass through to access.storefront in the GraphQL input."""
    c2 = cells["b810afd7"]
    assert "visible_to_storefront" in c2, (
        "Helper signature must accept visible_to_storefront parameter"
    )
    assert '"storefront":' in c2 or "'storefront':" in c2, (
        "Helper must build access.storefront field in MetafieldDefinitionInput"
    )
    assert '"NONE"' in c2 or "'NONE'" in c2, (
        "Helper must use storefront=NONE for admin-only definitions"
    )


def test_photo_pack_is_admin_only_in_loop(cells: dict) -> None:
    """Cell 2 loop must mark photo_pack as admin-only (visible_to_storefront=False)."""
    c2 = cells["b810afd7"]
    assert "_admin_only" in c2 and "'photo_pack'" in c2, (
        "Cell 2 must declare _admin_only set containing 'photo_pack'"
    )
    assert "visible_to_storefront=(_k not in _admin_only)" in c2, (
        "Loop must pass visible_to_storefront based on admin-only set membership"
    )


def test_other_metafields_remain_storefront_visible(cells: dict) -> None:
    """All other metafields (hero, story, etc.) must remain visible to
    Storefront API — Liquid theme reads them. The admin-only set must be
    explicit and tight (only utility/internal fields)."""
    c2 = cells["b810afd7"]
    # _admin_only set should contain ONLY photo_pack right now — anything else
    # would silently break theme rendering. Use a regex to extract the set.
    m = re.search(r"_admin_only\s*=\s*\{([^}]+)\}", c2)
    assert m, "_admin_only set declaration not found"
    members = {s.strip().strip("'\"") for s in m.group(1).split(',') if s.strip()}
    assert members == {"photo_pack"}, (
        f"_admin_only must contain ONLY photo_pack; got {members}. "
        "Adding other keys would hide content metafields from Liquid."
    )


# ============================================================
# Customer-facing markup must NOT reference photo_pack
# ============================================================

def test_no_liquid_snippet_references_photo_pack() -> None:
    """No Liquid snippet should read product.metafields.custom.photo_pack —
    photo_pack is an admin utility, not page content."""
    snippets_dir = ROOT / "pipeline" / "theme_assets" / "snippets"
    for snippet_path in snippets_dir.glob("*.liquid"):
        content = snippet_path.read_text(encoding="utf-8")
        assert "photo_pack" not in content, (
            f"{snippet_path.name}: must NOT reference photo_pack — "
            "snippet would expose ZIP URL to storefront markup"
        )


def test_master_section_does_not_render_photo_pack() -> None:
    """The master section must not include photo_pack in its render list."""
    section = (ROOT / "pipeline" / "theme_assets" / "sections" /
               "wanelo-product-page.liquid").read_text(encoding="utf-8")
    assert "photo_pack" not in section, (
        "Master section must NOT render photo_pack — utility-only metafield"
    )
    assert "photo-pack" not in section, (
        "Master section must NOT render any photo-pack snippet"
    )


def test_body_html_does_not_include_photo_pack(cells: dict) -> None:
    """Step 5 body_html (the product description shown above the metafields)
    must not embed the photo_pack URL."""
    c6 = cells["ce20f070"]
    # Find the body_html assembly section
    pat = re.compile(r"body_parts\s*=\s*\[(.*?)\]\s*\n", re.DOTALL)
    m = pat.search(c6)
    if m:
        body = m.group(1)
        assert "photo_pack" not in body, "body_html must not embed photo_pack"
    # Also check body_html itself doesn't reference it
    body_idx = c6.find("body_html = ")
    if body_idx != -1:
        chunk = c6[body_idx:body_idx + 500]
        assert "photo_pack" not in chunk


# ============================================================
# Cell 6: Designer outputs visual_style + photo_briefs[]
# ============================================================

def test_designer_schema_has_visual_style(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert '"visual_style":' in c6, (
        "Designer JSON schema must have visual_style field "
        "(unified style anchor used in photo_pack prompt.txt)"
    )


def test_designer_schema_has_photo_briefs(cells: dict) -> None:
    """Designer decides count + content of briefs (5-12). Each brief specifies
    slot, source_index, concept, edit_instructions."""
    c6 = cells["ce20f070"]
    assert '"photo_briefs":' in c6, (
        "Designer JSON schema must have photo_briefs[] field"
    )
    # Brief shape keys
    for key in ('"id":', '"slot":', '"source_index":', '"concept":', '"edit_instructions":'):
        assert key in c6, f"photo_briefs schema missing key {key}"


def test_designer_brief_slots_listed(cells: dict) -> None:
    """Slot enum includes carousel-* and inline-* values for clear placement."""
    c6 = cells["ce20f070"]
    for slot in ("carousel-hero", "carousel-lifestyle", "carousel-detail",
                 "inline-hero", "inline-story-1"):
        assert slot in c6, f"slot enum missing '{slot}'"


def test_designer_extracts_visual_style_into_meta(cells: dict) -> None:
    c6 = cells["ce20f070"]
    assert "meta['visual_style']" in c6


def test_designer_extracts_photo_briefs_into_meta(cells: dict) -> None:
    """photo_briefs must be persisted in meta so STEP 4.5 can read them
    after the designer step writes final_html."""
    c6 = cells["ce20f070"]
    assert "meta['photo_briefs']" in c6


def test_designer_instructions_explain_quality_over_quantity(cells: dict) -> None:
    """Goal: designer should pick FEWER strong briefs over many weak ones."""
    c6 = cells["ce20f070"]
    assert "QUALITY" in c6 or "quality" in c6
    # Count rule: 5-12 typical, designer-decided
    assert "5-12" in c6 or "5\\u201312" in c6


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
    assert "f'photos/" in c6, (
        "ZIP must include photos/ directory with descriptive filenames"
    )


def test_step45_drives_off_briefs(cells: dict) -> None:
    """STEP 4.5 reads briefs from meta — does NOT bundle ALL EPROLO photos.
    Quality > quantity: only briefed photos go into the ZIP."""
    c6 = cells["ce20f070"]
    assert "_photo_briefs_pp" in c6 or "photo_briefs" in c6
    assert "_resolved" in c6, (
        "STEP 4.5 must resolve briefs to source URLs (not bundle everything)"
    )
    # Must read briefs from meta, not just dump all _all_eprolo
    assert "_meta_pp.get('photo_briefs')" in c6


def test_step45_filenames_use_slot(cells: dict) -> None:
    """Filenames in ZIP must include the brief's slot (e.g. 01-carousel-hero.jpg)
    so user can drop them into Shopify product images correctly."""
    c6 = cells["ce20f070"]
    assert "_safe_slot" in c6, "STEP 4.5 must build descriptive filenames using slot"


def test_step45_caps_briefs_at_30(cells: dict) -> None:
    """Defensive cap so a runaway designer (e.g. emits 100 briefs) doesn't
    create a huge ZIP that times out the upload."""
    c6 = cells["ce20f070"]
    assert "_resolved[:30]" in c6 or "[:30]" in c6, (
        "STEP 4.5 should cap briefs at 30 to prevent oversized ZIPs"
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
    """prompt.txt must explain the ChatGPT-UI workflow per-brief."""
    c6 = cells["ce20f070"]
    # Now built via "\n".join(_prompt_lines) — anchor on _prompt_lines list literal
    idx = c6.find("_prompt_lines = [")
    assert idx != -1, "_prompt_lines list not found"
    txt = c6[idx:idx + 3500]
    assert "visual style" in txt.lower(), "missing 'visual style' header"
    assert "ChatGPT-UI" in txt or "ChatGPT" in txt
    assert "carousel" in txt.lower() or "gallery" in txt.lower()


def test_prompt_txt_includes_per_brief_section(cells: dict) -> None:
    """Each brief gets its own ### section with Concept/Edit/Source URL fields."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1
    txt = c6[idx:idx + 3500]
    assert "Concept:" in txt
    assert "Edit instructions:" in txt
    assert "Source URL:" in txt
