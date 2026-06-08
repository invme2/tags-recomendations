# -*- coding: utf-8 -*-
"""Generate per-category filter facets (metafields) from existing product data.
Facets are populated ONLY where relevant -> Shopify shows each filter only on
collections whose products have values => effectively per-category filters.

Usage:
  python gen_facets.py --dry      # derive + print sample/distribution, NO writes
  python gen_facets.py --apply    # create defs + write metafields to ALL products
"""
import sys, os, json, re, time
sys.path.insert(0, os.path.dirname(__file__))
import theme_edit as te
import requests
from collections import Counter

tok = te.token(); STORE = os.environ['SHOPIFY_STORE']; BASE = f'https://{STORE}/admin/api/2024-10'
H = {'X-Shopify-Access-Token': tok}
GQL = f'{BASE}/graphql.json'

# ---- facet definitions ----
DEFS = [
    ('f_category', 'Category'),
    ('f_form',     'Format'),
    ('f_concern',  'Concern'),
    ('f_audience', 'For'),
    ('f_scent',    'Scent family'),
]

def kw(s, *words):
    return any(w in s for w in words)

def derive(title, ptype, tags):
    t = (title + ' ' + ptype).lower()
    clusters = [x.strip()[8:] for x in tags.split(',') if x.strip().startswith('cluster:')]
    demos = [x.strip()[5:] for x in tags.split(',') if x.strip().startswith('demo:')]
    cl = ' '.join(clusters)
    f = {}

    # ---- category (single primary) ----
    cat = None
    order = [
        ('Fragrance',           lambda: kw(t,'perfume','cologne','eau de','fragrance',' scent',' musk','parfum') or kw(cl,'fragrance','perfume')),
        ('Nail Care',           lambda: kw(t,'nail','acrylic','manicure','pedicure','cuticle') or kw(cl,'nail')),
        ('Oral Care',           lambda: kw(t,'tooth','teeth','dental','oral','floss','mouth','denture','interdental') or kw(cl,'oral','dental')),
        ('Makeup',              lambda: kw(t,'makeup','lipstick','mascara','eyeliner','eyeshadow','foundation','blush','lash','brow','brush','blender','sponge') or kw(cl,'makeup','cosmetics','lash-brow','eye-makeup')),
        ('Hair & Grooming',     lambda: kw(t,'hair','beard','shav','razor','clipper','trimmer','wig','comb','scalp') or kw(cl,'hair','beard','grooming','shaving')),
        ('Supplements & Wellness', lambda: kw(t,'supplement','gummies','gummy','capsule','vitamin','collagen','probiotic','magnesium','ashwagandha','tablet','powder') or kw(cl,'supplement','wellness','vitamin','gummies')),
        ('Massage & Recovery',  lambda: kw(t,'massage','massager','knee','back pain','joint','foot','posture','brace','heating pad','acupressure','cupping') or kw(cl,'massage','back-pain','knee','joint','foot-care','recovery')),
        ('Body Care',           lambda: kw(t,'body','cellulite','slimming','sculpt','bath','shower','scrub','tan','firming') or kw(cl,'body-care','body-sculpting','cellulite','bath','shower','slimming')),
        ("Men's Grooming",      lambda: kw(t,"men's",'mens ') or 'male' in demos and 'female' not in demos),
        ('Skincare',            lambda: kw(t,'skin','serum','cream','moistur','cleanser','acne','anti-aging','wrinkle','pore','mask','toner','spf','retinol') or kw(cl,'skincare','acne','anti-aging','mens-skincare')),
        ('Sleep & Snoring',     lambda: kw(t,'snore','snoring','nasal strip','sleep strip','anti-snore','apnea','mouthpiece','sleep mask','sleep aid','earplug')),
        ('Health & Wellness',   lambda: kw(t,'brace','support','posture','radiation','protective','emergency','blood pressure','thermometer','first aid','air purifier','air fresh','humidifier','monitor','glucose','nebulizer','anti-chafing','insole','wrist','ankle','elbow','compression')),
    ]
    for name, cond in order:
        if cond():
            cat = name; break
    # fallback: every product gets a coherent category bucket (no NONE)
    if not cat: cat = 'Health & Wellness'
    f['f_category'] = [cat]

    # ---- format (single primary, by priority) ----
    forms = [
        ('Gummies', ('gummies','gummy')), ('Capsules', ('capsule','softgel','caps ')),
        ('Tablets', ('tablet','pill ')), ('Powder', ('powder',)),
        ('Drops & Liquids', ('drops','tincture','liquid ')),
        ('Serum', ('serum','essence','ampoule')),
        ('Oil', (' oil','essential oil')),
        ('Cream & Lotion', ('cream','lotion','balm','butter','moisturizer')),
        ('Gel', (' gel',)), ('Spray & Mist', ('spray','mist')),
        ('Mask', (' mask','sheet mask')), ('Patches', ('patch','patches','strips')),
        ('Cleanser & Wash', ('cleanser','wash','soap','foam','shampoo')),
        ('Tools & Devices', ('massager','device','machine','roller','gua sha','trimmer','clipper','lamp','brush','tool','kit','tweezer','file','curler','mirror','meter','monitor')),
    ]
    for name, keys in forms:
        if kw(t, *keys): f['f_form'] = [name]; break

    # ---- concern (multi) ----
    concern = []
    rules = [
        ('Acne', ('acne','pimple','blemish','blackhead','breakout')),
        ('Anti-aging', ('anti-aging','anti aging','wrinkle','firming',' lift','collagen','age ')),
        ('Brightening', ('bright','whiten','dark spot','pigment','glow','radian','tone')),
        ('Hydration', ('hydrat','moistur',' dry ','nourish')),
        ('Pores', ('pore',)),
        ('Slimming & Contour', ('cellulite','slim','fat ','contour','sculpt','weight','firm')),
        ('Pain Relief', ('pain',' ache','sore','relief','arthritis','inflamm')),
        ('Sleep', ('sleep','insomnia','melatonin','night')),
        ('Stress & Calm', ('stress','anxiety','calm','relax','ashwagandha')),
        ('Hair Growth', ('hair growth','regrow','thinning','bald','grow hair')),
        ('Joint & Back', ('joint','knee','back ','spine','posture','lumbar')),
        ('Snoring', ('snore','snoring','apnea')),
        ('Detox', ('detox','cleanse','colon')),
        ('Energy & Focus', ('energy','focus','brain','memory','cognit')),
        ('Immunity', ('immune','immunity','vitamin c')),
        ('Teeth Whitening', ('whiten','teeth')),
    ]
    for name, keys in rules:
        if kw(t, *keys): concern.append(name)
    if concern: f['f_concern'] = concern[:3]

    # ---- audience ----
    aud = None
    if kw(t, "women",'ladies','female','her ') or ('female' in demos and 'male' not in demos): aud='Women'
    elif kw(t, "men's",'mens ',' men ','male','him ') or ('male' in demos and 'female' not in demos): aud="Men"
    elif 'unisex' in demos: aud='Unisex'
    if aud: f['f_audience'] = [aud]

    # ---- scent (fragrance only) ----
    if f.get('f_category') == ['Fragrance'] or kw(t,'perfume','cologne','eau de','fragrance'):
        sc = []
        for name, keys in [('Floral',('floral','rose','jasmine','flower','peony')),('Woody',('wood','sandal','oud','cedar','amber')),
                           ('Citrus',('citrus','lemon','bergamot','orange','lime','grapefruit')),('Fresh',('fresh','aqua','marine','clean','ocean','breeze')),
                           ('Sweet',('vanilla','sweet','caramel','gourmand','candy','sugar')),('Musk',('musk',)),('Oriental & Spice',('oriental','spice','cinnamon','clove'))]:
            if kw(t,*keys): sc.append(name)
        if sc: f['f_scent'] = sc[:3]
    return f


