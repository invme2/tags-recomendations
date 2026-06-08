# -*- coding: utf-8 -*-
"""Phase 1 full facet-tag backfill to ALL products. Additive + idempotent.
Writes Category:/Concern:/Format:/For:/Scent: tags from gen_facets.derive().
PUTs only products whose facet set actually changes."""
import sys, os, re, time, requests
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
import gen_facets as G
import facet_engine as FE

USE_LLM = '--llm' in sys.argv      # rescue unknowns via Haiku over title+type+DESCRIPTION (cached)
USE_VISION = '--vision' in sys.argv  # last-resort: classify from the PRODUCT PHOTO (EPROLO thin, photo rich)
def _derive(ti, pt, tg, body='', img=None):
    if USE_LLM or USE_VISION:
        return FE.derive(ti, pt, tg, desc=body, image_url=img, use_llm=True, use_vision=USE_VISION)
    return G.derive(ti, pt, tg, desc=body)  # keyword path now also scans the description

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok, 'Content-Type': 'application/json'}
PREFIXES = ('Category:', 'Concern:', 'Format:', 'For:', 'Scent:')
KMAP = {'f_category': 'Category', 'f_concern': 'Concern', 'f_form': 'Format', 'f_audience': 'For', 'f_scent': 'Scent'}

def fetch_all():
    out=[]; url=f'{BASE}/products.json?limit=250&fields=id,title,product_type,tags,body_html,image'
    while url:
        r=requests.get(url,headers={'X-Shopify-Access-Token':tok},timeout=90); out+=r.json()['products']
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.25)
    return out

def put_tags(pid, tags_str, tries=4):
    for a in range(tries):
        r=requests.put(f'{BASE}/products/{pid}.json',headers=H,json={'product':{'id':pid,'tags':tags_str}},timeout=40)
        if r.status_code==200: return True
        if r.status_code==429:
            time.sleep(float(r.headers.get('Retry-After',2))); continue
        time.sleep(1.0)
    return False

def main():
    print('fetching all products...'); P=fetch_all(); print('total',len(P))
    changed=0; skipped=0; failed=0; i=0
    for p in P:
        i+=1
        img=(p.get('image') or {}).get('src')
        f=_derive(p.get('title',''), p.get('product_type',''), p.get('tags') or '', p.get('body_html') or '', img)
        facet=[]
        for k,label in KMAP.items():
            for v in f.get(k,[]): facet.append(f'{label}:{v}')
        existing=[t.strip() for t in (p.get('tags') or '').split(',') if t.strip()]
        kept=[t for t in existing if not t.startswith(PREFIXES)]
        # dedupe preserve order
        final=[]; seen=set()
        for t in kept+facet:
            if t.lower() not in seen: seen.add(t.lower()); final.append(t)
        # compare facet-sets (only PUT if facets actually differ)
        cur_facets=set(t for t in existing if t.startswith(PREFIXES))
        new_facets=set(facet)
        if cur_facets==new_facets:
            skipped+=1
        else:
            if put_tags(p['id'], ', '.join(final)): changed+=1
            else: failed+=1
            time.sleep(0.4)
        if i % 250 == 0:
            print(f'  ...{i}/{len(P)} | changed={changed} skipped={skipped} failed={failed}', flush=True)
    print(f'DONE: changed={changed} skipped(already correct)={skipped} failed={failed} total={len(P)}')

if __name__=='__main__':
    main()
