# -*- coding: utf-8 -*-
"""SEO hygiene backfill — idempotent, NON-destructive (only fills what's empty).
Ensures every product ships SEO-correct so audit problems don't recur on each load:
  - seo.title  (<title>/title_tag): concise lead phrase, <=60 chars (raw titles run ~78)
  - seo.description (meta description): from body first sentences, ~155 chars, else template
Image alt is handled at the THEME level (card-product / vibe-card fall back to product.title),
so it's not rewritten here; pass --images to also stamp product-image alt (heavier, many writes).

Part of post_load. READ-ONLY by default (reports how many need fixing + samples).

Usage:
  python pipeline/tools/seo_backfill.py            # dry run: report gaps + samples
  python pipeline/tools/seo_backfill.py --apply    # write seo.title / seo.description where empty
  python pipeline/tools/seo_backfill.py --apply --images   # also stamp empty product-image alt
"""
import sys, os, re, time, json, requests
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
HJ = {'X-Shopify-Access-Token': tok, 'Content-Type': 'application/json'}
H = {'X-Shopify-Access-Token': tok}
APPLY = '--apply' in sys.argv
DO_IMAGES = '--images' in sys.argv

def gql(q, v=None):
    r = requests.post(f'{BASE}/graphql.json', headers=HJ, json={'query': q, 'variables': v or {}}, timeout=60)
    return r.json()

def make_title_tag(title):
    t = (title or '').strip()
    for sep in [' — ', ' – ', ' - ', ' | ', ': ']:
        if sep in t:
            lead = t.split(sep)[0].strip()
            if 15 <= len(lead) <= 60:
                return lead
    if len(t) > 60:
        return t[:60].rsplit(' ', 1)[0]
    return t

def make_desc_tag(body, title):
    txt = re.sub(r'<[^>]+>', ' ', body or '')
    txt = re.sub(r'\s+', ' ', txt).strip()
    if len(txt) >= 70:
        d = txt[:157].rsplit(' ', 1)[0].rstrip(' ,;:.')
        return d
    return ('Buy ' + (title or 'this product').strip() + ' at Wanelo — great price, fast shipping and easy returns.')[:160]

def fetch_products():
    out = []; cursor = None
    q = '''query($c:String){products(first:200,after:$c){pageInfo{hasNextPage endCursor}
      edges{node{id title descriptionHtml seo{title description}}}}}'''
    while True:
        d = gql(q, {'c': cursor})
        conn = d.get('data', {}).get('products')
        if not conn:
            print('GraphQL error:', json.dumps(d)[:300]); break
        for e in conn['edges']:
            out.append(e['node'])
        if conn['pageInfo']['hasNextPage']:
            cursor = conn['pageInfo']['endCursor']; time.sleep(0.25)
        else:
            break
    return out

def update_seo(pid, title_tag, desc_tag):
    q = '''mutation($id:ID!,$seo:SEOInput!){productUpdate(input:{id:$id,seo:$seo}){userErrors{field message}}}'''
    seo = {}
    if title_tag is not None: seo['title'] = title_tag
    if desc_tag is not None: seo['description'] = desc_tag
    d = gql(q, {'id': pid, 'seo': seo})
    return d.get('data', {}).get('productUpdate', {}).get('userErrors', [])

def stamp_image_alts(pid_num, title):
    r = requests.get(f'{BASE}/products/{pid_num}/images.json?fields=id,alt', headers=H, timeout=40)
    changed = 0
    for im in r.json().get('images', []):
        if not (im.get('alt') or '').strip():
            requests.put(f'{BASE}/products/{pid_num}/images/{im["id"]}.json', headers=HJ,
                         json={'image': {'id': im['id'], 'alt': title[:120]}}, timeout=40)
            changed += 1; time.sleep(0.2)
    return changed

def main():
    print('fetching products (GraphQL seo fields)...', flush=True)
    P = fetch_products(); N = len(P)
    need_title = need_desc = 0; samples = []
    plan = []
    for p in P:
        seo = p.get('seo') or {}
        cur_t = (seo.get('title') or '').strip(); cur_d = (seo.get('description') or '').strip()
        nt = None if cur_t else make_title_tag(p.get('title', ''))
        nd = None if cur_d else make_desc_tag(p.get('descriptionHtml', ''), p.get('title', ''))
        if nt: need_title += 1
        if nd: need_desc += 1
        if nt or nd:
            plan.append((p['id'], p.get('title', ''), nt, nd))
            if len(samples) < 6:
                samples.append((p.get('title', '')[:60], nt, (nd or '')[:70]))
    print(f'products: {N} | missing seo.title: {need_title} | missing seo.description: {need_desc}')
    print('--- sample of what would be set ---')
    for ti, nt, nd in samples:
        print(f'  {ti}\n     title -> {nt}\n     desc  -> {nd}')
    if not APPLY:
        print('\nDRY RUN. Re-run with --apply to write (non-destructive: only fills empty fields).')
        return
    print(f'\nAPPLYING to {len(plan)} products...', flush=True)
    done = fail = 0; imgs = 0
    for i, (pid, title, nt, nd) in enumerate(plan, 1):
        ue = update_seo(pid, nt, nd)
        if ue: fail += 1; print('  userErrors', pid, ue)
        else: done += 1
        if DO_IMAGES:
            imgs += stamp_image_alts(pid.split('/')[-1], title)
        if i % 100 == 0: print(f'  ...{i}/{len(plan)} done={done} fail={fail} imgAlts={imgs}', flush=True)
        time.sleep(0.2)
    print(f'DONE: seo set={done} fail={fail}' + (f' imageAlts={imgs}' if DO_IMAGES else ''))

if __name__ == '__main__':
    main()
