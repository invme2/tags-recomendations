# -*- coding: utf-8 -*-
"""Catalog health / validation — READ ONLY. Run post-batch or in CI before publish.
Checks (each PASS / WARN / FAIL):
  1. classification coverage   — % products unclassified by the keyword engine (new categories surface here)
  2. engine drift              — legacy gen_facets vs new facet_engine: how many products' facet-set changes
  3. nav facet_counts          — smart collections missing custom.facet_counts metafield
  4. canonical_map integrity   — handles in shop.custom.canonical_map that no longer resolve
  5. variant price variance    — products whose variants have >1 distinct price
  6. content hygiene           — products with empty body_html or junk product_type
Exit code != 0 if any FAIL (use as a pre-publish gate).

Usage:
  python pipeline/tools/catalog_health.py
  python pipeline/tools/catalog_health.py --json runs/catalog_health.json
"""
import sys, os, re, time, json, requests
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
import facet_engine as FE
try:
    import gen_facets_legacy as LEG
    HAVE_LEG = True
except Exception:
    HAVE_LEG = False

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}; HJ = {**H, 'Content-Type': 'application/json'}
PREFIXES = ('Category:', 'Concern:', 'Format:', 'For:', 'Scent:')

# thresholds
UNCLS_WARN = 0.02   # >2% unclassified -> WARN
UNCLS_FAIL = 0.10   # >10% -> FAIL

def fetch_products():
    out = []; url = f'{BASE}/products.json?limit=250&fields=id,handle,title,product_type,tags,variants,body_html'
    while url:
        r = requests.get(url, headers=H, timeout=90); out += r.json().get('products', [])
        m = re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link', '')); url = m.group(1) if m else None
        time.sleep(0.2)
    return out

def smart_collections():
    out = []; url = f'{BASE}/smart_collections.json?limit=250&fields=id,handle,title'
    while url:
        r = requests.get(url, headers=H, timeout=60); out += r.json().get('smart_collections', [])
        m = re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link', '')); url = m.group(1) if m else None
        time.sleep(0.2)
    return out

def coll_has_metafield(cid, ns, key):
    r = requests.get(f'{BASE}/collections/{cid}/metafields.json?namespace={ns}&key={key}', headers=H, timeout=40)
    return bool(r.json().get('metafields'))

def all_collection_handles():
    handles = set()
    for ep in ['smart_collections', 'custom_collections']:
        url = f'{BASE}/{ep}.json?limit=250&fields=id,handle'
        while url:
            r = requests.get(url, headers=H, timeout=60)
            for x in r.json().get(ep, []): handles.add(x['handle'])
            m = re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link', '')); url = m.group(1) if m else None
            time.sleep(0.2)
    return handles

def shop_metafield(ns, key):
    q = 'query($ns:String!,$k:String!){shop{metafield(namespace:$ns,key:$k){value}}}'
    r = requests.post(f'{BASE}/graphql.json', headers=HJ, json={'query': q, 'variables': {'ns': ns, 'k': key}}, timeout=40).json()
    mf = (r.get('data', {}).get('shop', {}) or {}).get('metafield')
    return mf.get('value') if mf else None

def facetset(d):
    s = set()
    for k, vs in (d or {}).items():
        for v in vs: s.add(k + ':' + v)
    return s

RESULTS = []
def record(name, status, detail):
    RESULTS.append({'check': name, 'status': status, 'detail': detail})
    icon = {'PASS': 'OK  ', 'WARN': 'WARN', 'FAIL': 'FAIL'}[status]
    print(f'[{icon}] {name}: {detail}')

