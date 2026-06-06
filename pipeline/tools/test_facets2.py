#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_facets2.py — robust facet-extraction demo, NO playwright. Uses data
already in Shopify (title, tags, variants, custom.specs metafield) + DeepSeek to
emit canonical category-aware facet tags. Read-only.
"""
from __future__ import annotations
import json, os, sys, time
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
APIGQL = f"https://{STORE}/admin/api/2024-10/graphql.json"
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# diverse, hand-picked so each is a different category (avoids beauty-only)
SEARCHES = ["uv nail lamp", "screwdriver", "anti-aging serum", "foot massager"]
LOG = ROOT / "runs" / ".facet_test.log"


def out(msg):
    print(msg, flush=True)
    try:
        open(LOG, "a", encoding="utf-8").write(msg + "\n")
    except Exception:
        pass

SYSTEM = ("You are a product taxonomy engineer for an e-commerce search/filter system. "
          "You output ONE JSON object only, no prose.")
USER_TMPL = """Product title: {title}
Category tags: {tags}
Color/option variants: {variants}
Supplier spec attributes: {specs}

Emit canonical FACET tags for THIS product, using the natural filter dimensions of ITS category
(nail lamp -> wattage, uv/led tech, color; screwdriver set -> tip types, bit count, magnetic, case;
face serum -> skin type, key ingredient, form). Rules:
- "type": ONE canonical product-type slug (nail-lamp, screwdriver-set, face-serum ...).
- "facets": array of {{"key","value"}}; key=lowercase dimension (tech,power,color,tip,bits,ingredient,skin_type,form,feature...);
  value=canonical short slug (uv,led,48w,white,phillips,25,retinol,oily,cream,cordless,magnetic,case...).
- NORMALIZE (Rose->pink, "48 Watt"->48w, "With case"->case; split multi-value).
- CONTEXT-AWARE: never emit a feature the product lacks ("no UV needed" -> NOT tech:uv).
- Only category-relevant dimensions; skip noise (model number, certification, origin, keyword).
- 4-10 facets.
Output JSON: {{"type":"...","facets":[{{"key":"...","value":"..."}}]}}"""


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(APIGQL, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=40).json()


def ds(title, tags, variants, specs):
    user = USER_TMPL.format(title=title[:200], tags=", ".join(tags)[:200] or "(none)",
                            variants=", ".join(variants)[:200] or "(none)",
                            specs="; ".join(f"{k}: {v}" for k, v in specs)[:900] or "(none)")
    for a in range(4):
        try:
            r = requests.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer " + DS_KEY, "Content-Type": "application/json"},
                json={"model": DS_MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                      "max_tokens": 4000, "temperature": 0.4, "response_format": {"type": "json_object"}}, timeout=120).json()
            txt = (((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if txt:
                return json.loads(txt)
        except Exception:
            pass
        time.sleep(1.5 + a)
    return {"type": "?", "facets": []}


def main():
    if not DS_KEY:
        sys.exit("no DEEPSEEK_API_KEY")
    tok = token()
    Q = ("query($q:String!){products(first:1,query:$q){nodes{id title tags "
         "options{name optionValues{name}} "
         "specs:metafield(namespace:\"custom\",key:\"specs\"){value}}}}")
    for s in SEARCHES:
        nodes = (((gql(tok, Q, {"q": f"title:*{s}*"}).get("data") or {}).get("products") or {}).get("nodes")) or []
        if not nodes:
            print(f"\n(no product for '{s}')"); continue
        n = nodes[0]
        tags = [t for t in (n.get("tags") or []) if t.startswith("cluster:") or t.startswith("intent:")][:6]
        variants = []
        for o in (n.get("options") or []):
            if o["name"].lower() != "title":
                variants += [f"{o['name']}:{v['name']}" for v in o["optionValues"][:8]]
        specs = []
        mv = (n.get("specs") or {}).get("value")
        if mv:
            try:
                for it in (json.loads(mv).get("items") or []):
                    specs.append((it["label"], it["value"]))
            except Exception:
                pass
        print("\n" + "=" * 74)
        out(n["title"][:64])
        out("  specs=%d variants=%s"%(len(specs),variants[:4]))
        fac = ds(n["title"], tags, variants, specs[:14])
        out("  TYPE: "+str(fac.get("type")))
        out("  FACETS: "+", ".join("%s:%s"%(f.get("key"),f.get("value")) for f in fac.get("facets",[]) if isinstance(f,dict)))
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
