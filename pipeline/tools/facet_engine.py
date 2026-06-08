# -*- coding: utf-8 -*-
"""Taxonomy-driven facet engine: keyword fast-path + LLM fallback for UNKNOWN categories.
Reads taxonomy/facets.json. Drop-in for gen_facets.derive(); adds confidence + unclassified flag
so new categories surface (and don't silently become fallback junk).

API:
  classify(title, ptype, tags) -> {category, concern[], format, audience[], scent[], confidence, source, unclassified, proposed_category}
  to_tags(result) -> ['Category:X','Concern:Y',...]
  derive(title, ptype, tags) -> gen_facets-compatible {f_category,f_concern,f_form,f_audience,f_scent}
"""
import os, json, re, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG_PATH = os.path.join(ROOT, 'taxonomy', 'facets.json')
CACHE_PATH = os.path.join(ROOT, 'taxonomy', '.facet_llm_cache.json')
_CFG = None; _CACHE = None

def cfg():
    global _CFG
    if _CFG is None: _CFG = json.load(open(CFG_PATH, encoding='utf-8'))
    return _CFG

def _cache():
    global _CACHE
    if _CACHE is None:
        try: _CACHE = json.load(open(CACHE_PATH, encoding='utf-8'))
        except Exception: _CACHE = {}
    return _CACHE

