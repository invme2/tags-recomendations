# -*- coding: utf-8 -*-
"""Phase 1: compute facet counts per navigation collection -> custom.facet_counts (json).
Counts products per facet tag (Category:/Concern:/Format:/For:/Scent:) within each collection.
Runs AFTER the facet backfill. Targets all SMART collections (browse surface)."""
import sys, os, re, time, json, requests
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}
HJ = {**H, 'Content-Type': 'application/json'}
PREFIXES = ('Category:', 'Concern:', 'Format:', 'For:', 'Scent:')

def all_collections():
    out=[]
    for ep in ['smart_collections']:  # browse surface; extend with custom if needed
        url=f'{BASE}/{ep}.json?limit=250&fields=id,handle,title'
        while url:
            r=requests.get(url,headers=H,timeout=60); js=r.json().get(ep,[])
            for x in js: x['_kind']=ep; out.append(x)
            m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
            time.sleep(0.25)
    return out

def coll_products_tags(cid):
    out=[]; url=f'{BASE}/products.json?collection_id={cid}&limit=250&fields=id,tags'
    while url:
        r=requests.get(url,headers=H,timeout=60); out+=r.json().get('products',[])
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.3)
    return out

def set_counts(cid, counts):
    q='''mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){metafields{id} userErrors{field message}}}'''
    v={'m':[{'ownerId':f'gid://shopify/Collection/{cid}','namespace':'custom','key':'facet_counts',
             'type':'json','value':json.dumps(counts)}]}
    r=requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':q,'variables':v},timeout=40).json()
    ue=r.get('data',{}).get('metafieldsSet',{}).get('userErrors',[])
    return ue

def main():
    cols=all_collections(); print('navigation collections:',len(cols))
    done=0
    for col in cols:
        ps=coll_products_tags(col['id'])
        cnt={}
        for p in ps:
            for t in (p.get('tags') or '').split(','):
                t=t.strip()
                if t.startswith(PREFIXES): cnt[t]=cnt.get(t,0)+1
        if not cnt:
            print('  skip (no facets yet):', col['handle']); continue
        ue=set_counts(col['id'], cnt)
        done+=1
        top=sorted(cnt.items(), key=lambda x:-x[1])[:4]
        print(f'  {col["handle"][:28]:28s} products={len(ps):4d} facets={len(cnt):3d} {"ERR "+str(ue) if ue else "OK"}  top={top}')
        time.sleep(0.35)
    print(f'DONE: facet_counts written to {done} collections')

if __name__=='__main__':
    main()
