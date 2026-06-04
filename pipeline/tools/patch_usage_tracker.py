# -*- coding: utf-8 -*-
"""patch_usage_tracker.py — make the Anthropic cache/cost tracker actually useful.

PROBLEM: `_anthropic_cost_tracker` is in-memory only. Every babysitter restart
spawns a fresh process → the tracker resets to 0. The end-of-run summary then
prints the totals for ONE resumed segment (often 0/0/0 when that segment only
ran the DeepSeek Designer and made no Anthropic calls). The operator sees
"0 read / 0 written / 0 fresh" and thinks caching is broken — it isn't; the
counter just never survives a restart and has no per-model split.

FIX (cell 4 + cell 14, nbformat):
  - persist the tracker to a JSON sidecar next to THIS run's DB
    (`{PROJECT_DIR}/anthropic_usage.json`) after every tracked call;
  - on the first track call of a process, MERGE the sidecar back in, so totals
    accumulate across restarts = JOB-WIDE cache-hit ratio, not one segment;
  - per-model breakdown (Opus vs Haiku) read from `resp.model`, so the operator
    can see the expensive Opus calls cache well while cheap Haiku image tokens
    are what drag the blended ratio down;
  - the summary block calls `_load_usage_once()` first, so even a resume-only
    segment prints the real job-wide numbers, and adds a per-model table.

Standalone reader (no notebook run needed): pipeline/tools/anthropic_usage_report.py

After: notebook_smoke + pytest.
"""
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

# ---- cell 4: tracker dict ----
DICT_OLD = """_anthropic_cost_tracker = {
    'spent_usd':       0.0,
    'cache_read_in':   0,   # tokens read from cache (cheap, 0.08/M)
    'cache_create_in': 0,   # tokens written to cache (full price)
    'fresh_in':        0,   # tokens not cached (full price)
    'output_tokens':   0,
    'calls':           0,
}"""

DICT_NEW = """_anthropic_cost_tracker = {
    'spent_usd':       0.0,
    'cache_read_in':   0,   # tokens read from cache (cheap, 0.08/M)
    'cache_create_in': 0,   # tokens written to cache (full price)
    'fresh_in':        0,   # tokens not cached (full price)
    'output_tokens':   0,
    'calls':           0,
    'by_model':        {},  # {model: {fresh,read,create,output,calls,spent}} per-model split
}
_usage_sidecar_loaded = [False]  # one-shot guard: merge prior restart-segment totals once"""

# ---- cell 4: tracker function (+ sidecar helpers) ----
FN_OLD = """def _track_anthropic_response(resp, cost_usd):
    \"\"\"Bump the global counter from an Anthropic Messages response.
    Call once per messages.create result. resp.usage is the truth-source
    for token counts incl. cache fields.\"\"\"
    _anthropic_cost_tracker['spent_usd'] += cost_usd
    _anthropic_cost_tracker['calls'] += 1
    u = getattr(resp, 'usage', None)
    if u is not None:
        _anthropic_cost_tracker['fresh_in']        += int(getattr(u, 'input_tokens', 0) or 0)
        _anthropic_cost_tracker['cache_read_in']   += int(getattr(u, 'cache_read_input_tokens', 0) or 0)
        _anthropic_cost_tracker['cache_create_in'] += int(getattr(u, 'cache_creation_input_tokens', 0) or 0)
        _anthropic_cost_tracker['output_tokens']   += int(getattr(u, 'output_tokens', 0) or 0)"""

