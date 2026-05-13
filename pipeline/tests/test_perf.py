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


# ============================================================
# Per-product concurrency — opt-in via BATCH_CONCURRENCY env var
# ============================================================

def test_cell1_declares_batch_concurrency_env_var(cells: dict) -> None:
    """Cell 1 must expose BATCH_CONCURRENCY via env var (directly or
    through the _safe_env_int helper that survives malformed values)."""
    c1 = cells["477e495d"]
    assert "BATCH_CONCURRENCY" in c1
    assert ("_safe_env_int('BATCH_CONCURRENCY'" in c1
            or "os.environ.get('BATCH_CONCURRENCY'" in c1), (
        "BATCH_CONCURRENCY must be read from env (directly or via _safe_env_int)"
    )


def test_per_product_body_extracted_to_async_function(cells: dict) -> None:
    """The 1400-line per-product body must live inside `async def _process_one(
    pi, prod):` so it can be awaited serially or fed to gather()."""
    c6 = cells["ce20f070"]
    assert "async def _process_one(pi, prod):" in c6, (
        "Per-product loop body must be extracted into _process_one()"
    )


def test_top_level_continues_converted_to_return(cells: dict) -> None:
    """`continue` inside a function body is a SyntaxError. The three top-
    level `continue` statements that used to skip to the next product
    must now be `return`."""
    c6 = cells["ce20f070"]
    # The 'No EPROLO URL' and 'Already in Shopify' branches use return
    assert "error_msg='No EPROLO URL'); return" in c6, (
        "'No EPROLO URL' branch must use `return` (was `continue`)"
    )
    assert "Already in Shopify, skipping.'); return" in c6, (
        "'Already in Shopify' branch must use `return` (was `continue`)"
    )
    assert "f'Scrape failed: {\", \".join(scrape_issues)}')\n                    return" in c6, (
        "Scrape-failure branch must use `return` (was `continue`)"
    )


def test_dispatcher_serial_vs_concurrent_branches_exist(cells: dict) -> None:
    """Cell 6 must dispatch on BATCH_CONCURRENCY — serial for-loop when ==1,
    asyncio.Semaphore + gather when >1."""
    c6 = cells["ce20f070"]
    # Serial branch
    assert "if BATCH_CONCURRENCY <= 1:" in c6
    assert "await _process_one(_pi, _prod)" in c6, (
        "Serial branch must call await _process_one(_pi, _prod)"
    )
    # Concurrent branch
    assert "asyncio.Semaphore(BATCH_CONCURRENCY)" in c6
    assert "asyncio.gather(" in c6


def test_concurrent_branch_uses_per_task_log_buffer(cells: dict) -> None:
    """Under concurrency >1, each task must redirect stdout to its own
    io.StringIO via _TASK_LOG_BUF ContextVar so per-product log blocks
    stay coherent. Single buffer flush at task end."""
    c6 = cells["ce20f070"]
    assert "_TASK_LOG_BUF.set(" in c6, (
        "Concurrent branch must enable per-task buffer via _TASK_LOG_BUF.set"
    )
    assert "_TASK_LOG_BUF.reset(" in c6, (
        "Concurrent branch must reset buffer token after task completes"
    )
    assert "_real_stdout.write(_buf.getvalue())" in c6, (
        "Final flush must write buffered output to real stdout atomically"
    )


def test_concurrency_disables_buffering_after_run(cells: dict) -> None:
    """After gather() completes, the buffering shim must be removed so
    subsequent Cell-6-post-loop prints go straight to stdout."""
    c6 = cells["ce20f070"]
    pat = re.compile(
        r"asyncio\.gather\([^)]*\).*?_disable_task_buffering\(\)",
        re.DOTALL,
    )
    assert pat.search(c6), (
        "Buffering must be disabled in a finally block around gather()"
    )


def test_cell2_provides_buffering_infrastructure(cells: dict) -> None:
    """Cell 2 must expose _TASK_LOG_BUF (ContextVar), _BufferedStdout
    (shim class), _enable_task_buffering / _disable_task_buffering helpers."""
    c2 = cells["b810afd7"]
    assert "_TASK_LOG_BUF" in c2
    assert "ContextVar" in c2
    assert "_BufferedStdout" in c2
    assert "_enable_task_buffering" in c2
    assert "_disable_task_buffering" in c2


def test_buffering_only_redirects_when_in_task_context(cells: dict) -> None:
    """Outside a task (i.e. _TASK_LOG_BUF.get() returns None), writes must
    go to real stdout — otherwise pre-loop / post-loop prints would vanish
    into nowhere."""
    c2 = cells["b810afd7"]
    # The class's write() method must check buf is None and fall back
    pat = re.compile(
        r"def write\(self, s\):.*?buf\s*=\s*_TASK_LOG_BUF\.get\(\).*?"
        r"if buf is None:.*?_real_stdout\.write\(s\)",
        re.DOTALL,
    )
    assert pat.search(c2), (
        "_BufferedStdout.write must fall back to real stdout when no task ctx"
    )


