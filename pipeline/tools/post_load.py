# -*- coding: utf-8 -*-
"""POST-LOAD ORCHESTRATOR — run after loading any batch of products (incl. new categories).
Collapses the CLAUDE.md facet checklist into ONE idempotent command:

  1. facet_backfill_full.py      (writes Category:/Concern:/Format:/For:/Scent: tags)
  2. compute_facet_counts.py     (writes custom.facet_counts on nav smart collections)
  3. build_seo_collection_map.py (writes shop.custom.category_collections for Shop-by-type)
  4. build_canonical_map.py      (writes shop.custom.canonical_map — non-destructive dedup)
  5. catalog_health.py           (read-only validation + drift report; gates exit code)

Every step is idempotent (writes only what changed). This orchestrator DELIBERATELY excludes
guardrailed operations — variant-price normalization and destructive SEO 301-dedup are NOT run
here; they require explicit per-action authorization (normalize_variant_prices.py --apply /
dedup_seo_collections.py --apply).

Usage:
  python pipeline/tools/post_load.py                # full run (steps 1-5), keyword tagging
  python pipeline/tools/post_load.py --llm          # full run + LLM-rescue unknown categories (cached, cheap)
  python pipeline/tools/post_load.py --health-only  # step 5 only (no writes) — CI/preview gate
  python pipeline/tools/post_load.py --no-health    # steps 1-4, skip report
"""
import sys, os, subprocess, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

WRITE_STEPS = [
    ('facet tags',        'facet_backfill_full.py'),
    ('facet counts',      'compute_facet_counts.py'),
    ('shop-by-type map',  'build_seo_collection_map.py'),
    ('canonical map',     'build_canonical_map.py'),
]
HEALTH = ('catalog health', 'catalog_health.py')

def run(label, script, extra=None):
    path = os.path.join(TOOLS, script)
    print('\n' + '=' * 72 + f'\n>>> {label}  ({script})\n' + '=' * 72, flush=True)
    t0 = time.time()
    rc = subprocess.call([PY, path] + (extra or []))
    dt = time.time() - t0
    print(f'<<< {label}: exit={rc}  ({dt:.0f}s)', flush=True)
    return rc

def main():
    health_only = '--health-only' in sys.argv
    no_health = '--no-health' in sys.argv
    results = []

    use_llm = '--llm' in sys.argv  # apply LLM-rescue of unknown categories during the tag backfill
    do_seo = '--seo' in sys.argv   # also fill seo.title / seo.description where empty
    if not health_only:
        for label, script in WRITE_STEPS:
            extra = ['--llm'] if (use_llm and script == 'facet_backfill_full.py') else None
            rc = run(label, script, extra)
            results.append((label, rc))
            time.sleep(1)
        if do_seo:
            rc = run('seo hygiene', 'seo_backfill.py', ['--apply'])
            results.append(('seo hygiene', rc))
            time.sleep(1)

    if not no_health:
        # pass through --json target if provided
        extra = []
        if '--json' in sys.argv:
            extra = ['--json', sys.argv[sys.argv.index('--json') + 1]]
        rc = run(HEALTH[0], HEALTH[1], extra)
        results.append((HEALTH[0], rc))

    print('\n' + '#' * 72 + '\nPOST-LOAD SUMMARY')
    fail = 0
    for label, rc in results:
        print(f'  {"OK  " if rc == 0 else "FAIL"}  {label}  (exit={rc})')
        if rc != 0: fail += 1
    print('#' * 72)
    if fail:
        print(f'{fail} step(s) reported a non-zero exit — review above (health FAIL = pre-publish gate).')
    sys.exit(1 if fail else 0)

if __name__ == '__main__':
    main()
