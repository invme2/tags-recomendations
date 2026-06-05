#!/usr/bin/env python3
"""patch_seo_resume.py — full RESUME CHECKPOINT layer for Cell 6 (SEO stage).

Goal (operator): never re-burn API on ANY stage; if the process stops, resume
from the exact same place.

Cell 6 was all-or-nothing: Stage-1 Claude categorization + all DataForSEO calls
accumulated in memory, written to DB only at the very end (+ seo_complete flag).
A crash mid-stage lost every spent call, and cost_tracker.spent reset to 0 each
run (so a restart could spend up to $15 AGAIN).

Fix — one uniform content-keyed cache around EVERY API call site:
  - seo_kw_cache(ckey, payload): each batch result persisted to DB immediately.
  - On restart a batch whose ckey is cached is REUSED (no API call, no charge).
  - dfs_spent persisted in seo_state -> cost_tracker.spent restored -> the $15
    cap becomes cumulative across restarts.
  - can_afford() moved INSIDE the cache-miss branch so cached batches always
    proceed even if the budget is already near the cap.
  - bulk_keyword_difficulty gains a can_afford guard it previously lacked.

Keyed by stable content hash (sorted seeds), NOT batch position -> seeds can't
drift and indices don't matter. No re-indentation of existing loop bodies beyond
the wrapped call blocks. nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 6

HELPER = '''    print("SEO: RUNNING...")

    # ─── RESUME CHECKPOINT LAYER (don't re-burn API on restart) ───
    import hashlib as _hl
    db.execute("CREATE TABLE IF NOT EXISTS seo_state (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS seo_kw_cache (ckey TEXT PRIMARY KEY, payload TEXT)")
    db.commit()
    def _seo_ckey(ep, items):
        _h = _hl.sha1((str(ep) + '|' + '|'.join(sorted(map(str, items)))).encode('utf-8')).hexdigest()
        return str(ep) + ':' + _h
    def _seo_cache_get(k):
        _row = db.execute("SELECT payload FROM seo_kw_cache WHERE ckey=?", (k,)).fetchone()
        return json.loads(_row[0]) if _row else None
    def _seo_cache_put(k, payload):
        db.execute("INSERT OR REPLACE INTO seo_kw_cache (ckey,payload) VALUES (?,?)", (k, json.dumps(payload)))
        db.commit()
    def _seo_persist_spend():
        try:
            db.execute("INSERT OR REPLACE INTO seo_state (key,value) VALUES ('dfs_spent',?)", (str(cost_tracker.spent),))
            db.commit()
        except Exception:
            pass
    try:
        _dfs_prev = db.execute("SELECT value FROM seo_state WHERE key='dfs_spent'").fetchone()
        if _dfs_prev:
            cost_tracker.spent = float(_dfs_prev[0])
            print(f"  [resume] DataForSEO prior spend restored: ${cost_tracker.spent:.2f}")
    except Exception:
        pass
    _seo_cache_n = db.execute("SELECT COUNT(*) FROM seo_kw_cache").fetchone()[0]
    if _seo_cache_n:
        print(f"  [resume] {_seo_cache_n} cached API batches will be reused (no re-charge)")'''

EDITS = [
    # 0) helper injection
    ('    print("SEO: RUNNING...")', HELPER),

    # 1) Stage-1 categorize (Claude)
    ("        result=call_claude(prompt,0.3)",
     "        _ckc = _seo_ckey('cat1', batch)\n"
     "        result = _seo_cache_get(_ckc)\n"
     "        if result is None:\n"
     "            result=call_claude(prompt,0.3)\n"
     "            if result: _seo_cache_put(_ckc, result)"),

    # 2) Seed-gen (Claude)
    ("        result = call_claude(prompt, 0.5)",
     "        _cks = _seo_ckey('seed1', batch)\n"
     "        result = _seo_cache_get(_cks)\n"
     "        if result is None:\n"
     "            result = call_claude(prompt, 0.5)\n"
     "            if result: _seo_cache_put(_cks, result)"),

    # 3) Part A — keywords_for_keywords
    ("""        if not cost_tracker.can_afford('keywords_for_keywords'):
            print('Budget limit!'); break
        try:
            r = api_post_with_retry(
                'https://api.dataforseo.com/v3/keywords_data/google_ads/keywords_for_keywords/live',
                [{'keywords': batch, 'location_code': LOCATION_CODE,
                  'language_code': LANGUAGE_CODE, 'sort_by': 'search_volume',
                  'include_adult_keywords': False}])
            if r is None: continue
            cost_tracker.charge('keywords_for_keywords', str(len(batch))+' seeds')
            data = r.json()""",
     """        try:
            _cka = _seo_ckey('keywords_for_keywords', batch)
            data = _seo_cache_get(_cka)
            if data is None:
                if not cost_tracker.can_afford('keywords_for_keywords'):
                    print('Budget limit!'); break
                r = api_post_with_retry(
                    'https://api.dataforseo.com/v3/keywords_data/google_ads/keywords_for_keywords/live',
                    [{'keywords': batch, 'location_code': LOCATION_CODE,
                      'language_code': LANGUAGE_CODE, 'sort_by': 'search_volume',
                      'include_adult_keywords': False}])
                if r is None: continue
                cost_tracker.charge('keywords_for_keywords', str(len(batch))+' seeds')
                data = r.json()
                _seo_cache_put(_cka, data); _seo_persist_spend()"""),

    # 4) Part B — keyword_ideas
    ("""        if not cost_tracker.can_afford('keyword_ideas'):
            print('Budget limit!'); break
        try:
            r = api_post_with_retry(
                'https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_ideas/live',
                [{'keywords': batch, 'location_code': LOCATION_CODE,
                  'language_code': LANGUAGE_CODE, 'include_serp_info': False,
                  'limit': 700, 'filters': [['keyword_info.search_volume', '>', MIN_VOLUME - 1]],
                  'order_by': ['keyword_info.search_volume,desc']}])
            if r is None: continue
            cost_tracker.charge('keyword_ideas', str(len(batch))+' seeds')
            data = r.json()""",
     """        try:
            _ckb = _seo_ckey('keyword_ideas', batch)
            data = _seo_cache_get(_ckb)
            if data is None:
                if not cost_tracker.can_afford('keyword_ideas'):
                    print('Budget limit!'); break
                r = api_post_with_retry(
                    'https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_ideas/live',
                    [{'keywords': batch, 'location_code': LOCATION_CODE,
                      'language_code': LANGUAGE_CODE, 'include_serp_info': False,
                      'limit': 700, 'filters': [['keyword_info.search_volume', '>', MIN_VOLUME - 1]],
                      'order_by': ['keyword_info.search_volume,desc']}])
                if r is None: continue
                cost_tracker.charge('keyword_ideas', str(len(batch))+' seeds')
                data = r.json()
                _seo_cache_put(_ckb, data); _seo_persist_spend()"""),

    # 5) bulk_keyword_difficulty (adds a can_afford guard it lacked)
    ("""                r = api_post_with_retry('https://api.dataforseo.com/v3/dataforseo_labs/google/bulk_keyword_difficulty/live',
                    [{'keywords': chunk, 'location_code': LOCATION_CODE, 'language_code': LANGUAGE_CODE}])
                if r is None: continue
                cost_tracker.charge('bulk_keyword_difficulty', str(len(chunk))+' kws')
                data = r.json()""",
     """                _ckk = _seo_ckey('bulk_keyword_difficulty', chunk)
                data = _seo_cache_get(_ckk)
                if data is None:
                    if not cost_tracker.can_afford('bulk_keyword_difficulty'):
                        break
                    r = api_post_with_retry('https://api.dataforseo.com/v3/dataforseo_labs/google/bulk_keyword_difficulty/live',
                        [{'keywords': chunk, 'location_code': LOCATION_CODE, 'language_code': LANGUAGE_CODE}])
                    if r is None: continue
                    cost_tracker.charge('bulk_keyword_difficulty', str(len(chunk))+' kws')
                    data = r.json()
                    _seo_cache_put(_ckk, data); _seo_persist_spend()"""),

    # 6) expansion — keyword_suggestions / related_keywords
    ("""                if not cost_tracker.can_afford(ep): break
                try:
                    fp = 'keyword_info' if ep == 'keyword_suggestions' else 'keyword_data.keyword_info'
                    r = api_post_with_retry('https://api.dataforseo.com/v3/dataforseo_labs/google/'+ep+'/live',
                        [{'keyword': seed, 'location_code': LOCATION_CODE, 'language_code': LANGUAGE_CODE,
                        'include_seed_keyword': True, 'limit': 80,
                        'filters': [[fp+'.search_volume', '>', MIN_VOLUME-1]],
                        'order_by': [fp+'.search_volume,desc']}], timeout=60)
                    if r is None: continue
                    cost_tracker.charge(ep, seed)
                    data = r.json()""",
     """                try:
                    fp = 'keyword_info' if ep == 'keyword_suggestions' else 'keyword_data.keyword_info'
                    _cke = _seo_ckey(ep, [seed])
                    data = _seo_cache_get(_cke)
                    if data is None:
                        if not cost_tracker.can_afford(ep): break
                        r = api_post_with_retry('https://api.dataforseo.com/v3/dataforseo_labs/google/'+ep+'/live',
                            [{'keyword': seed, 'location_code': LOCATION_CODE, 'language_code': LANGUAGE_CODE,
                            'include_seed_keyword': True, 'limit': 80,
                            'filters': [[fp+'.search_volume', '>', MIN_VOLUME-1]],
                            'order_by': [fp+'.search_volume,desc']}], timeout=60)
                        if r is None: continue
                        cost_tracker.charge(ep, seed)
                        data = r.json()
                        _seo_cache_put(_cke, data); _seo_persist_spend()"""),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    src = cell.source
    for idx, (old, new) in enumerate(EDITS):
        n = src.count(old)
        if n != 1:
            print(f"FAIL edit #{idx}: expected 1 match, found {n}")
            print(f"  old starts: {old[:70]!r}")
            return 1
        src = src.replace(old, new)
    cell.source = src
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print(f"OK: applied {len(EDITS)} edits (helper + 6 cached call sites).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
