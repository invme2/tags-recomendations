#!/usr/bin/env python3
"""fix_meta_descriptions.py — regenerate EMPTY meta descriptions from product content.

Builds a 140-155 char meta description from the product's own hero.lead / hero.h1
(+ a feature benefit fallback), strips HTML, truncates at a word boundary.
Robust: retries on Shopify throttle / empty responses with backoff.
"""
from __future__ import annotations
import os, re, json, time, sys
import requests
from dotenv import load_dotenv

load_dotenv('.env', override=True)
STORE = os.environ['SHOPIFY_STORE']
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


def token():
    r = requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ['SHOPIFY_CLIENT_ID'],
              "client_secret": os.environ['SHOPIFY_CLIENT_SECRET'],
              "grant_type": "client_credentials"}, timeout=15)
    return r.json()["access_token"]


TOK = token()


def gql(q, v=None, tries=5):
    for a in range(tries):
        try:
            r = requests.post(API, headers={"X-Shopify-Access-Token": TOK,
                                            "Content-Type": "application/json"},
                              json={"query": q, "variables": v or {}}, timeout=60)
            if r.status_code == 200 and r.text.strip():
                j = r.json()
                if "errors" in j and any("throttl" in str(e).lower() for e in j["errors"]):
                    time.sleep(2 * (a + 1)); continue
                return j
            time.sleep(1.5 * (a + 1))
        except Exception:
            time.sleep(1.5 * (a + 1))
    raise RuntimeError("gql failed after retries")


def clean(s):
    return re.sub(r'<[^>]+>', '', s or '').replace('\n', ' ').replace('  ', ' ').strip()


def make_meta(title, hero, feats):
    lead = clean(hero.get('lead')); h1 = clean(hero.get('h1'))
    desc = lead if len(lead) >= 70 else ((h1 + '. ' + lead).strip(' .') if h1 else lead)
    if len(desc) < 90:
        items = feats.get('items') or []
        if items:
            f0 = clean(items[0].get('p') or items[0].get('h4') or '')
            desc = (desc + ' ' + f0).strip()
    if len(desc) < 90:
        desc = clean(title) + '. Premium quality with visible results — see why shoppers love it.'
    if len(desc) > 155:
        desc = desc[:152].rsplit(' ', 1)[0].rstrip('.,;: ') + '...'
    return desc


FETCH = """query($c:String){products(first:150,after:$c){pageInfo{hasNextPage endCursor}
  nodes{id title seo{description}
    hero:metafield(namespace:"custom",key:"hero"){value}
    features:metafield(namespace:"custom",key:"features"){value}}}}"""

MUT = """mutation($id:ID!,$d:String!){productUpdate(input:{id:$id,seo:{description:$d}}){
  product{id} userErrors{message}}}"""


def main():
    allp, c = [], None
    while True:
        d = gql(FETCH, {"c": c}); b = d["data"]["products"]; allp += b["nodes"]
        if not b["pageInfo"]["hasNextPage"]: break
        c = b["pageInfo"]["endCursor"]
    print(f"Всего товаров: {len(allp)}")

    todo = []
    for p in allp:
        if not ((p.get("seo") or {}).get("description") or ""):
            hv = (p.get("hero") or {}).get("value") or "{}"
            fv = (p.get("features") or {}).get("value") or "{}"
            try: hero = json.loads(hv) if hv not in ("null", "") else {}
            except: hero = {}
            try: feats = json.loads(fv) if fv not in ("null", "") else {}
            except: feats = {}
            todo.append((p["id"], make_meta(p["title"] or "", hero if isinstance(hero, dict) else {},
                                            feats if isinstance(feats, dict) else {})))
    print(f"Пустых мета-описаний к регенерации: {len(todo)}")

    ok = err = 0
    for i, (pid, meta) in enumerate(todo, 1):
        try:
            r = gql(MUT, {"id": pid, "d": meta})
            ue = (r.get("data", {}).get("productUpdate", {}) or {}).get("userErrors", [])
            if ue: err += 1; print("  !", ue)
            else: ok += 1
        except Exception as e:
            err += 1; print("  ! err", str(e)[:60])
        if i % 50 == 0: print(f"  …{i}/{len(todo)} (ok={ok})")
        time.sleep(0.25)
    print(f"\nГотово: регенерировано {ok}, ошибок {err}")


if __name__ == "__main__":
    sys.exit(main())