# ============================================================
# AsyncAnthropic — real concurrency (not sync-blocking-in-async)
# ============================================================

def test_async_anthropic_client_declared(cells: dict) -> None:
    """Cell 2 must declare client_async = anthropic.AsyncAnthropic(...).
    Without this, BATCH_CONCURRENCY>1 still serialises AI calls (the
    sync `client.messages.create()` blocks the event loop)."""
    c2 = cells["b810afd7"]
    assert "client_async" in c2
    assert "anthropic.AsyncAnthropic(" in c2, (
        "Must use anthropic.AsyncAnthropic for true async I/O"
    )


def test_loop_uses_await_client_async(cells: dict) -> None:
    """The per-product AI calls (Vision / Strategy / Designer + retries)
    must use `await client_async.messages.create(...)` — not the sync
    `client.messages.create(...)` which blocks the event loop."""
    c6 = cells["ce20f070"]
    # Count async vs sync call sites in Cell 6
    n_async = c6.count("await client_async.messages.create")
    n_sync = c6.count("client.messages.create")
    assert n_async >= 5, (
        f"Expected ≥5 await client_async.messages.create call sites in Cell 6; "
        f"got {n_async}"
    )
    assert n_sync == 0, (
        f"Cell 6 must NOT call sync client.messages.create (would block "
        f"event loop under concurrency). Found {n_sync} sync call(s)."
    )


def test_sync_client_still_used_in_sync_contexts(cells: dict) -> None:
    """Sync `client` must remain for the smoke-tests in Cell 2 and the
    sync helpers `_call_claude` / `generate_collection_html` — those run
    in non-async contexts and can't `await`."""
    c2 = cells["b810afd7"]
    # Both clients must exist at module level
    assert "client = anthropic.Anthropic(" in c2
    # generate_collection_html uses sync client (it's not async)
    assert "client.messages.create" in c2


# ============================================================
# Sanitization for EPROLO scraped data → prompts
# ============================================================

def test_sanitize_helper_declared(cells: dict) -> None:
    """A _sanitize_for_prompt() helper must exist — used to scrub EPROLO
    scrape data (title / description / specs) before feeding into prompts,
    defending against prompt-injection payloads in product titles."""
    c2 = cells["b810afd7"]
    assert "def _sanitize_for_prompt(" in c2
    # Must strip control chars + length cap
    assert "max_len" in c2
    # Zero-width chars are a common injection vector
    assert "200B" in c2 or "200b" in c2 or "zero-width" in c2.lower()


def test_vision_title_runs_through_sanitizer(cells: dict) -> None:
    """The product title fed to Vision must pass through _sanitize_for_prompt
    — otherwise a malicious title can leak into the cached system prompt."""
    c6 = cells["ce20f070"]
    assert "safe_title = _sanitize_for_prompt(" in c6, (
        "Vision user content must build safe_title via _sanitize_for_prompt"
    )


# ============================================================
# Safe env-var helpers — malformed values don't crash batch
# ============================================================

def test_safe_env_helpers_defined(cells: dict) -> None:
    """Cell 1 must define _safe_env_float / _safe_env_int — wrappers that
    fall back to default on ValueError so a typo'd Colab Secret can't
    crash the entire batch."""
    c1 = cells["477e495d"]
    assert "def _safe_env_float(" in c1
    assert "def _safe_env_int(" in c1


def test_safe_env_helpers_catch_valueerror(cells: dict) -> None:
    """The helper must catch ValueError / TypeError and print a warning."""
    c1 = cells["477e495d"]
    # ValueError / TypeError handling
    assert "ValueError" in c1
    assert "is not" in c1, "Warning message must explain why fallback fires"


def test_retail_markup_uses_safe_helper(cells: dict) -> None:
    """RETAIL_MARKUP / COMPARE_AT_MARKUP / BATCH_CONCURRENCY must all
    flow through the safe wrappers."""
    c1 = cells["477e495d"]
    assert "_safe_env_float('RETAIL_MARKUP'" in c1
    assert "_safe_env_float('COMPARE_AT_MARKUP'" in c1
    assert "_safe_env_int('BATCH_CONCURRENCY'" in c1


# ============================================================
# Anthropic spend cap + cache-hit verification
# ============================================================

def test_max_anthropic_budget_env_var(cells: dict) -> None:
    """Cell 1 must declare MAX_ANTHROPIC_BUDGET via _safe_env_float
    so runaway spend (typo'd CSV size, retry storm) is bounded."""
    c1 = cells["477e495d"]
    assert "MAX_ANTHROPIC_BUDGET" in c1
    assert "_safe_env_float('MAX_ANTHROPIC_BUDGET'" in c1


def test_cost_tracker_declared(cells: dict) -> None:
    """Cell 2 must declare _anthropic_cost_tracker dict + helpers
    _track_anthropic_response + _check_anthropic_budget."""
    c2 = cells["b810afd7"]
    assert "_anthropic_cost_tracker" in c2
    assert "def _track_anthropic_response(" in c2
    assert "def _check_anthropic_budget(" in c2
    # Sentinel exception for the budget breach path
    assert "_AnthropicBudgetExceeded" in c2


