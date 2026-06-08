# -*- coding: utf-8 -*-
"""Non-destructive dedup: compute weak->strong canonical map for near-duplicate SEO collections,
write to shop metafield custom.canonical_map (json). Theme outputs <link rel=canonical> for weak ones.
Nothing is unpublished/deleted/redirected."""
import sys, os, re, time, json, requests
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}; HJ = {**H, 'Content-Type': 'application/json'}

def fetch_custom():
    out=[]; url=f'{BASE}/custom_collections.json?limit=250&fields=id,handle'
    while url:
        r=requests.get(url,headers=H,timeout=60); out+=r.json()['custom_collections']
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.25)
    return out

def is_dup(a,b):
    na=a.replace('-',''); nb=b.replace('-','')
    return na==nb or na==nb+'s' or nb==na+'s' or na==nb+'es' or nb==na+'es'

def pcount(cid):
    return requests.get(f'{BASE}/products/count.json',headers=H,params={'collection_id':cid},timeout=30).json().get('count',0)

def main():
    cols=fetch_custom(); handles=[c['handle'] for c in cols]; byh={c['handle']:c for c in cols}
    parent={h:h for h in handles}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    buckets=defaultdict(list)
    for h in handles: buckets[h.replace('-','')[:4]].append(h)
    for _,hs in buckets.items():
        for i in range(len(hs)):
            for j in range(i+1,len(hs)):
                if is_dup(hs[i],hs[j]): parent[find(hs[i])]=find(hs[j])
    clusters=defaultdict(list)
    for h in handles: clusters[find(h)].append(h)
    dupc=[v for v in clusters.values() if len(v)>1]
    cmap={}
    for clu in dupc:
        counts={h:pcount(byh[h]['id']) for h in clu}; time.sleep(0.1)
        strong=sorted(clu, key=lambda h:(counts[h], len(h)))[-1]
        for w in clu:
            if w!=strong: cmap[w]=strong
    print('canonical pairs:',len(cmap))
    for w,s in list(cmap.items())[:10]: print('  ',w,'-> canonical',s)
    # def + write shop metafield
    q='''mutation($d:MetafieldDefinitionInput!){metafieldDefinitionCreate(definition:$d){createdDefinition{id} userErrors{code message}}}'''
    requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':q,'variables':{'d':{'name':'Canonical map','namespace':'custom','key':'canonical_map','type':'json','ownerType':'SHOP','access':{'storefront':'PUBLIC_READ'}}}},timeout=40)
    sg=requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':'{shop{id}}'},timeout=30).json()['data']['shop']['id']
    qs='''mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){metafields{id} userErrors{field message}}}'''
    r=requests.post(f'{BASE}/graphql.json',headers=HJ,json={'query':qs,'variables':{'m':[{'ownerId':sg,'namespace':'custom','key':'canonical_map','type':'json','value':json.dumps(cmap)}]}},timeout=40).json()
    ue=r.get('data',{}).get('metafieldsSet',{}).get('userErrors',[])
    print('shop metafield canonical_map:', 'OK' if not ue else ue)

if __name__=='__main__':
    main()
