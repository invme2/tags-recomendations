# -*- coding: utf-8 -*-
"""COMPAT SHIM. The facet rules now live in taxonomy/facets.json and are executed by
facet_engine.py (taxonomy-driven, word-boundary matching, optional LLM fallback for new
categories). This module preserves the historical gen_facets.derive() API so existing
callers (facet_backfill_full, build_seo_collection_map, catalog_audit) keep working while
reading from the single source of truth.

Original hardcoded rules + the old metafield-writing CLI archived in gen_facets_legacy.py.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import facet_engine as _fe

# Deterministic, keyword-only (no LLM) — identical contract to the old derive(),
# minus latent substring false positives. Now also scans the description (desc) when provided.
def derive(title, ptype, tags, desc=''):
    return _fe.derive_keyword(title, ptype, tags, desc=desc)

# Pass-throughs for callers that want the richer engine.
classify = _fe.classify
to_tags = _fe.to_tags

if __name__ == '__main__':
    import json
    for ti, pt, tg in [("Magnesium Gummies", "supplement", ""),
                       ("Bluetooth Headphones", "Electronics", "")]:
        print(ti, '->', json.dumps(derive(ti, pt, tg), ensure_ascii=False))
