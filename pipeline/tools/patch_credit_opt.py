#!/usr/bin/env python3
"""patch_credit_opt.py — one-off nbformat patch: Anthropic credit optimizations.

Applied (2026-05-31, operator: reduce Claude spend WITHOUT touching Opus / quality):
  1. Extended prompt-cache TTL 5min -> 1h on every system cache_control block,
     so the cache survives slow serial Designer streams (8-10 min/product) and
     gets REUSED across the batch instead of being re-written every product.
  2. anthropic-beta header `extended-cache-ttl-2025-04-11` on both clients
     (required to honor ttl:"1h").
  3. BATCH_CONCURRENCY default 1 -> 3: overlapping calls keep the cache hot
     inside its window and cut wall-clock ~3x. Products are independent.
  4. Strategy (Opus) max_tokens 4096 -> 2500 + terse-JSON instruction. The
     strategy brief is internal (never shown to users); trimming the priciest
     token type ($75/M output) with zero user-visible quality change.

Runs via nbformat (sanctioned path; NOT manual JSON editing). After running,
verify with: python pipeline/tools/notebook_smoke.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

# (cell_index, old, new, expected_count)  count=None -> replace_all (must be >0)
EDITS = [
    # 3. concurrency
    (2,
     "BATCH_CONCURRENCY  = _safe_env_int('BATCH_CONCURRENCY', 1)",
     "BATCH_CONCURRENCY  = _safe_env_int('BATCH_CONCURRENCY', 3)",
     1),
    # 2. beta header on both clients
    (4,
     "client_async = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY, max_retries=5)",
     'client_async = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY, max_retries=5, '
     'default_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"})',
     1),
    (4,
     "client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=5)",
     'client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=5, '
     'default_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"})',
     1),
    # 1. extended TTL on every system cache_control (5 sites, all identical)
    (14,
     '"cache_control":{"type":"ephemeral"}',
     '"cache_control":{"type":"ephemeral","ttl":"1h"}',
     None),
    # 4a. strategy output cap
    (14,
     "model=MODEL_STRATEGY, max_tokens=4096, timeout=120.0,",
     "model=MODEL_STRATEGY, max_tokens=2500, timeout=120.0,",
     1),
    # 4b. strategy terse-JSON instruction (append to user content)
    (14,
     '                f"LANGUAGE: {LANGUAGE}\\n"\n            )',
     '                f"LANGUAGE: {LANGUAGE}\\n"\n'
     '                "OUTPUT: respond with ONLY compact JSON — no markdown fences, '
     'no prose, terse string values.\\n"\n            )',
     1),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    for ci, old, new, want in EDITS:
        cell = nb.cells[ci]
        src = cell.source
        n = src.count(old)
        if n == 0:
            print(f"FAIL c{ci}: pattern not found: {old[:60]!r}")
            return 1
        if want is not None and n != want:
            print(f"FAIL c{ci}: expected {want} match, found {n}: {old[:60]!r}")
            return 1
        cell.source = src.replace(old, new)
        print(f"OK c{ci}: replaced {n}x  {old[:50]!r}")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("\nnbformat.validate passed; notebook written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
