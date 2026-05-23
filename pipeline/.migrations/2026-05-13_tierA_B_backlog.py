"""One-shot: 9 fixes from session backlog audit.
  #1 Designer prompt: forbid shipping/returns/refund/delivery mentions
  #2 Designer prompt: compare module hallucination rule
  #3 body_html sanitize raw EPROLO description fallback
  #6 Image dedup in scrape_eprolo
  #7 MAX_DATAFORSEO_BUDGET env-configurable
  #8 Carousel reorder by Vision role before shopify_attach_media
  #10 Real-time cost checkpoint every 25 products
  #14 Designer prompt: explicit spec source-tracing rule
"""
from __future__ import annotations
from pathlib import Path
import nbformat

NB = Path("/home/user/tags-recomendations/pipeline/Shopify_Pipeline.ipynb")

# ============================================================
# Cell 1 — make TOTAL_BUDGET env-configurable (MAX_DATAFORSEO_BUDGET)
# ============================================================
CELL1_BUDGET_ANCHOR = '''MAX_ANTHROPIC_BUDGET = _safe_env_float('MAX_ANTHROPIC_BUDGET', 1000.0)'''

CELL1_BUDGET_NEW = '''MAX_ANTHROPIC_BUDGET = _safe_env_float('MAX_ANTHROPIC_BUDGET', 1000.0)
# DataForSEO spend cap — was previously hardcoded TOTAL_BUDGET = 15.00 at
# the top of Cell 1 (still set for backwards-compat). Now env-tunable via
# MAX_DATAFORSEO_BUDGET. CostTracker reads TOTAL_BUDGET below, so we
# reassign here to pick up env override before tracker is created.
TOTAL_BUDGET = _safe_env_float('MAX_DATAFORSEO_BUDGET', TOTAL_BUDGET)'''

# ============================================================
# Cell 2 — scrape_eprolo: dedup image URL lists before return
# ============================================================
CELL2_DEDUP_ANCHOR = '''        result["top_image_urls"] = top
        result["desc_image_urls"] = desc'''

CELL2_DEDUP_NEW = '''        # Dedup — EPROLO occasionally returns the same photo URL 2-3 times.
        # Otherwise carousel + photo_pack ZIP would contain duplicates.
        # dict.fromkeys preserves insertion order, drops duplicates.
        result["top_image_urls"]  = list(dict.fromkeys(top))
        result["desc_image_urls"] = list(dict.fromkeys(desc))'''

# ============================================================
# Cell 6 — Designer system prompt: rules block
# ============================================================
DESIGNER_RULES_ANCHOR = '''                "RULE: never fabricate certs/specs/ingredients. Pull only what VISION ANALYSIS confirmed (packaging text,\\n"
                "claims, ingredients_visible, certifications fields). If vision found nothing — skip the module.\\n\\n"'''

DESIGNER_RULES_NEW = '''                "RULE: never fabricate certs/specs/ingredients. Pull only what VISION ANALYSIS confirmed (packaging text,\\n"
                "claims, ingredients_visible, certifications fields). If vision found nothing — skip the module.\\n\\n"
                "RULE (SHIPPING / RETURNS / REFUND): NEVER mention shipping cost, delivery times, return policy,\\n"
                "refund terms, 'secure checkout', money-back guarantees, or warranty terms anywhere — not in FAQ,\\n"
                "not in features, not in trust, not in hero/lead, not in CTA copy. These concerns are handled by a\\n"
                "separate Shopify checkout-page module. Mentioning them on the PDP creates contradictions with the\\n"
                "actual stored policy and kills buyer trust on inspection.\\n\\n"
                "RULE (COMPARE MODULE — anti-hallucination): The compare matrix is high-risk because Designer has\\n"
                "no source-of-truth for competitor numbers. For row values, prefer Yes/No/Partial cells over\\n"
                "specific numbers (battery hours, dB, prices, weights). If you must include a number for the OWN\\n"
                "column, ONLY use values that appeared verbatim in VISION ANALYSIS or scrape facts. For competitor\\n"
                "columns, NEVER invent specific numbers — leave as Yes/No or omit the row. A buyer who fact-checks\\n"
                "an invented 'Handheld fan: 40-50dB' competitor stat finds nothing and trust collapses. Better to\\n"
                "skip the compare module entirely than to fill it with plausible-sounding fakes.\\n\\n"
                "RULE (SPEC SOURCE-TRACING): Every spec row value must be traceable to a specific evidence source.\\n"
                "Allowed sources, in order of priority: (1) scrape specs/variants dict, (2) VISION packaging_text\\n"
                "claims/ingredients/instructions, (3) VISION physical key_features. If a candidate value isn't in\\n"
                "any of those, OMIT THE ROW. Prefer a 4-row honest specs table over a 12-row half-invented one.\\n\\n"'''

# ============================================================
# Cell 6 — body_html sanitize fallback
# ============================================================
BODY_HTML_ANCHOR = '''            short_desc = meta.get('short_description', product.get('description','')[:200])'''

BODY_HTML_NEW = '''            # Sanitize: when Designer's meta.short_description is empty we fall back
            # to the raw EPROLO description, which can contain <img>, <a>, embedded
            # styling, EPROLO URLs, etc. Stripping tags + collapsing whitespace
            # keeps the body_html clean and prevents EPROLO links leaking onto
            # storefront markup.
            _raw_short = meta.get('short_description') or (product.get('description') or '')
            short_desc = re.sub(r'<[^>]+>', '', _raw_short)
            short_desc = re.sub(r'\\s+', ' ', short_desc).strip()[:200]'''