def _cache_save():
    try: json.dump(_CACHE, open(CACHE_PATH, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception: pass

_RE_CACHE = {}
def _compile(words):
    """Word-boundary matcher. Keyword = stem matched at a word start (\\b + stem),
    so 'tooth' matches toothbrush but NOT bluetooth, 'fat ' (trailing space) = whole word
    so it matches 'fat' but not 'fatigue'. Fixes latent substring false positives."""
    key = tuple(words)
    rx = _RE_CACHE.get(key)
    if rx is None:
        parts = []
        for w in words:
            core = re.escape(w.strip())
            if not core: continue
            p = r'\b' + core
            if w.endswith(' '): p += r'\b'
            parts.append(p)
        rx = re.compile('|'.join(parts)) if parts else None
        _RE_CACHE[key] = rx
    return rx

def _kw(text, words):
    rx = _compile(words)
    return bool(rx.search(text)) if rx else False

def _clusters(tags):
    return ' '.join(x.strip()[8:] for x in (tags or '').split(',') if x.strip().startswith('cluster:'))

def _demos(tags):
    return [x.strip()[5:] for x in (tags or '').split(',') if x.strip().startswith('demo:')]

def _striphtml(s):
    return re.sub(r'<[^>]+>', ' ', s or '')

def _api_key():
    api = os.environ.get('ANTHROPIC_API_KEY')
    if not api:
        try:
            for line in open(os.path.join(ROOT, '.env'), encoding='utf-8'):
                if line.startswith('ANTHROPIC_API_KEY='): api = line.split('=', 1)[1].strip()
        except Exception: pass
    return api

def _parse_cat(ans, cats):
    if ans.upper().startswith('NEW:'):
        return (None, ans.split(':', 1)[1].strip()[:40])
    for cat in cats:
        if cat.lower() == ans.lower() or cat.lower() in ans.lower():
            return (cat, None)
    return (None, None)

def _llm_category(title, ptype, desc='', use_llm=True):
    """Classify into an EXISTING category or 'NEW: <name>' from title+type+DESCRIPTION. Cached.
    The description is gold: EPROLO titles are often sparse, but the generated copy (written from
    the product photos via VISION) carries the real signal."""
    c = cfg()
    if not (use_llm and c.get('llm', {}).get('enable')): return (None, None)
    key = hashlib.sha1((title + '|' + (ptype or '') + '|' + (desc or '')[:200]).encode('utf-8', 'ignore')).hexdigest()
    cache = _cache()
    if key in cache:
        v = cache[key]; return (v.get('category'), v.get('proposed'))
    try:
        import anthropic
        api = _api_key()
        if not api: return (None, None)
        cats = c['category_order']
        prompt = ("Classify this e-commerce product into EXACTLY ONE category from the list. "
                  "If none fits well, reply 'NEW: <2-3 word category name>'.\n\nCATEGORIES:\n- " + "\n- ".join(cats) +
                  "\n\nPRODUCT: " + (title or '')[:200] + " | type: " + (ptype or '')[:60] +
                  "\n\nDESCRIPTION: " + (_striphtml(desc))[:500] +
                  "\n\nReply with ONLY the exact category name from the list, or 'NEW: ...'. No other text.")
        cl = anthropic.Anthropic(api_key=api)
        r = cl.messages.create(model=c['llm'].get('model', 'claude-haiku-4-5'), max_tokens=30,
                               messages=[{'role': 'user', 'content': prompt}])
        category, proposed = _parse_cat(r.content[0].text.strip(), cats)
        cache[key] = {'category': category, 'proposed': proposed}; _cache_save()
        return (category, proposed)
    except Exception:
        return (None, None)

def _vision_category(title, image_url):
    """Classify straight from the PRODUCT PHOTO. The last-resort signal for items where EPROLO gave
    almost no text but the image shows exactly what it is. Cached by image URL."""
    c = cfg()
    if not (c.get('llm', {}).get('enable') and image_url): return (None, None)
    key = 'vis:' + hashlib.sha1(image_url.encode('utf-8', 'ignore')).hexdigest()
    cache = _cache()
    if key in cache:
        v = cache[key]; return (v.get('category'), v.get('proposed'))
    try:
        import anthropic
        api = _api_key()
        if not api: return (None, None)
        cats = c['category_order']
        prompt = ("Look at this product photo and classify the product into EXACTLY ONE category from "
                  "the list. If none fits, reply 'NEW: <2-3 word category name>'.\n\nCATEGORIES:\n- " +
                  "\n- ".join(cats) + "\n\n(Title, may be vague: " + (title or '')[:120] +
                  ")\n\nReply with ONLY the exact category name, or 'NEW: ...'. No other text.")
        cl = anthropic.Anthropic(api_key=api)
        r = cl.messages.create(model=c['llm'].get('vision_model', c['llm'].get('model', 'claude-haiku-4-5')),
                               max_tokens=30, messages=[{'role': 'user', 'content': [
                                   {'type': 'image', 'source': {'type': 'url', 'url': image_url}},
                                   {'type': 'text', 'text': prompt}]}])
        category, proposed = _parse_cat(r.content[0].text.strip(), cats)
        cache[key] = {'category': category, 'proposed': proposed}; _cache_save()
        return (category, proposed)
    except Exception:
        return (None, None)

def classify(title, ptype, tags, desc='', image_url=None, use_llm=True, use_vision=False, vision=None):
    c = cfg()
    dtxt = _striphtml(desc)[:800]
    t = ((title or '') + ' ' + (ptype or '') + ' ' + dtxt).lower()
    cl = _clusters(tags); demos = _demos(tags)
    res = {'category': None, 'concern': [], 'format': None, 'audience': [], 'scent': [],
           'material': [], 'color': [], 'size': [],
           'confidence': 0.0, 'source': 'keyword', 'unclassified': False, 'proposed_category': None}

    # ---- category (keyword fast-path over title + type + DESCRIPTION) ----
    for name in c['category_order']:
        cd = c['categories'][name]
        if _kw(t, cd['keywords']) or (cd.get('cluster_keywords') and _kw(cl, cd['cluster_keywords'])):
            res['category'] = name; res['confidence'] = 0.9; break
    if res['category'] is None:
        # text LLM fallback (title + type + description)
        cat, proposed = _llm_category(title, ptype, dtxt, use_llm)
        # vision fallback: read the photo when text still failed (EPROLO thin, photo rich)
        if not cat and use_vision and image_url:
            vcat, vprop = _vision_category(title, image_url)
            if vcat: cat = vcat; proposed = None; res['source'] = 'vision'
            elif vprop and not proposed: proposed = vprop
        if cat:
            res['category'] = cat
            if res['source'] != 'vision': res['source'] = 'llm'
            res['confidence'] = 0.7
        else:
            res['category'] = c['fallback_category']; res['unclassified'] = True
            res['proposed_category'] = proposed; res['confidence'] = 0.2; res['source'] = 'fallback'

    P = c['params']
    # ---- format (single, priority) ----
    for name, keys in P['Format']['priority']:
        if _kw(t, keys): res['format'] = name; break
    # ---- concern (multi) ----
    con = [name for name, keys in P['Concern']['values'].items() if _kw(t, keys)]
    res['concern'] = con[:P['Concern'].get('max', 3)]
    # ---- audience ----
    Fv = P['For']['values']; dm = P['For'].get('demo_map', {})
    aud = None
    if _kw(t, Fv['Women']) or ('female' in demos and 'male' not in demos): aud = 'Women'
    elif _kw(t, Fv['Men']) or ('male' in demos and 'female' not in demos): aud = 'Men'
    elif 'unisex' in demos: aud = 'Unisex'
    if aud: res['audience'] = [aud]
    # ---- scent (category-gated) ----
    Sg = P['Scent'].get('category_gate')
    if res['category'] == Sg or _kw(t, ['perfume', 'cologne', 'eau de', 'fragrance']):
        sc = [name for name, keys in P['Scent']['values'].items() if _kw(t, keys)]
        res['scent'] = sc[:P['Scent'].get('max', 3)]
    # ---- material (keyword; low ambiguity) ----
    Mv = (P.get('Material') or {}).get('values', {})
    if Mv:
        res['material'] = [n for n, keys in Mv.items() if _kw(t, keys)][:(P['Material'].get('max', 2))]
    # ---- vision dict enrichment: Color / Material / Size come precisely from the photo analysis ----
    if vision:
        s = vision.get('sensory', {}) or {}; ph = vision.get('physical', {}) or {}
        cn = s.get('color_names') or []
        if cn and not res['color']: res['color'] = [str(x).strip().title() for x in cn if x][:3]
        if s.get('material') and not res['material']: res['material'] = [str(s['material']).strip().title()]
        if ph.get('size_impression') and not res['size']: res['size'] = [str(ph['size_impression']).strip().title()]
    return res

def to_tags(res):
    out = []
    if res.get('category'): out.append('Category:' + res['category'])
    for x in res.get('concern', []): out.append('Concern:' + x)
    if res.get('format'): out.append('Format:' + res['format'])
    for x in res.get('audience', []): out.append('For:' + x)
    for x in res.get('scent', []): out.append('Scent:' + x)
    for x in res.get('material', []): out.append('Material:' + x)
    for x in res.get('color', []): out.append('Color:' + x)
    for x in res.get('size', []): out.append('Size:' + x)
    return out

def derive(title, ptype, tags, desc='', image_url=None, use_llm=False, use_vision=False, vision=None):
    """gen_facets-compatible output (drop-in). use_llm=False by default so catalog SWEEPS
    are cheap + deterministic; onboarding/health paths pass use_llm=True (and optionally
    use_vision=True + image_url) to rescue unknowns from description / product photo."""
    r = classify(title, ptype, tags, desc=desc, image_url=image_url, use_llm=use_llm, use_vision=use_vision, vision=vision)
    f = {}
    if r['category']: f['f_category'] = [r['category']]
    if r['concern']: f['f_concern'] = r['concern']
    if r['format']: f['f_form'] = [r['format']]
    if r['audience']: f['f_audience'] = r['audience']
    if r['scent']: f['f_scent'] = r['scent']
    if r['material']: f['f_material'] = r['material']
    if r['color']: f['f_color'] = r['color']
    if r['size']: f['f_size'] = r['size']
    return f

def derive_keyword(title, ptype, tags, desc=''):
    """Deterministic keyword-only derive (no LLM). Now also scans the description text."""
    return derive(title, ptype, tags, desc=desc, use_llm=False)

if __name__ == '__main__':
    import sys
    samples = [("14-in-1 Magnesium Gummies Ashwagandha", "supplement", "cluster:sleep,demo:adult"),
               ("Wireless Noise-Cancelling Headphones Bluetooth 5.3", "Electronics", ""),
               ("Orthopedic Memory Foam Dog Bed Washable", "Pet", ""),
               ("Acne Spot Serum 2% Salicylic", "skincare", "cluster:acne,demo:female")]
    for ti, pt, tg in samples:
        r = classify(ti, pt, tg, use_llm=('--llm' in sys.argv))
        print('%-46s -> cat=%-22s src=%s uncls=%s proposed=%s  tags=%s' % (
            ti[:46], r['category'], r['source'], r['unclassified'], r['proposed_category'], to_tags(r)))