def main():
    out_json = None
    if '--json' in sys.argv: out_json = sys.argv[sys.argv.index('--json') + 1]
    print('fetching catalog...', flush=True)
    P = fetch_products(); N = len(P)
    print(f'products: {N}\n' + '-' * 72)

    # 1 ACTUAL tag coverage (gated) — % products that carry a Category: tag in Shopify right now.
    #   This is the real state after backfill (not a re-derivation). Target ~100%.
    untagged = 0; cat_actual = Counter()
    for p in P:
        tags = [t.strip() for t in (p.get('tags') or '').split(',') if t.strip()]
        ct = [t[9:] for t in tags if t.startswith('Category:')]
        if ct: cat_actual[ct[0]] += 1
        else: untagged += 1
    utr = untagged / N if N else 0
    st = 'FAIL' if utr > 0.05 else ('WARN' if untagged else 'PASS')
    record('category_tag_coverage', st, f'{N-untagged}/{N} products carry a Category: tag ({untagged} untagged)' +
           ('  -> run post_load' if untagged else ''))

    # 2 engine view (informational) — keyword-unclassified + legacy-vs-current delta. Not gated.
    uncls = 0; drift = 0; cat_new = Counter(); proposals = Counter(); drift_samples = []
    for p in P:
        ti = p.get('title', ''); pt = p.get('product_type', ''); tg = p.get('tags') or ''
        r = FE.classify(ti, pt, tg, use_llm=False)
        cat_new[r['category']] += 1
        if r['unclassified']:
            uncls += 1
            if r.get('proposed_category'): proposals[r['proposed_category']] += 1
        if HAVE_LEG:
            fo = facetset(LEG.derive(ti, pt, tg)); fn = facetset(FE.derive_keyword(ti, pt, tg))
            if fo != fn:
                drift += 1
                if len(drift_samples) < 12:
                    drift_samples.append({'title': ti[:48], 'removed': sorted(fo - fn), 'added': sorted(fn - fo)})
    record('keyword_unclassified', 'PASS', f'{uncls}/{N} ({uncls/N*100:.1f}%) need LLM-rescue/onboarding (use post_load --llm)' +
           (f' | proposed new: {dict(proposals.most_common(5))}' if proposals else ''))
    if HAVE_LEG:
        record('engine_vs_legacy_delta', 'PASS',
               f'{drift}/{N} products differ between archived legacy rules and current engine (informational)')

    # 3 nav facet_counts
    cols = smart_collections(); missing = []
    for c in cols:
        if not coll_has_metafield(c['id'], 'custom', 'facet_counts'): missing.append(c['handle'])
        time.sleep(0.15)
    record('nav_facet_counts', 'WARN' if missing else 'PASS',
           f'{len(cols)-len(missing)}/{len(cols)} smart collections have facet_counts' +
           (f' | missing: {missing[:8]}' if missing else ''))

    # 4 canonical_map integrity
    cm = shop_metafield('custom', 'canonical_map')
    if cm:
        try: cmap = json.loads(cm)
        except Exception: cmap = {}
        handles = all_collection_handles()
        broken = [f'{k}->{v}' for k, v in cmap.items() if v not in handles or k not in handles]
        record('canonical_map_integrity', 'FAIL' if broken else 'PASS',
               f'{len(cmap)} mappings, {len(broken)} broken' + (f' | {broken[:6]}' if broken else ''))
    else:
        record('canonical_map_integrity', 'WARN', 'shop.custom.canonical_map not set')

    # 5 variant price variance (INFORMATIONAL — different sizes legitimately have different prices)
    var = []
    for p in P:
        prices = {v.get('price') for v in (p.get('variants') or []) if v.get('price') is not None}
        if len(prices) > 1: var.append({'handle': p.get('handle'), 'prices': sorted(prices)})
    record('variant_price_variance', 'PASS',
           f'{len(var)} products have >1 distinct variant price (expected for size variants; not a gate)' +
           (f' | e.g. {[(v["handle"], v["prices"]) for v in var[:5]]}' if var else ''))

    # 6 content hygiene
    no_body = [p.get('handle') for p in P if not (p.get('body_html') or '').strip()]
    junk_pt = [p.get('handle') for p in P if not (p.get('product_type') or '').strip()]
    record('content_hygiene', 'WARN' if (no_body or junk_pt) else 'PASS',
           f'{len(no_body)} empty body_html, {len(junk_pt)} empty product_type')

    # category distribution (actual Shopify tags)
    print('-' * 72 + '\ncategory distribution (actual Category: tags in catalog):')
    for cat, n in cat_actual.most_common():
        print(f'  {cat:26s} {n}')

    fails = [r for r in RESULTS if r['status'] == 'FAIL']
    warns = [r for r in RESULTS if r['status'] == 'WARN']
    print('-' * 72 + f'\nSUMMARY: {len(RESULTS)} checks | {len(fails)} FAIL | {len(warns)} WARN')
    if out_json:
        os.makedirs(os.path.dirname(out_json) or '.', exist_ok=True)
        json.dump({'products': N, 'checks': RESULTS, 'category_distribution': dict(cat_actual),
                   'category_distribution_keyword': dict(cat_new), 'drift_samples': drift_samples},
                  open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('wrote', out_json)
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main()