def fetch_all(fields='id,title,product_type,tags'):
    out=[]; url=f'{BASE}/products.json?limit=250&fields={fields}'
    while url:
        r=requests.get(url,headers=H,timeout=60); js=r.json()['products']; out+=js
        link=r.headers.get('Link','')
        m=re.search(r'<([^>]+)>; rel="next"',link)
        url=m.group(1) if m else None
        time.sleep(0.3)
    return out


def gql(q, v=None):
    r=requests.post(GQL,headers={**H,'Content-Type':'application/json'},json={'query':q,'variables':v or {}},timeout=40)
    return r.json()


def create_defs():
    for key,name in DEFS:
        q='''mutation($d:MetafieldDefinitionInput!){metafieldDefinitionCreate(definition:$d){createdDefinition{id} userErrors{code message}}}'''
        v={'d':{'name':name,'namespace':'custom','key':key,'type':'list.single_line_text_field','ownerType':'PRODUCT','access':{'storefront':'PUBLIC_READ'}}}
        res=gql(q,v); ue=res.get('data',{}).get('metafieldDefinitionCreate',{}).get('userErrors',[])
        print('  def',key,'->','OK' if not ue else ue)


def main():
    mode = '--apply' if '--apply' in sys.argv else '--dry'
    if mode=='--dry':
        prods=fetch_all()[:300]
        dist={k:Counter() for k,_ in DEFS}
        examples=[]
        covered=0
        for p in prods:
            f=derive(p.get('title',''),p.get('product_type',''),p.get('tags',''))
            if f: covered+=1
            for k in dist:
                for val in f.get(k,[]): dist[k][val]+=1
            if len(examples)<14 and len(f)>=2: examples.append((p['title'][:40],f))
        print(f'DRY: {covered}/{len(prods)} products got >=1 facet')
        for k,_ in DEFS:
            print(f'\\n{k}:'); [print('   ',v,n) for v,n in dist[k].most_common(12)]
        print('\\n--- EXAMPLES ---')
        for t,f in examples: print(' •',t,'=>',{k:v for k,v in f.items()})
    else:
        print('Creating metafield definitions...'); create_defs()
        print('Fetching all products...'); prods=fetch_all(); print(' got',len(prods))
        batch=[]; written=0; calls=0
        def flush():
            nonlocal batch,written,calls
            if not batch: return
            q='''mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){metafields{id} userErrors{field message}}}'''
            res=gql(q,{'m':batch}); ue=res.get('data',{}).get('metafieldsSet',{}).get('userErrors',[])
            if ue: print('  userErrors:',ue[:3])
            written+=len(batch)-len(ue); calls+=1; batch=[]; time.sleep(0.35)
        for p in prods:
            f=derive(p.get('title',''),p.get('product_type',''),p.get('tags',''))
            oid=f"gid://shopify/Product/{p['id']}"
            for k,vals in f.items():
                batch.append({'ownerId':oid,'namespace':'custom','key':k,'type':'list.single_line_text_field','value':json.dumps(vals)})
                if len(batch)>=25: flush()
            if calls and calls%50==0 and not batch: print(f'  ...{written} metafields written')
        flush()
        print(f'DONE: {written} facet metafields written across {len(prods)} products, {calls} calls')

if __name__=='__main__':
    main()
