# -*- coding: utf-8 -*-
"""Phase 0 catalog audit (READ-ONLY). Coverage, problems, collection breadth."""
import sys, os, re, time, json
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
import gen_facets as G
import requests
from collections import Counter

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}

def get(path, **params):
    return requests.get(f'{BASE}/{path}', headers=H, params=params, timeout=60)

def fetch_all_products():
    out=[]; url=f'{BASE}/products.json?limit=250&fields=id,title,handle,product_type,vendor,tags,status,images,variants'
    while url:
        r=requests.get(url,headers=H,timeout=90); js=r.json().get('products',[]); out+=js
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.3)
    return out

CLEAN_PREFIXES=('Category:','Concern:','Format:','For:','Scent:','Skin type:','Volume:')

def main():
    print('Fetching all products...'); P=fetch_all_products(); n=len(P); print('total products:',n)
    c=Counter()
    cat_dist=Counter(); ptype_dist=Counter(); vendor_dist=Counter()
    problems={'no_image':[], 'zero_price':[], 'no_derivable_cat':[], 'no_facet_tags':[]}
    derive_cat=Counter(); derive_cov=0
    multi_variant=0
    for p in P:
        tags=p.get('tags') or ''
        has_clean = any(prefix in t for t in [tags] for prefix in CLEAN_PREFIXES)
        # more precise: any tag starts with a clean prefix
        taglist=[t.strip() for t in tags.split(',') if t.strip()]
        has_clean = any(t.startswith(CLEAN_PREFIXES) for t in taglist)
        if has_clean: c['clean_facets']+=1
        else: problems['no_facet_tags'].append(p['handle'])
        if (p.get('product_type') or '').strip(): c['has_ptype']+=1; ptype_dist[p['product_type'].strip()]+=1
        if (p.get('vendor') or '').strip(): c['has_vendor']+=1; vendor_dist[p['vendor'].strip()]+=1
        imgs=p.get('images') or []
        if imgs: c['has_image']+=1
        else: problems['no_image'].append(p['handle'])
        vs=p.get('variants') or []
        if len(vs)>1: multi_variant+=1
        price=0.0
        try: price=float(vs[0]['price']) if vs else 0.0
        except: price=0.0
        if price>0: c['valid_price']+=1
        else: problems['zero_price'].append(p['handle'])
        onsale=False
        try:
            cap=vs[0].get('compare_at_price'); onsale = cap and float(cap)>price
        except: pass
        if onsale: c['on_sale']+=1
        if (p.get('status'))=='active': c['active']+=1
        # derive facets
        f=G.derive(p.get('title',''), p.get('product_type',''), tags)
        if f: derive_cov+=1
        fc=f.get('f_category')
        if fc: derive_cat[fc[0]]+=1
        else: problems['no_derivable_cat'].append(p['handle'])

    def pct(k): return f"{c[k]} ({round(100.0*c[k]/n)}%)"
    print('\n=== COVERAGE (of %d) ==='%n)
    for k,label in [('active','active/published'),('has_image','has image'),('valid_price','valid price>0'),
                    ('on_sale','on sale'),('has_ptype','has product_type'),('has_vendor','has vendor'),
                    ('clean_facets','has CLEAN facet tags')]:
        print(f'  {label:24s}: {pct(k)}')
    print(f'  multi-variant products  : {multi_variant} ({round(100.0*multi_variant/n)}%)')
    print(f'  derive() yields >=1 facet: {derive_cov} ({round(100.0*derive_cov/n)}%)')

    print('\n=== DERIVED Category distribution (whole catalog) ===')
    for k,v in derive_cat.most_common(20): print(f'  {v:5d}  {k}')

    print('\n=== PROBLEMS ===')
    for k,v in problems.items(): print(f'  {k:18s}: {len(v)}  e.g. {[x[:24] for x in v[:3]]}')

    print('\n=== top product_type (messy free-text) ===')
    for k,v in ptype_dist.most_common(15): print(f'  {v:5d}  {k.encode("ascii","replace").decode()!r}')
    print('distinct product_type values:', len(ptype_dist))
    print('distinct vendor values:', len(vendor_dist), '| top:', [v.encode("ascii","replace").decode() for v,_ in vendor_dist.most_common(5)])

    # ---- collections ----
    print('\n=== COLLECTIONS ===')
    cols=[]
    for ep in ['smart_collections','custom_collections']:
        url=f'{BASE}/{ep}.json?limit=250&fields=id,handle,title,products_count'
        while url:
            r=requests.get(url,headers=H,timeout=60); js=r.json().get(ep,[])
            for x in js: x['_kind']=ep.replace('_collections',''); cols.append(x)
            m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
            time.sleep(0.25)
    print('total collections:',len(cols), '| smart:',sum(1 for x in cols if x['_kind']=='smart'),
          '| custom:',sum(1 for x in cols if x['_kind']=='custom'))
    cols.sort(key=lambda x: x.get('products_count',0), reverse=True)
    print('\nTop 18 collections by size + CATEGORY BREADTH (distinct derived categories among first 250):')
    for col in cols[:18]:
        r=get('products.json', collection_id=col['id'], limit=250, fields='id,title,product_type,tags')
        ps=r.json().get('products',[]); time.sleep(0.3)
        cats=Counter()
        for p in ps:
            f=G.derive(p.get('title',''), p.get('product_type',''), p.get('tags',''))
            if f.get('f_category'): cats[f['f_category'][0]]+=1
        breadth=len(cats); topcats=', '.join(f"{k}:{v}" for k,v in cats.most_common(4))
        flag=' <== BROAD' if breadth>=6 else ''
        print(f'  [{col["_kind"][:1]}] {col["handle"][:30]:30s} n={col.get("products_count",0):4d} breadth={breadth:2d}{flag}  top: {topcats}')

    print('\nDONE')

if __name__=='__main__':
    main()
