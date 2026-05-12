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
    """All content metafields (hero, story, etc.) must remain visible to
    Storefront API — Liquid theme reads them. The admin-only set must be
    explicit and tight (only utility/internal fields: photo_pack ZIP +
    source EPROLO origin record)."""
    c2 = cells["b810afd7"]
    m = re.search(r"_admin_only\s*=\s*\{([^}]+)\}", c2)
    assert m, "_admin_only set declaration not found"
    members = {s.strip().strip("'\"") for s in m.group(1).split(',') if s.strip()}
    assert members == {"photo_pack", "source"}, (
        f"_admin_only must contain ONLY photo_pack + source; got {members}. "
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
    slot, source_index, concept, edit_instructions, slot_context."""
    c6 = cells["ce20f070"]
    assert '"photo_briefs":' in c6, (
        "Designer JSON schema must have photo_briefs[] field"
    )
    # Brief shape keys
    for key in ('"id":', '"slot":', '"source_index":', '"concept":',
                '"edit_instructions":', '"slot_context":'):
        assert key in c6, f"photo_briefs schema missing key {key}"


def test_designer_brief_has_slot_context(cells: dict) -> None:
    """slot_context is mandatory — designer must explain what buyer-question
    OR what page text the photo accompanies. Without it, the editor can't
    tailor the image to the page narrative."""
    c6 = cells["ce20f070"]
    assert "slot_context" in c6
    # Extraction or guidance must enforce it
    assert "what TEXT the photo accompanies" in c6 or "slot_context MUST" in c6


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
# CAROUSEL CONVERSION FUNNEL — buyer-question per slot
# ============================================================

def test_designer_describes_carousel_conversion_funnel(cells: dict) -> None:
    """Designer prompt must explain that the 5 carousel photos are a
    conversion funnel — each answers a specific buyer question in <2s."""
    c6 = cells["ce20f070"]
    assert "CAROUSEL CONVERSION FUNNEL" in c6, (
        "Designer prompt must include CAROUSEL CONVERSION FUNNEL section"
    )
    # Anchor inside the funnel block — the slots may also appear in schema
    # example/enum elsewhere, so we scope our search to the funnel block.
    funnel_start = c6.find("CAROUSEL CONVERSION FUNNEL")
    funnel_end = c6.find("INLINE SLOT SEMANTICS", funnel_start)
    assert funnel_end != -1, "INLINE SLOT SEMANTICS must follow CAROUSEL FUNNEL"
    block = c6[funnel_start:funnel_end]
    funnel_pairs = [
        ("carousel-hero",      ["What IS it", "what is it"]),
        ("carousel-lifestyle", ["Who uses it", "who uses"]),
        ("carousel-in-use",    ["How does it work", "how does it work"]),
        ("carousel-detail",    ["Is it quality", "is it quality"]),
        ("carousel-scale",     ["How big", "how big"]),
    ]
    for slot, question_variants in funnel_pairs:
        idx = block.find(slot)
        assert idx != -1, f"funnel block missing slot '{slot}'"
        window = block[idx:idx + 400]
        has_question = any(v in window for v in question_variants)
        assert has_question, (
            f"slot '{slot}' must be paired with one of {question_variants} "
            "in the funnel description"
        )


def test_designer_carousel_funnel_states_buyer_objection(cells: dict) -> None:
    """Funnel should explicitly call out the buyer objection each slot removes."""
    c6 = cells["ce20f070"]
    # Should mention removing objections / building trust language
    assert "objection" in c6.lower(), "carousel funnel must mention objections being removed"


# ============================================================
# INLINE SLOT SEMANTICS — match page narrative
# ============================================================

def test_designer_describes_inline_slot_semantics(cells: dict) -> None:
    """Each inline-* slot must have its narrative role explained so designer
    fills it correctly per page section. Scope check to INLINE SLOT SEMANTICS
    block — slots may appear in schema/enum elsewhere with no description."""
    c6 = cells["ce20f070"]
    sem_start = c6.find("INLINE SLOT SEMANTICS")
    assert sem_start != -1, "INLINE SLOT SEMANTICS section missing"
    # Block ends at next major section header (RULE/OUTPUT/PALETTE/COPY/etc.)
    sem_end = c6.find("OUTPUT:", sem_start)
    if sem_end == -1: sem_end = sem_start + 4000
    block = c6[sem_start:sem_end]
    for slot, expected in [
        ("inline-story-1", ["BEFORE", "PROBLEM", "before", "problem"]),
        ("inline-story-2", ["DISCOVERY", "SOLUTION", "discovery", "solution"]),
        ("inline-story-3", ["TRANSFORMATION", "RESULT", "transformation", "result"]),
    ]:
        idx = block.find(slot)
        assert idx != -1, f"INLINE block missing slot '{slot}'"
        window = block[idx:idx + 300]
        assert any(e in window for e in expected), (
            f"slot '{slot}' must be described as {expected[0]}/{expected[1]} state"
        )


def test_designer_inline_briefs_must_quote_actual_heading(cells: dict) -> None:
    """Rule: inline brief's slot_context must quote the actual H2/h4 from
    the corresponding section so the editor sees what TEXT it accompanies."""
    c6 = cells["ce20f070"]
    # Look for the rule statement
    assert "quote the actual H2" in c6 or "MUST quote" in c6


# ============================================================
# prompt.txt surfaces funnel + slot_context per brief
# ============================================================

def test_prompt_txt_includes_funnel_reference(cells: dict) -> None:
    """prompt.txt should have a Carousel funnel section so ChatGPT knows
    each carousel photo answers a different buyer question."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1
    txt = c6[idx:idx + 6000]
    assert "Carousel conversion funnel" in txt or "carousel conversion" in txt.lower()
    assert "buyer-question" in txt.lower() or "buyer question" in txt.lower()


def test_prompt_txt_per_brief_includes_slot_context(cells: dict) -> None:
    """Per-brief section must surface slot_context so ChatGPT sees the
    placement context for each photo."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1
    txt = c6[idx:idx + 6000]
    assert "Slot context:" in txt or "slot_context" in txt
    assert "_brief_pp.get('slot_context'" in c6, (
        "STEP 4.5 must read brief.slot_context and include it per brief"
    )


def test_prompt_txt_inline_placement_block(cells: dict) -> None:
    """prompt.txt should have a section explaining inline-* placement
    inside the page narrative — so editor knows the photo isn't standalone.
    Lives at the end of prompt.txt under 'Reference: inline placement'."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1
    # Look at the whole _prompt_lines block + Reference extends (8k window covers it).
    txt = c6[idx:idx + 8000]
    assert "inline placement" in txt.lower(), (
        "prompt.txt must include an inline placement reference block"
    )
    assert "inline-*" in txt, "prompt.txt must explain inline-* slot behavior"


def test_prompt_txt_workflow_mentions_carousel_priority(cells: dict) -> None:
    """The model instruction line must call out that carousel-* photos
    should prioritise the buyer-question over generic style."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1
    txt = c6[idx:idx + 6000]
    assert "buyer-question" in txt.lower() or "prioritise" in txt.lower() or "prioritize" in txt.lower()


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


def test_step45_caps_zip_at_50mb(cells: dict) -> None:
    """ZIP must be capped at 50 MB to avoid Shopify staged-upload failure
    on huge EPROLO photos. Briefs that push over the cap are dropped (in order)."""
    c6 = cells["ce20f070"]
    assert "_MAX_ZIP_BYTES = 50 * 1024 * 1024" in c6
    assert "_files_capped" in c6
    assert "ZIP cap" in c6 and "dropping brief" in c6


def test_designer_retries_on_parse_fail(cells: dict) -> None:
    """If all 3 parse-fallback attempts fail (or yield empty), Designer
    is called once more with error context to recover."""
    c6 = cells["ce20f070"]
    assert "PREVIOUS ATTEMPT FAILED" in c6, (
        "Designer must retry once with error-context user message"
    )
    assert "_retry_user" in c6
    assert "_r2_retry" in c6
    # Cost from retry must be added to cost2 so per-product spend reflects reality
    assert "cost2 += _r2_retry.usage" in c6


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


def test_step45_payload_is_plain_url(cells: dict) -> None:
    """photo_pack metafield is now type 'url' — value is the raw URL string,
    NOT a JSON dict. Shopify Admin renders it as a one-click download button."""
    c6 = cells["ce20f070"]
    # Plain URL assignment into sections dict (no wrapper dict)
    assert "['photo_pack'] = _upload_res['url']" in c6, (
        "photo_pack must be stored as plain URL string (type 'url'), "
        "not a wrapper dict — otherwise Admin can't render the clickable button"
    )
    # And the old dict shape must be gone — otherwise metafieldsSet would push
    # a JSON-encoded dict to a url-typed field and Shopify would reject.
    assert "_photo_pack = {" not in c6, (
        "photo_pack dict literal must be removed — type is now 'url'"
    )


def test_step45_injects_into_final_html(cells: dict) -> None:
    """photo_pack URL stored in sections dict so Step 5 metafieldsSet picks it up."""
    c6 = cells["ce20f070"]
    assert "['photo_pack'] = _upload_res['url']" in c6


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

def test_prompt_txt_contains_model_instructions(cells: dict) -> None:
    """prompt.txt (model context) must have explicit 'Instructions for the
    image model' section at the top with visual style + per-brief edits.
    Operator-workflow language (ChatGPT-UI / Download / Shopify Admin) must
    NOT live in prompt.txt — that's README.md territory."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    assert idx != -1, "_prompt_lines list not found"
    txt = c6[idx:idx + 3500]
    assert "Instructions for the image model" in txt, (
        "prompt.txt must have explicit model-instruction header"
    )
    assert "visual style" in txt.lower(), "missing 'visual style' header"
    assert "carousel" in txt.lower(), "missing carousel mention"


def test_prompt_txt_has_no_operator_workflow_language(cells: dict) -> None:
    """prompt.txt must NOT include operator-workflow phrases like 'Open a NEW
    chat', 'Download edited photos', 'In Shopify Admin'. Those live in
    README.md and would confuse the model if uploaded as context."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    end = c6.find("_prompt_txt = ", idx)
    assert idx != -1 and end != -1
    prompt_block = c6[idx:end]
    for forbidden in ("Open a NEW chat", "Download edited photos",
                      "In Shopify Admin", "Drop edited"):
        assert forbidden not in prompt_block, (
            f"prompt.txt must NOT contain operator-only phrase: {forbidden!r}"
        )


def test_prompt_txt_includes_per_brief_section(cells: dict) -> None:
    """Each brief gets its own ### section with Slot context / Concept /
    Edit instructions. Source URL must NOT be in prompt.txt (lives in
    manifest.json — operator-only audit data)."""
    c6 = cells["ce20f070"]
    idx = c6.find("_prompt_lines = [")
    end = c6.find("_prompt_txt = ", idx)
    assert idx != -1 and end != -1
    prompt_block = c6[idx:end]
    assert "Concept:" in prompt_block
    assert "Edit instructions:" in prompt_block
    assert "Slot context:" in prompt_block
    # Source URL must NOT leak into prompt.txt — it's audit-only operator data.
    assert "Source URL:" not in prompt_block, (
        "Source URL must live in manifest.json, NOT prompt.txt (noise for model)"
    )


# ============================================================
# photo_pack = type 'url' (one-click download button in Admin)
# ============================================================

def test_photo_pack_definition_uses_url_type(cells: dict) -> None:
    """Cell 2 must register photo_pack with type 'url' (not 'json'). Shopify
    Admin renders url-typed metafields as a clickable hyperlink — that's
    the one-click download UX the operator gets."""
    c2 = cells["b810afd7"]
    pat = re.compile(r"_type_overrides\s*=\s*\{([^}]+)\}")
    m = pat.search(c2)
    assert m, "_type_overrides dict not found in Cell 2"
    body = m.group(1)
    assert "'photo_pack'" in body and "'url'" in body, (
        "photo_pack must be mapped to 'url' in _type_overrides"
    )


def test_cell2_loop_uses_type_override_lookup(cells: dict) -> None:
    """The Cell 2 ensure-loop must pass type_name=_type_overrides.get(_k, 'json')
    — not the hardcoded 'json' it used to."""
    c2 = cells["b810afd7"]
    assert "type_name=_type_overrides.get(_k, 'json')" in c2, (
        "Loop must look up per-key type via _type_overrides (json default)"
    )


def test_metafieldsset_special_cases_photo_pack_as_url(cells: dict) -> None:
    """Step 5 metafieldsSet payload must send photo_pack with type='url' and a
    plain-URL string value — sending a JSON-encoded dict to a url-typed field
    would be rejected by Shopify."""
    c6 = cells["ce20f070"]
    assert "_mf_types = {'photo_pack': 'url'}" in c6, (
        "Step 5 must declare per-key type override for photo_pack"
    )
    # The loop must branch on type and skip JSON-encoding for url-typed fields
    assert 'if _t == \'url\':' in c6 or "if _t == 'url':" in c6, (
        "metafieldsSet loop must special-case type 'url' to avoid json.dumps"
    )


def test_metafieldsset_skips_photo_pack_when_upload_failed(cells: dict) -> None:
    """If ZIP upload failed earlier, photo_pack URL is absent — must skip
    that entry rather than send empty/None value, which Shopify rejects."""
    c6 = cells["ce20f070"]
    assert "not isinstance(_v, str) or not _v.startswith('http')" in c6, (
        "url-typed metafield entries must be skipped when value isn't a real URL"
    )


# ============================================================
# Zero-leak: photo_pack URL must NEVER reach storefront HTML
# ============================================================

def test_body_html_assembly_never_uses_photo_pack(cells: dict) -> None:
    """The product body_html string (= description shown in PDP <body>) is
    assembled from short_desc + hero + pain_points. Must NOT pull from
    sections['photo_pack'] or include the ZIP URL."""
    c6 = cells["ce20f070"]
    # Grab the body_html assembly block
    idx = c6.find("body_parts = [")
    assert idx != -1, "body_parts assembly not found in Cell 6"
    body_block = c6[idx:idx + 1500]
    assert "photo_pack" not in body_block, (
        "body_html assembly block must NOT reference photo_pack"
    )
    assert "_upload_res" not in body_block, (
        "body_html must not pull ZIP upload URL into the description"
    )


def test_theme_css_does_not_reference_photo_pack() -> None:
    """wanelo.css must not reference photo_pack — no styles for it, ever
    (would imply some snippet renders it)."""
    css = (ROOT / "pipeline" / "theme_assets" / "assets" / "wanelo.css").read_text(encoding="utf-8")
    assert "photo_pack" not in css and "photo-pack" not in css, (
        "wanelo.css must not contain photo_pack styles"
    )


def test_theme_js_does_not_reference_photo_pack() -> None:
    """wanelo.js (storefront JS) must not reference photo_pack — would imply
    a runtime fetch of the admin-only ZIP URL."""
    js_path = ROOT / "pipeline" / "theme_assets" / "assets" / "wanelo.js"
    if js_path.exists():
        js = js_path.read_text(encoding="utf-8")
        assert "photo_pack" not in js and "photo-pack" not in js, (
            "wanelo.js must not reference photo_pack"
        )


def test_no_hidden_attribute_renders_photo_pack() -> None:
    """Catch any `hidden`, `display:none`, `aria-hidden`, or `data-photo-pack`
    pattern in theme files — common ways developers accidentally embed an
    admin-only URL invisibly in DOM, which view-source would still expose."""
    pat = re.compile(
        r"(hidden|display\s*:\s*none|aria-hidden|sr-only|visually-hidden)"
        r"[^>]{0,200}(photo[_-]pack|photo_pack)",
        re.IGNORECASE | re.DOTALL,
    )
    for sub in ("snippets", "sections", "assets"):
        for f in (ROOT / "pipeline" / "theme_assets" / sub).glob("*"):
            if not f.is_file():
                continue
            txt = f.read_text(encoding="utf-8", errors="ignore")
            assert not pat.search(txt), (
                f"{f.name}: appears to embed photo_pack in a hidden DOM element. "
                "Admin-only data must never reach storefront HTML, even hidden."
            )


# ============================================================
# Funnel-ordered filenames
# ============================================================

def test_briefs_sorted_by_funnel_position(cells: dict) -> None:
    """Briefs must be sorted by carousel-funnel order before being numbered,
    so filenames `01-..., 02-...` map to the slot order the operator should
    use when dropping into Shopify carousel."""
    c6 = cells["ce20f070"]
    assert "_FUNNEL_ORDER = [" in c6, (
        "STEP 4.5 must declare an explicit funnel order constant"
    )
    # Must contain at minimum the 5 carousel slots in conversion order
    pat = re.compile(r"_FUNNEL_ORDER\s*=\s*\[(.*?)\]", re.DOTALL)
    m = pat.search(c6)
    assert m, "_FUNNEL_ORDER list not found"
    body = m.group(1)
    hero = body.find("'carousel-hero'")
    lifestyle = body.find("'carousel-lifestyle'")
    in_use = body.find("'carousel-in-use'")
    detail = body.find("'carousel-detail'")
    scale = body.find("'carousel-scale'")
    assert hero < lifestyle < in_use < detail < scale, (
        "carousel slots must be listed in conversion-funnel order: "
        "hero → lifestyle → in-use → detail → scale"
    )
    # And the sort must actually be applied to _resolved
    assert "_resolved.sort(" in c6, "_resolved list must be sorted before naming"
    assert "_funnel_idx.get" in c6, "Sort key must use the funnel index lookup"


def test_unknown_slots_sort_after_known(cells: dict) -> None:
    """Slots not in the funnel must sort AFTER known ones (key=999), so the
    carousel order isn't disrupted by an unexpected slot name."""
    c6 = cells["ce20f070"]
    assert "999" in c6, (
        "Unknown slots must sort to the back via a large fallback index (999)"
    )


# ============================================================
# README.md — operator workflow (separated from prompt.txt)
# ============================================================

def test_readme_md_is_written_to_zip(cells: dict) -> None:
    """ZIP must include README.md so the operator has workflow docs separately
    from the model-instruction prompt.txt."""
    c6 = cells["ce20f070"]
    assert "_zip.writestr('README.md'," in c6, (
        "ZIP must include README.md (operator workflow)"
    )
    assert "_readme_lines = [" in c6, "_readme_lines list literal required"
    assert '_zip.writestr(\'README.md\',     _readme_txt)' in c6 or \
           "_zip.writestr('README.md', _readme_txt)" in c6


def test_readme_explains_funnel_filename_order(cells: dict) -> None:
    """README.md must explicitly tell the operator that filenames are
    pre-sorted by conversion funnel — this is the whole point of #3."""
    c6 = cells["ce20f070"]
    idx = c6.find("_readme_lines = [")
    assert idx != -1
    end = c6.find("_readme_txt = ", idx)
    assert end != -1
    readme = c6[idx:end]
    assert "FILENAME ORDER" in readme or "filename order" in readme.lower(), (
        "README must instruct operator to use filename order"
    )
    assert "funnel" in readme.lower(), "README must mention the funnel sort"


def test_readme_lists_inline_metafield_mapping(cells: dict) -> None:
    """README must tell operator which metafield image_url field each
    inline-* slot maps to."""
    c6 = cells["ce20f070"]
    idx = c6.find("_readme_lines = [")
    end = c6.find("_readme_txt = ", idx)
    readme = c6[idx:end]
    assert "custom.hero.image_url" in readme
    assert "custom.story.chapters" in readme


def test_readme_tells_operator_not_to_upload_readme(cells: dict) -> None:
    """README.md must warn that operator should NOT upload it as model context
    (would confuse model with operator-workflow language)."""
    c6 = cells["ce20f070"]
    idx = c6.find("_readme_lines = [")
    end = c6.find("_readme_txt = ", idx)
    readme = c6[idx:end]
    assert "do NOT upload" in readme or "operator only" in readme.lower() or \
           "do not upload" in readme.lower(), (
        "README must warn against uploading itself as model context"
    )


# ============================================================
# manifest.json — audit trail (filename → EPROLO source URL)
# ============================================================

def test_manifest_json_is_written_to_zip(cells: dict) -> None:
    """ZIP must include manifest.json with audit data (filename → source URL)."""
    c6 = cells["ce20f070"]
    assert "_zip.writestr('manifest.json'," in c6
    assert "_manifest = {" in c6
    assert "json.dumps(_manifest" in c6


def test_manifest_includes_per_brief_audit_fields(cells: dict) -> None:
    """Manifest must have filename / slot / source_url / source_index per
    brief so the operator can verify which EPROLO photo each brief used."""
    c6 = cells["ce20f070"]
    idx = c6.find("_manifest = {")
    end = c6.find("_manifest_txt = ", idx)
    assert idx != -1 and end != -1
    manifest_block = c6[idx:end]
    for field in ("'filename'", "'slot'", "'source_url'", "'source_index'",
                  "'concept'", "'edit_instructions'", "'slot_context'"):
        assert field in manifest_block, (
            f"manifest.json brief shape missing field {field}"
        )


def test_manifest_includes_visual_style_and_timestamp(cells: dict) -> None:
    """Manifest header must record the visual_style and created_at so audit
    can reconstruct what style was used when the ZIP was built."""
    c6 = cells["ce20f070"]
    idx = c6.find("_manifest = {")
    end = c6.find("_manifest_txt = ", idx)
    manifest_block = c6[idx:end]
    assert "'visual_style'" in manifest_block
    assert "'created_at'" in manifest_block
    assert "'product_title'" in manifest_block


# ============================================================
# Smart visual_style fallback (palette + voice)
# ============================================================

def test_no_generic_editorial_fallback(cells: dict) -> None:
    """The old hardcoded fallback 'Editorial product photography. Soft
    north-light...' must be REMOVED — it conflicted with pastel section
    palettes and produced inconsistent ZIP edits vs page."""
    c6 = cells["ce20f070"]
    assert "Pure white seamless or muted neutral background" not in c6, (
        "Generic editorial fallback must be removed — built personalized "
        "fallback from palette+voice instead"
    )


def test_visual_style_fallback_uses_palette(cells: dict) -> None:
    """When Designer didn't emit visual_style, fallback must build from
    palette + strategy.voice so the ZIP style matches the page palette."""
    c6 = cells["ce20f070"]
    assert "_palette_hex" in c6, "Fallback must inspect product palette"
    assert "brand_soft" in c6 and "brand_deep" in c6, (
        "Fallback must read brand_1/2/3/soft/deep from palette section"
    )


def test_visual_style_fallback_uses_strategy_voice(cells: dict) -> None:
    """Fallback must read strategy.voice from DB and map it to a tone anchor
    (warm-confidant → 'warm intimate framing', etc.)."""
    c6 = cells["ce20f070"]
    assert "strategy_json" in c6, "Fallback must read strategy_json from DB"
    # voice tone anchors must be present
    voice_anchors = ['warm-confidant', 'witty-irreverent', 'clinical-precise',
                     'editorial-thoughtful', 'aspirational-luxury', 'down-to-earth-honest']
    for v in voice_anchors:
        assert v in c6, f"Fallback must map voice '{v}' to a tone anchor"


def test_skips_zip_when_no_visual_style_and_no_fallback_data(cells: dict) -> None:
    """If Designer emitted no visual_style AND no palette/voice exists,
    must skip ZIP gracefully — never build with a generic fallback."""
    c6 = cells["ce20f070"]
    pat = re.compile(
        r"if not _visual_style_pp:\s*\n\s*print\([^)]*Photo pack: skip"
        r"[^)]*no visual_style",
        re.DOTALL,
    )
    assert pat.search(c6), (
        "STEP 4.5 must skip ZIP when no visual_style is available"
    )


# ============================================================
# Photo download retry (transient EPROLO CDN errors)
# ============================================================

def test_photo_download_has_retry_loop(cells: dict) -> None:
    """For 10K-product unattended runs, EPROLO CDN can blip — single failure
    must NOT silently drop the brief. 3 attempts with exp backoff."""
    c6 = cells["ce20f070"]
    pat = re.compile(
        r"for _att in range\(3\):.*?_c_dl_pp\.get\(_src_url_pp\)",
        re.DOTALL,
    )
    assert pat.search(c6), (
        "Photo download must use 3-attempt retry loop"
    )
    # exponential backoff (1s, 2s)
    assert "2 ** _att" in c6 or "asyncio.sleep(2" in c6, (
        "Retry must use exponential backoff between attempts"
    )


def test_photo_download_logs_final_failure(cells: dict) -> None:
    """After all 3 attempts fail, the brief must be reported (not silently
    dropped) so operator can investigate."""
    c6 = cells["ce20f070"]
    assert "download failed after 3 attempts" in c6, (
        "Final-fail message must announce the brief id + 3-attempt failure"
    )
