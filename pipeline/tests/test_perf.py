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
