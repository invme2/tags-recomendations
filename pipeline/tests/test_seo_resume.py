"""Guards the Cell-6 SEO resume/checkpoint layer (patch_seo_resume.py).

Goal: the keyword-research stage must never re-burn API on restart and must
resume from the exact place it stopped. These tests assert the checkpoint
machinery stays wired into the SEO cell.
"""
from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

NOTEBOOK_PATH = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
SEO_CELL_ID = "f6ecfe8b"


@pytest.fixture(scope="module")
def cells() -> dict:
    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    return {c.get("id"): c["source"] for c in nb.cells if c.cell_type == "code"}


def test_seo_checkpoint_helpers_present(cells: dict) -> None:
    c = cells[SEO_CELL_ID]
    for token in ("_seo_ckey", "_seo_cache_get", "_seo_cache_put",
                  "_seo_persist_spend", "seo_kw_cache", "dfs_spent"):
        assert token in c, f"SEO resume layer missing '{token}'"


def test_seo_spend_is_restored_on_restart(cells: dict) -> None:
    """cost_tracker.spent must be reloaded from persisted dfs_spent so the
    DataForSEO budget cap is cumulative across restarts (no re-spend up to $15)."""
    c = cells[SEO_CELL_ID]
    assert "cost_tracker.spent = float(" in c, (
        "prior DataForSEO spend must be restored into cost_tracker on resume"
    )


def test_every_api_call_site_is_cache_guarded(cells: dict) -> None:
    """Every keyword API call site (2 Claude + 4 DataForSEO) must check the
    cache before spending. A bare api call with no _seo_cache_get nearby would
    re-burn on restart."""
    c = cells[SEO_CELL_ID]
    # 2 Claude (cat1, seed1) + 4 DataForSEO (kfk, ideas, bulk_kd, expansion)
    assert c.count("_seo_cache_get(") >= 6, (
        f"expected >= 6 cache-guarded call sites, found {c.count('_seo_cache_get(')}"
    )
    # Each successful fetch persists to cache.
    assert c.count("_seo_cache_put(") >= 6, (
        f"expected >= 6 cache writes, found {c.count('_seo_cache_put(')}"
    )


def test_dataforseo_charges_persist_spend(cells: dict) -> None:
    """Each DataForSEO charge must be followed by a spend persist so a crash
    right after a paid batch doesn't lose the budget accounting."""
    c = cells[SEO_CELL_ID]
    # 4 DataForSEO endpoints each persist spend after charging.
    assert c.count("_seo_persist_spend()") >= 4, (
        f"expected >= 4 spend-persist calls, found {c.count('_seo_persist_spend()')}"
    )
