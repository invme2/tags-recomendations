# -*- coding: utf-8 -*-
"""Dedup near-duplicate SEO collections (singular/plural, hyphen variants).
Keep the STRONGEST (most products); unpublish the weaker + 301 redirect weak->strong.
Reversible: republish + delete redirect. Run with --apply to execute (default: dry)."""
import sys, os, re, time, requests
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
from collections import defaultdict

APPLY = '--apply' in sys.argv
tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}; HJ = {**H, 'Content-Type': 'application/json'}

def fetch_custom():
    out=[]; url=f'{BASE}/custom_collections.json?limit=250&fields=id,handle,title,published_at'
    while url:
        r=requests.get(url,headers=H,timeout=60); out+=r.json()['custom_collections']
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.25)
    return out

def is_dup(a,b):
    na=a.replace('-',''); nb=b.replace('-','')
    if na==nb: return True
    if na==nb+'s' or nb==na+'s': return True
    if na==nb+'es' or nb==na+'es': return True
    if na==nb+'ies'[:0] : return False
    return False

def pcount(cid):
    return requests.get(f'{BASE}/products/count.json',headers=H,params={'collection_id':cid},timeout=30).json().get('count',0)

def main():
    cols=fetch_custom(); print('custom collections:',len(cols))
    handles=[c['handle'] for c in cols]; byh={c['handle']:c for c in cols}
    # union-find within prefix buckets
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
    dupc=[sorted(v) for v in clusters.values() if len(v)>1]
    print('duplicate clusters:',len(dupc),'covering',sum(len(v) for v in dupc),'collections')
    print('mode:', 'APPLY' if APPLY else 'DRY (use --apply to execute)')
    actions=[]
    for clu in dupc:
        counts={h:pcount(byh[h]['id']) for h in clu}; time.sleep(0.1*len(clu))
        # strong = max products; tie -> longer handle (plural usually higher volume)
        strong=sorted(clu, key=lambda h:(counts[h], len(h)))[-1]
        weaks=[h for h in clu if h!=strong]
        print(f'  KEEP {strong}({counts[strong]})  <-  ' + ', '.join(f'{w}({counts[w]})' for w in weaks))
        for w in weaks: actions.append((w,strong))
    print(f'\nplanned: redirect+unpublish {len(actions)} weak collections')
    if not APPLY:
        print('DRY done.'); return
    done=0
    for weak,strong in actions:
        wid=byh[weak]['id']
        # unpublish weak
        requests.put(f'{BASE}/custom_collections/{wid}.json',headers=HJ,json={'custom_collection':{'id':wid,'published':False}},timeout=30)
        time.sleep(0.3)
        # 301 redirect weak -> strong
        r=requests.post(f'{BASE}/redirects.json',headers=HJ,json={'redirect':{'path':f'/collections/{weak}','target':f'/collections/{strong}'}},timeout=30)
        if r.status_code in (200,201): done+=1
        elif r.status_code==422 and 'already' in r.text.lower(): done+=1
        else: print('   redirect ERR',weak,r.status_code,r.text[:80])
        time.sleep(0.35)
    print(f'DONE: {done}/{len(actions)} weak collections unpublished + redirected to their strong twin')

if __name__=='__main__':
    main()
