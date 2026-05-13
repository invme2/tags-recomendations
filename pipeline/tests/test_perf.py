"""Performance reliability tests — explicit Anthropic timeouts + base64 cleanup.

Both are unattended-10K-batch hardening:
  - Without explicit timeout, hung Anthropic call blocks worst-case 10 min × 5
    retries = 50 min per stuck product
  - Without base64 cleanup after Vision, image_urls_json grows ~2-3 MB per
    product (Vision uses base64 of 4+4 images); 10K × 2.5 MB = 25 GB in DB
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
# Explicit Anthropic timeouts on every messages.create call
# ============================================================

def test_every_anthropic_call_has_explicit_timeout(cells: dict) -> None:
    """Every client.messages.create(...) call MUST pass an explicit timeout=
    kwarg. SDK default is 10 min, which times-and-retries to 50 min per
    stuck call — catastrophic for unattended batches.

    Method: regex over each cell looking for messages.create(... ) without
    a `timeout=` inside the same call expression.
    """
    # Pattern: 'messages.create' followed by parameters up to closing ')'
    # Multiline, non-greedy, must contain matching close-paren that
    # terminates the call. We then assert 'timeout=' is inside.
    pat = re.compile(r"messages\.create\((.*?)\)\s*\n", re.DOTALL)
    offenders = []
    for cid, src in cells.items():
        for m in pat.finditer(src):
            args = m.group(1)
            # Skip helper definitions / mocked usages
            if "def " in args:
                continue
            if "timeout=" not in args:
                # Report cell id + first 80 chars of the args for debugging
                snippet = re.sub(r"\s+", " ", args)[:100]
                offenders.append(f"{cid}: messages.create({snippet}...)")
    assert not offenders, (
        "All messages.create calls must pass explicit timeout=. Missing in:\n"
        + "\n".join("  " + s for s in offenders)
    )


def test_designer_timeout_is_at_least_two_minutes(cells: dict) -> None:
    """Designer emits ~16k tokens of JSON — generation time is real.
    Timeout must be ≥ 120s. Anything tighter fails on slow batches."""
    c6 = cells["ce20f070"]
    # Designer call sites use max_tokens=16000 — find their timeouts
    pat = re.compile(r"max_tokens=16000,\s*timeout=(\d+(?:\.\d+)?)")
    timeouts = [float(m.group(1)) for m in pat.finditer(c6)]
    assert timeouts, "No Designer (max_tokens=16000) call sites found"
    for t in timeouts:
        assert t >= 120.0, (
            f"Designer call timeout={t}s too tight (must be ≥120s)"
        )


def test_strategy_timeout_is_reasonable(cells: dict) -> None:
    """Strategy emits ~4096 tokens — 90-180s is appropriate."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"max_tokens=4096,\s*timeout=(\d+(?:\.\d+)?)")
    m = pat.search(c6)
    assert m, "Strategy call (max_tokens=4096, timeout=) not found"
    t = float(m.group(1))
    assert 60.0 <= t <= 240.0, f"Strategy timeout={t}s outside reasonable 60-240s range"


def test_vision_timeout_is_at_least_one_minute(cells: dict) -> None:
    """Vision sends base64 images + 2000 tokens response — needs ≥60s."""
    c6 = cells["ce20f070"]
    pat = re.compile(r"max_tokens=2000,\s*timeout=(\d+(?:\.\d+)?)")
    timeouts = [float(m.group(1)) for m in pat.finditer(c6)]
    assert timeouts, "No Vision call sites with timeout found"
    for t in timeouts:
        assert t >= 60.0, f"Vision timeout={t}s too tight (must be ≥60s)"


# ============================================================
# Base64 cleanup after Vision (DB bloat protection)
# ============================================================

def test_base64_cleaned_after_vision(cells: dict) -> None:
    """After Step 3 succeeds, top_b64 and desc_b64 must be removed from
    image_urls_json — otherwise DB grows ~2-3 MB per product × 10K = 25 GB.

    Cleanup must be in the same code block as the vision_done status
    transition (or right after) so it's not skipped on partial-success
    resumes.
    """
    c6 = cells["ce20f070"]
    assert "_img_clean.pop('top_b64'" in c6 or '_img_clean.pop("top_b64"' in c6, (
        "Step 3 must pop top_b64 from image_urls_json post-vision"
    )
    assert "_img_clean.pop('desc_b64'" in c6 or '_img_clean.pop("desc_b64"' in c6, (
        "Step 3 must pop desc_b64 from image_urls_json post-vision"
    )
    # Cleanup must run AFTER vision_done status is set (not before, so we
    # don't blow away images Vision still needs)
    vd_idx = c6.find("'vision_done'")
    clean_idx = c6.find("_img_clean.pop")
    assert vd_idx != -1 and clean_idx != -1
    assert clean_idx > vd_idx, (
        "Base64 cleanup must run AFTER vision_done status transition"
    )


def test_base64_cleanup_persists_via_db_commit(cells: dict) -> None:
    """The cleanup must include a db.commit() — without commit, the cleaned
    image_urls_json is lost on Colab disconnect."""
    c6 = cells["ce20f070"]
    # Find the cleanup block and confirm commit follows shortly after
    idx = c6.find("_img_clean.pop")
    assert idx != -1
    window = c6[idx:idx + 500]
    assert "db.commit()" in window, (
        "Base64 cleanup block must call db.commit() to persist"
    )