# ============================================================
# Cell 6 Step 5 — sort gallery by Vision role before shopify_attach_media
# ============================================================
GALLERY_SORT_ANCHOR = '''                gallery = [img['url'] for img in img_data.get('top',[]) if img.get('url','').startswith('http')]'''

GALLERY_SORT_NEW = '''                # Sort gallery by Vision-assigned role so 'hero' goes first in
                # Shopify carousel — provides editorial first-impression even
                # before operator runs the photo_pack edit workflow. Order:
                # hero → lifestyle → in_use → detail → packaging → other.
                _ROLE_PRIORITY = {'hero':0, 'lifestyle':1, 'in_use':2, 'feature':3,
                                  'detail':4, 'ingredient':5, 'packaging':6, 'before_after':7}
                _role_by_index = {ii.get('index'): (ii.get('role','') or 'other')
                                  for ii in stage1.get('images', [])}
                _gallery_raw = [img for img in img_data.get('top',[]) if img.get('url','').startswith('http')]
                _gallery_raw.sort(key=lambda im: _ROLE_PRIORITY.get(
                    _role_by_index.get(im.get('index'), 'other'), 99))
                gallery = [img['url'] for img in _gallery_raw]'''

# ============================================================
# Cell 6 — real-time cost checkpoint every 25 products
# ============================================================
CHECKPOINT_ANCHOR = '''for pi, prod in enumerate(pending):'''

# Old: just a bare for. Wait — we have async _process_one structure now.
# Let me find the right spot in the dispatcher.
# Actually the simplest: print checkpoint inside the serial loop AND
# inside the slot wrapper. But the slot wrapper is async — checkpoint
# under concurrency would print mid-task, OK.
# Better: print checkpoint AFTER each product completes regardless of
# concurrency. The simplest hook is right at end of _process_one before
# function exits — but that's invasive.
# Cleanest: print every 25 finished products in the dispatcher.
DISPATCHER_ANCHOR = '''if BATCH_CONCURRENCY <= 1:
    # Serial path — preserves natural log streaming, zero overhead.
    for _pi, _prod in enumerate(pending):
        await _process_one(_pi, _prod)'''

DISPATCHER_NEW = '''def _print_cost_checkpoint(idx, total_n):
    """Periodic cost checkpoint so 10K-batch operators see spend live,
    not only at end-of-batch. Triggers every 25 finished products."""
    if (idx + 1) % 25 == 0 or (idx + 1) == total_n:
        _spent = _anthropic_cost_tracker['spent_usd']
        _proj  = (_spent / (idx + 1)) * total_n if (idx + 1) > 0 else 0
        print(f'\\n  ── Checkpoint [{idx+1}/{total_n}] ── '
              f'${_spent:.2f} spent · ${_proj:.2f} projected · '
              f'{_anthropic_cost_tracker["calls"]} AI calls ──')

if BATCH_CONCURRENCY <= 1:
    # Serial path — preserves natural log streaming, zero overhead.
    for _pi, _prod in enumerate(pending):
        await _process_one(_pi, _prod)
        _print_cost_checkpoint(_pi, len(pending))'''

# Same for concurrent path:
DISPATCHER_CONC_ANCHOR = '''    try:
        await asyncio.gather(*[_slot(_pi, _p) for _pi, _p in enumerate(pending)])
    finally:
        _disable_task_buffering()'''

DISPATCHER_CONC_NEW = '''    # Wrap _slot to print checkpoint after each finishes (still under sem).
    _finished_count = {'n': 0}
    async def _slot_with_checkpoint(_pi, _prod):
        await _slot(_pi, _prod)
        _finished_count['n'] += 1
        _print_cost_checkpoint(_finished_count['n'] - 1, len(pending))
    try:
        await asyncio.gather(*[_slot_with_checkpoint(_pi, _p) for _pi, _p in enumerate(pending)])
    finally:
        _disable_task_buffering()'''


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cells = {c.get("id"): c for c in nb.cells if c.cell_type == "code"}

    c1 = cells.get("477e495d")
    if CELL1_BUDGET_ANCHOR not in c1["source"]:
        print("ERR Cell 1 budget anchor"); return 1
    c1["source"] = c1["source"].replace(CELL1_BUDGET_ANCHOR, CELL1_BUDGET_NEW, 1)

    c2 = cells.get("b810afd7")
    if CELL2_DEDUP_ANCHOR not in c2["source"]:
        print("ERR Cell 2 dedup anchor"); return 2
    c2["source"] = c2["source"].replace(CELL2_DEDUP_ANCHOR, CELL2_DEDUP_NEW, 1)

    c6 = cells.get("ce20f070")
    for label, old, new in [
        ("designer rules", DESIGNER_RULES_ANCHOR, DESIGNER_RULES_NEW),
        ("body_html sanitize", BODY_HTML_ANCHOR, BODY_HTML_NEW),
        ("gallery role sort", GALLERY_SORT_ANCHOR, GALLERY_SORT_NEW),
        ("dispatcher serial", DISPATCHER_ANCHOR, DISPATCHER_NEW),
        ("dispatcher concurrent", DISPATCHER_CONC_ANCHOR, DISPATCHER_CONC_NEW),
    ]:
        if old not in c6["source"]:
            print(f"ERR Cell 6 {label} anchor missing")
            return 3
        c6["source"] = c6["source"].replace(old, new, 1)

    nbformat.write(nb, NB)
    print("✅ 7 notebook edits applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
