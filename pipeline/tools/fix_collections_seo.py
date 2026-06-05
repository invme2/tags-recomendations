#!/usr/bin/env python3
"""fix_collections_seo.py — regenerate SUB-PAR collection SEO to senior level.

Reads the audit plan (collections_seo_audit.json) and, for each flagged
collection, uses Claude to produce a clean senior-SEO title + meta title + meta
description + description HTML: brand-free, correct lengths, on-topic to the
actual products, with a call-to-action. Clean collections are NOT touched.

DRY-RUN by default. --execute applies via collectionUpdate.
  python pipeline/tools/fix_collections_seo.py
  python pipeline/tools/fix_collections_seo.py --execute [--limit N] [--model ID]
"""
from __future__ import annotations
import argparse, json, os, re, time
from pathlib import Path
import requests
from dotenv import load_dotenv
import anthropic

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
PLAN = ROOT / "pipeline" / "runs" / "_logs" / "collections_seo_audit.json"
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYS = (
    "You are a senior e-commerce SEO copywriter for a US dropshipping store. "
    "Rewrite ONE Shopify collection's SEO. Rules:\n"
    "- title (H1): 45-65 chars, primary keyword first, compelling, Title Case, AT MOST one '|' separator.\n"
    "- seo_title (meta title): 50-60 chars, primary keyword first.\n"
    "- seo_description (meta desc): 140-158 chars, benefit + a call-to-action (Shop/Browse/Find ... today).\n"
    "- description_html: ONE <p>, 60-100 words, warm tone, mention the collection topic, soft CTA.\n"
    "- NEVER use brand names (the store does not sell branded goods) — no Real Techniques, Theragun, "
    "Olive & June, Dyson, etc. Describe products generically.\n"
    "- Stay strictly ON-TOPIC to the collection name + the example products. No off-topic categories.\n"
    "- Return ONLY compact JSON: {\"title\":\"\",\"seo_title\":\"\",\"seo_description\":\"\",\"description_html\":\"<p>...</p>\"}"
)


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    for a in range(6):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=60).json()
        if r.get("errors") and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in r["errors"]):
            time.sleep(2 + a); continue
        return r
    return r


def products_of(tok, handle):
    r = gql(tok, 'query($q:String!){collections(first:1,query:$q){nodes{products(first:6){nodes{title}}}}}',
            {"q": f"handle:{handle}"})
    n = (r.get("data") or {}).get("collections", {}).get("nodes") or []
    if not n:
        return []
    return [p["title"] for p in (n[0].get("products") or {}).get("nodes", [])]


def regen(model, name, cur_title, prods, issues):
    user = (f"Collection name: {name}\nCurrent title: {cur_title}\n"
            f"Example products in it: {', '.join(prods[:6]) if prods else '(none yet)'}\n"
            f"Audit flags to fix: {issues}\n")
    for a in range(3):
        try:
            r = client.messages.create(model=model, max_tokens=600,
                                       system=SYS, messages=[{"role": "user", "content": user}])
            t = r.content[0].text.strip()
            if t.startswith("```"):
                t = t.split("\n", 1)[-1].rsplit("\n", 1)[0]
            m = re.search(r'\{.*\}', t, re.S)
            return json.loads(m.group(0)) if m else None
        except Exception as e:
            if a == 2:
                print(f"     ! regen err: {str(e)[:70]}")
            time.sleep(2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="claude-opus-4-8")
    args = ap.parse_args()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if args.limit:
        plan = plan[:args.limit]
    tok = token()
    print(f"Коллекций к обработке: {len(plan)} | модель: {args.model} | "
          f"{'EXECUTE' if args.execute else 'DRY-RUN'}\n")
    done = 0
    BRAND = re.compile(r'\b(real techniques|theragun|olive and june|dyson|hoover|blick|procreate)\b', re.I)
    for p in plan:
        prods = products_of(tok, p["handle"])
        g = regen(args.model, p["title"], p["title"], prods, list(p["issues"].keys()))
        if not g:
            print(f"  ❌ {p['handle']}: regen не удался"); continue
        # guard: never ship a brand or oversized fields
        if BRAND.search(json.dumps(g)):
            print(f"  ⚠ {p['handle']}: бренд в регене — пропуск"); continue
        title = (g.get("title") or "")[:70]
        st = (g.get("seo_title") or "")[:60]
        sd = (g.get("seo_description") or "")[:165]
        dh = g.get("description_html") or ""
        print(f"  ▸ {p['handle']:<34} [{','.join(p['issues'])}]")
        print(f"      title: {title}")
        print(f"      meta:  {sd}")
        if args.execute:
            r = gql(tok, "mutation($i:CollectionInput!){collectionUpdate(input:$i){userErrors{message}}}",
                    {"i": {"id": p["id"], "title": title, "descriptionHtml": dh,
                           "seo": {"title": st, "description": sd}}})
            ue = (((r.get("data") or {}).get("collectionUpdate") or {}).get("userErrors")) or []
            print(f"      {'✅ обновлено' if not ue else '! '+str(ue)}")
            done += 0 if ue else 1
        time.sleep(0.5)
    print(f"\n{'Обновлено: '+str(done) if args.execute else 'DRY-RUN — запусти с --execute чтобы применить'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