# ============================================================
# Vision prompt caching — system block with cache_control
# ============================================================

def test_vision_system_prompt_defined_in_cell5(cells: dict) -> None:
    """The static Vision schema must live in a VISION_SYSTEM_PROMPT constant
    in Cell 5 (alongside STRATEGY_SYSTEM_PROMPT) so it's reusable + cacheable."""
    c5 = cells["ea617348"]
    assert "VISION_SYSTEM_PROMPT" in c5, (
        "VISION_SYSTEM_PROMPT constant must be defined in Cell 5"
    )
    # The schema must include the key fields the call expects
    assert '"accent":' in c5
    assert '"palette":' in c5
    assert '"packaging_text":' in c5


def test_vision_call_uses_cached_system_block(cells: dict) -> None:
    """Vision messages.create must pass system=[{...,cache_control:ephemeral}]
    pointing at VISION_SYSTEM_PROMPT — otherwise the static schema gets
    re-sent as fresh input on every product (no cache savings)."""
    c6 = cells["ce20f070"]
    pat = re.compile(
        r'max_tokens=2000,\s*timeout=\d+(?:\.\d+)?,\s*\n\s*'
        r'system=\[\{[^\]]*VISION_SYSTEM_PROMPT[^\]]*cache_control[^\]]*ephemeral',
        re.DOTALL,
    )
    matches = pat.findall(c6)
    assert len(matches) >= 2, (
        f"Both Vision call sites must use system=VISION_SYSTEM_PROMPT with "
        f"cache_control:ephemeral; found {len(matches)}"
    )


def test_vision_user_message_no_longer_holds_schema(cells: dict) -> None:
    """The huge inline `vision_prompt = f\"...{safe_title}...\"` block must
    be GONE from Cell 6 — schema moved to system. Only the `Product:
    {safe_title}` line should remain in user content."""
    c6 = cells["ce20f070"]
    assert 'vision_prompt = f"""' not in c6 and \
           "vision_prompt = f'''" not in c6, (
        "Inline vision_prompt f-string must be removed (schema is now in "
        "VISION_SYSTEM_PROMPT, cached via system block)"
    )
    assert 'f"Product: {safe_title}' in c6 or "f'Product: {safe_title}" in c6, (
        "Lean user content with f'Product: {safe_title}' must be present"
    )


# ============================================================
# Playwright browser reuse — saves ~1.5s/scrape × 10K = ~4h
# ============================================================

def test_shared_browser_ctx_helpers_defined(cells: dict) -> None:
    """Cell 2 must define get_shared_browser_ctx() and
    close_shared_browser_ctx() — lazy-init + explicit teardown for the
    module-level Playwright state."""
    c2 = cells["b810afd7"]
    assert "async def get_shared_browser_ctx(" in c2, (
        "get_shared_browser_ctx() helper missing in Cell 2"
    )
    assert "async def close_shared_browser_ctx(" in c2, (
        "close_shared_browser_ctx() helper missing in Cell 2"
    )
    assert "_PW_STATE" in c2, "Module-level _PW_STATE dict missing"


def test_scrape_eprolo_accepts_ctx_arg(cells: dict) -> None:
    """scrape_eprolo must accept optional ctx= so callers can share a
    Playwright context across calls. Default `None` falls back to the
    shared module-level ctx via lazy init."""
    c2 = cells["b810afd7"]
    assert "async def scrape_eprolo(url, ctx=None):" in c2, (
        "scrape_eprolo signature must be `async def scrape_eprolo(url, ctx=None):`"
    )


def test_scrape_eprolo_no_longer_launches_chromium_per_call(cells: dict) -> None:
    """The function must NOT contain `async with async_playwright()` or
    `await p.chromium.launch(` — those would re-spawn Chromium on every
    scrape, defeating the reuse."""
    c2 = cells["b810afd7"]
    # Find the scrape_eprolo function body
    start = c2.find("async def scrape_eprolo(url, ctx=None):")
    assert start != -1
    # Body ends at the next top-level `async def` / `def` / blank-line
    # heuristic — function is ~250 lines so check first 12000 chars
    body = c2[start:start + 12000]
    # Look for the next async def to bound the body
    next_def = body.find("\nasync def ", 50)
    if next_def != -1:
        body = body[:next_def]
    assert "async with async_playwright()" not in body, (
        "scrape_eprolo body still does `async with async_playwright()` — "
        "would re-launch Chromium per call"
    )
    assert "chromium.launch(" not in body, (
        "scrape_eprolo body still calls chromium.launch — must reuse shared ctx"
    )


def test_scrape_eprolo_closes_page_in_finally(cells: dict) -> None:
    """Each call still creates a NEW page on the shared ctx — must close
    that page on every exit path so we don't leak page objects."""
    c2 = cells["b810afd7"]
    start = c2.find("async def scrape_eprolo(url, ctx=None):")
    body = c2[start:start + 12000]
    assert "await page.close()" in body, (
        "scrape_eprolo must close the per-call page in a finally block"
    )


def test_cell6_tears_down_shared_browser_after_loop(cells: dict) -> None:
    """End of Cell 6 must call close_shared_browser_ctx() so Chromium
    is freed before the post-loop work runs (sitemap ping etc.) and so
    re-running Cell 6 picks up a fresh browser."""
    c6 = cells["ce20f070"]
    assert "await close_shared_browser_ctx()" in c6, (
        "Cell 6 must explicitly close the shared browser after the loop"
    )
