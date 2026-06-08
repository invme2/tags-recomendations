# -*- coding: utf-8 -*-
"""Normalize variant prices: every product's variants -> single price (mode; tie -> min).
Also normalizes compare_at_price the same way (keep discount consistent). Only PUTs deviating variants."""
import sys, os, re, time, requests
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te

APPLY = '--apply' in sys.argv
tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}; HJ = {**H, 'Content-Type': 'application/json'}

def fetch_all():
    out=[]; url=f'{BASE}/products.json?limit=250&fields=id,handle,title,variants'
    while url:
        r=requests.get(url,headers=H,timeout=90); out+=r.json()['products']
        m=re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link','')); url=m.group(1) if m else None
        time.sleep(0.25)
    return out

def mode_price(vs):
    prices=[]
    for v in vs:
        try: prices.append(round(float(v['price']),2))
        except: pass
    if not prices: return None
    cnt=Counter(prices); top=cnt.most_common()
    maxn=top[0][1]
    tied=[p for p,n in top if n==maxn]
    return min(tied)  # tie -> cheapest (never overcharge)

def main():
    P=fetch_all()
    targets=[]
    for p in P:
        vs=p.get('variants',[])
        if len(vs)<2: continue
        prices=set()
        for v in vs:
            try: prices.add(round(float(v['price']),2))
            except: pass
        if len(prices)>1: targets.append(p)
    print('products with price variance:',len(targets),'| mode:', 'APPLY' if APPLY else 'DRY')
    fixed=0; vfixed=0
    for p in targets:
        vs=p['variants']; m=mode_price(vs); hdl=p['handle']
        # compare_at mode too (so discount stays sane)
        cmode=mode_price([{'price':v.get('compare_at_price') or 0} for v in vs]) or None
        print('  %-38s -> price %s%s' % (hdl[:38], m, (', compare %s'%cmode) if cmode else ''))
        for v in vs:
            try: vp=round(float(v['price']),2)
            except: vp=None
            need = (vp!=m)
            if not need: continue
            if APPLY:
                body={'variant':{'id':v['id'],'price':'%.2f'%m}}
                if cmode and cmode>m: body['variant']['compare_at_price']='%.2f'%cmode
                r=requests.put('%s/variants/%s.json'%(BASE,v['id']),headers=HJ,json=body,timeout=30)
                if r.status_code==200: vfixed+=1
                else: print('     ERR',v['id'],r.status_code,r.text[:80])
                time.sleep(0.35)
            else:
                print('     would set variant %s %s -> %s' % (v['title'][:24], vp, m))
        fixed+=1
    print(f'DONE: {fixed} products, {vfixed} variants repriced' + ('' if APPLY else ' (DRY)'))

if __name__=='__main__':
    main()
