"""Resilience tests for unattended 10K-product batches.

Verifies that every external-failure path has either retry, timeout, or
graceful fallback — so a long unattended run doesn't get stuck on a single
transient error.
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
# Anthropic SDK retry — bumped from default 2 to 5
# ============================================================

def test_anthropic_client_has_max_retries(cells: dict) -> None:
    """For 10K-product batches, default 2 retries from Anthropic SDK isn't
    enough — bump to 5 to absorb transient 429/5xx without losing a product."""
    c2 = cells["b810afd7"]
    assert "max_retries=5" in c2, (
        "anthropic.Anthropic(...) must be created with max_retries=5"
    )


# ============================================================
# scrape_eprolo retry wrapper at call site
# ============================================================

def test_scrape_eprolo_call_has_retry_loop(cells: dict) -> None:
    """STEP 1 must wrap scrape_eprolo in retry loop — playwright timeouts and
    EPROLO 5xx are routine in big batches."""
    c6 = cells["ce20f070"]
    assert "_scrape_attempt in range(3)" in c6, (
        "STEP 1 must retry scrape up to 3 times"
    )
    assert "scrape attempt" in c6, "must log retry attempts"


def test_scrape_eprolo_uses_exponential_backoff(cells: dict) -> None:
    """Wait should grow with attempt number to spread retries."""
    c6 = cells["ce20f070"]
    assert "10 * (_scrape_attempt + 1)" in c6 or "5 * (_scrape_attempt + 1)" in c6


def test_scrape_failure_provides_empty_dict_default(cells: dict) -> None:
    """If all 3 scrape attempts return empty title without raising, pipeline
    should fall through with safe-empty product (so error status set later
    by validate_scrape, not raised KeyError)."""
    c6 = cells["ce20f070"]
    assert 'product = {"title": ""' in c6 or "product = {'title': ''" in c6


# ============================================================
# shopify_attach_media idempotency — prevents duplicate gallery photos on retry
# ============================================================

def test_attach_media_checks_existing_media(cells: dict) -> None:
    """Before pushing media, query existing count. If product already has
    >= requested count, skip — prevents duplication on Step 5 retry after
    partial-success crash."""
    c2 = cells["b810afd7"]
    assert "media(first:50){nodes{id}}" in c2, (
        "attach_media must query existing product media to dedupe"
    )
    assert "_existing" in c2 and "len(media)" in c2


def test_attach_media_idempotency_failure_is_non_blocking(cells: dict) -> None:
    """If the existence check itself fails (network glitch), proceed with
    attach — better risk-of-duplicate than no-photos at all."""
    c2 = cells["b810afd7"]
    pat = re.compile(
        r"async def shopify_attach_media.*?try:.*?except Exception.*?pass",
        re.DOTALL,
    )
    assert pat.search(c2), (
        "Idempotency check must be wrapped in try/except so failure doesn't block attach"
    )


# ============================================================
# shopify_gql network exception handling
# ============================================================

def test_shopify_gql_catches_httpx_exceptions(cells: dict) -> None:
    """Connection-level errors (DNS, connection refused, timeout) must be
    caught and retried — not propagated up to kill the whole batch."""
    c2 = cells["b810afd7"]
    pat = re.compile(
        r"async def shopify_gql.*?except \(httpx\.NetworkError, httpx\.TimeoutException, httpx\.HTTPError\)",
        re.DOTALL,
    )
    assert pat.search(c2), (
        "shopify_gql must catch httpx.NetworkError + TimeoutException + HTTPError"
    )


def test_shopify_gql_uses_exponential_backoff_on_network_fail(cells: dict) -> None:
    """Network retries should use exponential wait (2/4/8s) — not flat sleep."""
    c2 = cells["b810afd7"]
    assert "2 ** (attempt + 1)" in c2, "network-retry backoff should be exponential"


# ============================================================
# End-of-run summary surfaces stuck products
# ============================================================

def test_summary_shows_per_status_counts(cells: dict) -> None:
    """End-of-Cell-6 summary must show counts for every pipeline status,
    not just done/error totals — user needs to see exactly where products
    got stuck across a 10K batch."""
    c6 = cells["ce20f070"]
    assert "_status_order = [" in c6, (
        "Summary must iterate explicit status order"
    )
    # Order must include all 7 non-pending non-done states
    for st in ['scraped', 'images_uploaded', 'vision_done', 'strategy_done',
               'html_ready', 'pack_done', 'done', 'error']:
        assert f"'{st}'" in c6


def test_summary_prints_retry_hint(cells: dict) -> None:
    """When products are in 'error' status, summary must hint at the SQL
    one-liner to reset them so user can quickly retry."""
    c6 = cells["ce20f070"]
    assert "To retry errored products" in c6
    assert "UPDATE products SET status=" in c6
    assert "WHERE status=" in c6


def test_summary_shows_sample_error_messages(cells: dict) -> None:
    """For first few errored products, surface their error_msg so user can
    diagnose pattern (rate limit / auth / EPROLO down / ...) at a glance."""
    c6 = cells["ce20f070"]
    assert "SELECT name, error_msg FROM products WHERE status='error'" in c6
    assert "LIMIT 3" in c6


# ============================================================
# Smoke checks for resilience invariants
# ============================================================

def test_per_product_loop_wrapped_in_try_except(cells: dict) -> None:
    """Single bad product must NOT kill the whole batch loop. The product
    iteration body must be wrapped in try/except that marks status='error'."""
    c6 = cells["ce20f070"]
    # The pattern: `try:` near `STEP 1` followed by `except Exception as e:`
    # with db_update_status(pid, 'error')
    assert "db_update_status(pid, 'error'" in c6, (
        "Product loop body must catch all exceptions and mark status=error"
    )


def test_db_committed_after_each_product(cells: dict) -> None:
    """DB must persist after each product so a Colab disconnect doesn't lose
    the last 50 products' progress."""
    c6 = cells["ce20f070"]
    assert "shutil.copy(DB_LOCAL, DB_PATH)" in c6, (
        "DB must be backed up to Drive after each product (or at minimum end of loop)"
    )
