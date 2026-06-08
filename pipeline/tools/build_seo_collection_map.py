# -*- coding: utf-8 -*-
"""Map each CUSTOM (SEO/DataForSEO) collection -> dominant Category, group by category.
Writes shop metafield custom.category_collections (json) for theme 'Shop by type' linking.
Read-only on products/collects; one shop-metafield write at the end."""
import sys, os, re, time, json, requests
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
import gen_facets as G
from collections import Counter, defaultdict

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}; HJ = {**H, 'Content-Type': 'application/json'}

def paged(path, key, fields):
    out=[]; url=f'{BASE}/{path}?limit=250&fields={fields}'
    while url:
        for _ in range(5):
            r=requests.get(url,headers=H,timeout=90)
            if r.status_code==429: time.sleep(float(r.headers.get('Retry-After',2))); continue
            break
        out+=r.json().get(key,[])
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.3)
    return out

def main():
    print('products...'); P=paged('products.json','products','id,title,product_type,tags')
    cat_of={}
    for p in P:
        f=G.derive(p.get('title',''),p.get('product_type',''),p.get('tags') or '')
        fc=f.get('f_category'); cat_of[p['id']]= fc[0] if fc else 'Health & Wellness'
    print('  products',len(P))
    print('collects (memberships)...'); C=paged('collects.json','collects','collection_id,product_id')
    members=defaultdict(list)
    for c in C: members[c['collection_id']].append(c['product_id'])
    print('  collects',len(C),'covering',len(members),'collections')
    print('custom collections...'); CC=paged('custom_collections.json','custom_collections','id,handle,title')
    print('  custom',len(CC))

    by_cat=defaultdict(list)
    for col in CC:
        pids=members.get(col['id'],[])
        if not pids: continue
        cats=Counter(cat_of.get(pid,'Health & Wellness') for pid in pids)
        dom,domn=cats.most_common(1)[0]
        by_cat[dom].append({'h':col['handle'],'t':col['title'],'n':len(pids)})

    # dedupe near-duplicate SEO collections within each category (keep strongest by product count)
    def is_dup(a,b):
        na=a.replace('-',''); nb=b.replace('-','')
        return na==nb or na==nb+'s' or nb==na+'s' or na==nb+'es' or nb==na+'es'
    def dedupe(lst):
        lst=sorted(lst, key=lambda x:-x['n'])
        kept=[]
        for e in lst:
            if any(is_dup(e['h'], k['h']) for k in kept): continue
            kept.append(e)
        return kept
    mapping={}
    for cat,lst in by_cat.items():
        mapping[cat]=dedupe(lst)[:30]
    print('\n=== category -> #SEO collections ===')
    for cat in sorted(mapping,key=lambda k:-len(by_cat[k])):
        tops = ', '.join("%s(%d)" % (x['h'], x['n']) for x in mapping[cat][:4])
        print('  %-24s %4d seo-collections  top: %s' % (cat, len(by_cat[cat]), tops))

    # write shop metafield
    q='''mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){metafields{id} userErrors{field message}}}'''
    # get shop gid
    sg=requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':'{shop{id}}'},timeout=30).json()['data']['shop']['id']
    v={'m':[{'ownerId':sg,'namespace':'custom','key':'category_collections','type':'json','value':json.dumps(mapping)}]}
    r=requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':q,'variables':v},timeout=40).json()
    ue=r.get('data',{}).get('metafieldsSet',{}).get('userErrors',[])
    print('\nshop metafield custom.category_collections:', 'OK' if not ue else ue)
    json.dump(mapping, open(os.path.join(os.path.dirname(__file__),'..','runs','seo_collection_map.json'),'w'), indent=1)
    print('DONE: mapped', sum(len(v) for v in by_cat.values()), 'SEO collections into', len(mapping), 'categories')

if __name__=='__main__':
    main()