FN_NEW = """def _usage_sidecar_path():
    \"\"\"JSON sidecar next to THIS run's DB — survives babysitter restarts so the
    cache-hit ratio reflects the whole job, not a single resumed segment.\"\"\"
    try:
        _base = PROJECT_DIR
    except NameError:
        _base = '.'
    return os.path.join(_base, 'anthropic_usage.json')


_USAGE_KEYS = ('spent_usd', 'cache_read_in', 'cache_create_in', 'fresh_in', 'output_tokens', 'calls')


def _load_usage_once():
    \"\"\"Merge any prior segments' totals from the sidecar into the live counter,
    exactly once per process. Makes restart-accumulated totals job-wide.\"\"\"
    if _usage_sidecar_loaded[0]:
        return
    _usage_sidecar_loaded[0] = True
    try:
        _p = _usage_sidecar_path()
        if os.path.exists(_p):
            with open(_p, encoding='utf-8') as _f:
                _prior = json.load(_f)
            for _k in _USAGE_KEYS:
                _anthropic_cost_tracker[_k] += _prior.get(_k, 0) or 0
            for _m, _mv in (_prior.get('by_model') or {}).items():
                _cur = _anthropic_cost_tracker['by_model'].setdefault(
                    _m, {'fresh': 0, 'read': 0, 'create': 0, 'output': 0, 'calls': 0, 'spent': 0.0})
                for _kk in _cur:
                    _cur[_kk] += _mv.get(_kk, 0) or 0
    except Exception as _e_lu:
        print(f'    (usage sidecar load skipped: {str(_e_lu)[:60]})')


def _persist_usage():
    \"\"\"Write the cumulative counter to the sidecar (atomic-ish: tmp + replace).\"\"\"
    try:
        _p = _usage_sidecar_path()
        _tmp = _p + '.tmp'
        with open(_tmp, 'w', encoding='utf-8') as _f:
            json.dump(_anthropic_cost_tracker, _f, ensure_ascii=False)
        os.replace(_tmp, _p)
    except Exception:
        pass


def _track_anthropic_response(resp, cost_usd):
    \"\"\"Bump the global counter from an Anthropic Messages response, with per-model
    split, and persist to a per-run JSON sidecar (restart-safe, job-wide totals).
    resp.usage is the truth-source for token counts incl. cache fields.\"\"\"
    _load_usage_once()
    _anthropic_cost_tracker['spent_usd'] += cost_usd
    _anthropic_cost_tracker['calls'] += 1
    u = getattr(resp, 'usage', None)
    _model = getattr(resp, 'model', None) or 'unknown'
    if u is not None:
        _fin = int(getattr(u, 'input_tokens', 0) or 0)
        _crd = int(getattr(u, 'cache_read_input_tokens', 0) or 0)
        _ccr = int(getattr(u, 'cache_creation_input_tokens', 0) or 0)
        _out = int(getattr(u, 'output_tokens', 0) or 0)
        _anthropic_cost_tracker['fresh_in']        += _fin
        _anthropic_cost_tracker['cache_read_in']   += _crd
        _anthropic_cost_tracker['cache_create_in'] += _ccr
        _anthropic_cost_tracker['output_tokens']   += _out
        _bm = _anthropic_cost_tracker['by_model'].setdefault(
            _model, {'fresh': 0, 'read': 0, 'create': 0, 'output': 0, 'calls': 0, 'spent': 0.0})
        _bm['fresh'] += _fin; _bm['read'] += _crd; _bm['create'] += _ccr
        _bm['output'] += _out; _bm['calls'] += 1; _bm['spent'] += cost_usd
    _persist_usage()"""

# ---- cell 14: summary — load job-wide totals first + per-model table ----
SUM_OLD = """_cct = _anthropic_cost_tracker
_total_in = _cct['fresh_in'] + _cct['cache_read_in'] + _cct['cache_create_in']"""

SUM_NEW = """_load_usage_once()  # merge prior restart-segments so the ratio is JOB-WIDE, not just this segment
_cct = _anthropic_cost_tracker
_total_in = _cct['fresh_in'] + _cct['cache_read_in'] + _cct['cache_create_in']"""

PERMODEL_OLD = """if _cache_ratio < 15 and _total_in > 50000:
    print(f"    \\u26a0 cache hit ratio low ({_cache_ratio:.1f}%) — verify cache_control sticky in system blocks")"""

PERMODEL_NEW = """if _cache_ratio < 15 and _total_in > 50000:
    print(f"    \\u26a0 blended cache hit low ({_cache_ratio:.1f}%) — usually CHEAP Haiku image tokens, not a leak; check per-model below")
for _m, _mv in sorted(_anthropic_cost_tracker.get('by_model', {}).items(), key=lambda kv: -kv[1].get('spent', 0)):
    _mt = _mv['fresh'] + _mv['read'] + _mv['create']
    _mr = (_mv['read'] / _mt * 100) if _mt else 0.0
    print(f"      {_m:<26} {_mv['calls']:>4} calls | cache {_mr:4.1f}% "
          f"({_mv['read']:,}r/{_mv['create']:,}w/{_mv['fresh']:,}f) | ${_mv['spent']:.2f}")"""

EDITS = [
    (4, DICT_OLD, DICT_NEW),
    (4, FN_OLD, FN_NEW),
    (14, SUM_OLD, SUM_NEW),
    (14, PERMODEL_OLD, PERMODEL_NEW),
]


def main():
    nb = nbformat.read(NB, as_version=4)
    for idx, (cell_i, old, new) in enumerate(EDITS):
        cell = nb.cells[cell_i]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx} (cell {cell_i}): found {n} (need 1)")
            print(f"  anchor: {old[:70]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx} (cell {cell_i})")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("usage tracker patched: sidecar persist + per-model + restart-accumulate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