def test_cost_tracker_records_cache_tokens(cells: dict) -> None:
    """The tracker must capture cache_read_input_tokens AND
    cache_creation_input_tokens AND fresh input_tokens — three buckets
    are needed to compute the cache hit ratio."""
    c2 = cells["b810afd7"]
    assert "cache_read_input_tokens" in c2
    assert "cache_creation_input_tokens" in c2
    assert "'fresh_in'" in c2


def test_every_ai_call_tracked(cells: dict) -> None:
    """Each messages.create call site in Cell 6 must follow with a
    _track_anthropic_response() call so the tracker stays in sync."""
    c6 = cells["ce20f070"]
    # The 5 call sites: vision (1 inside if-else, both paths same r1), strategy, designer primary, designer retry
    # _track is called per (response, cost) tuple
    n_track = c6.count("_track_anthropic_response(")
    assert n_track >= 4, (
        f"Expected ≥4 _track_anthropic_response() invocations; got {n_track}"
    )


def test_budget_checked_before_expensive_ai_calls(cells: dict) -> None:
    """Each of the 3 main AI steps (Vision / Strategy / Designer) must
    call _check_anthropic_budget() so the breach raises BEFORE the
    expensive request fires."""
    c6 = cells["ce20f070"]
    # Find the budget check inside each step
    n_check = c6.count("_check_anthropic_budget()")
    assert n_check >= 3, (
        f"Expected ≥3 budget-check call sites (Vision / Strategy / Designer); "
        f"got {n_check}"
    )


def test_end_of_batch_summary_prints_cache_ratio(cells: dict) -> None:
    """The end-of-batch summary must print the cache hit ratio so we can
    verify prompt caching is actually working (silent breakage of
    cache_control would otherwise cost ~10× more)."""
    c6 = cells["ce20f070"]
    assert "cache hit" in c6.lower(), (
        "End-of-batch summary must print cache hit ratio"
    )
    assert "_anthropic_cost_tracker" in c6
    # Warning when cache ratio is suspiciously low
    assert "verify cache_control" in c6 or "cache hit ratio low" in c6


# ============================================================
# Tier 3 hygiene — module-level constants + silent-truncation warnings
# ============================================================

def test_funnel_order_is_module_level(cells: dict) -> None:
    """_PHOTO_FUNNEL_ORDER + _PHOTO_FUNNEL_IDX must live in Cell 2 (module
    level) so they aren't rebuilt every per-product loop iteration and
    tests can reason about them independently of Cell 6."""
    c2 = cells["b810afd7"]
    assert "_PHOTO_FUNNEL_ORDER" in c2
    assert "_PHOTO_FUNNEL_IDX" in c2


def test_funnel_order_not_redefined_in_cell6(cells: dict) -> None:
    """Local `_FUNNEL_ORDER = [...]` inside the loop body must be GONE —
    Cell 6 reads the module-level constant instead."""
    c6 = cells["ce20f070"]
    assert "_FUNNEL_ORDER = [" not in c6, (
        "Local funnel-order definition must be removed; use module-level "
        "_PHOTO_FUNNEL_ORDER from Cell 2"
    )


def test_photo_pack_skipped_is_module_level(cells: dict) -> None:
    """_PhotoPackSkipped class must be defined ONCE at module level
    (Cell 2), not re-created per iteration. Identity stability also
    matters for any external `isinstance` checks."""
    c2 = cells["b810afd7"]
    assert "class _PhotoPackSkipped(Exception):" in c2, (
        "Cell 2 must declare module-level _PhotoPackSkipped"
    )
    c6 = cells["ce20f070"]
    # Cell 6 must NOT redefine it inside the loop
    assert "class _PhotoPackSkipped" not in c6, (
        "Local class _PhotoPackSkipped definition must be removed from Cell 6"
    )


def test_eprolo_photos_truncation_warned(cells: dict) -> None:
    """When EPROLO returns more than 14 photos, Designer only sees the
    first 14 (token-budget cap). Operator must see a warning so they
    know photos 15+ are silently dropped for source_index selection."""
    c6 = cells["ce20f070"]
    assert "len(_all_eprolo_d) > 14" in c6, (
        "Cell 6 must check for >14 EPROLO photos"
    )
    assert "Designer sees first 14" in c6 or "Photos 15-" in c6, (
        "Must print explicit warning when EPROLO cap is hit"
    )


def test_source_image_urls_truncation_warned(cells: dict) -> None:
    """custom.source caps top/desc image_urls at 50. EPROLO occasionally
    returns 60-80 desc URLs — operator must see truncation."""
    c6 = cells["ce20f070"]
    # Either a clear print message or a count comparison
    assert ("truncated" in c6 and "image_urls" in c6) or \
           "custom.source image_urls truncated" in c6, (
        "Must warn when image_urls > 50 cap is hit"
    )
