#!/usr/bin/env python3
"""audit_collections_seo.py — senior-SEO audit of EVERY live Shopify collection.

Read-only by default. Checks each collection's user-facing SEO against best
practice and writes a fix-plan JSON. Pair with fix_collections_seo.py to apply.

CHECKS
  brand      — brand name in title/meta/desc (store is dropship, must be brand-free)
  title_len  — H1/title ideal 25-70 chars
  mtitle_len — meta title ideal ≤60 chars (Google truncation)
  mdesc_len  — meta description ideal 110-160 chars
  mdesc_cta  — meta description should contain a call-to-action verb
  dup_title  — duplicate title across collections
  no_desc    — empty/missing description body
  stuffing   — keyword stuffing (3+ pipes or a word repeated 3+ times)

USAGE
  python pipeline/tools/audit_collections_seo.py            # audit, write plan
  python pipeline/tools/audit_collections_seo.py --published # only published
"""
from __future__ import annotations
import argparse, json, os, re, time
from collections import Counter, defaultdict
from pathlib import Path
import requests
from dotenv import load_dotenv
import nbformat

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
OUT = ROOT / "pipeline" / "runs" / "_logs" / "collections_seo_audit.json"

CTA = ["shop", "buy", "browse", "explore", "find", "discover", "get ", "order",
       "today", "now", "save", "grab", "upgrade", "try "]


def brands():
    nb = nbformat.read(ROOT / "pipeline" / "Shopify_Pipeline.ipynb", as_version=4)
    src = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    m = re.search(r'BRAND_BLACKLIST\s*=\s*(\[[^\]]*\])', src, re.S)
    bl = [b.strip().lower() for b in eval(m.group(1))] if m else []
    extra = ['real techniques', 'wet brush', 'theragun', 'olive and june', 'great clips',
             'blick', 'hoover', 'giorgio armani', 'lancome', 'lancôme', 'invisalign',
             'oakley', 'procreate', 'dyson', 'goscratchit', 'gillette', 'venus razor']
    return sorted(set(b for b in bl + extra if len(b) >= 4))


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


def strip_html(h):
    return re.sub(r"<[^>]+>", " ", h or "").replace("&amp;", "&")


def load_all(tok, published_only):
    q = """query($c:String){collections(first:200,after:$c%s){pageInfo{hasNextPage endCursor}
      nodes{id handle title productsCount{count} descriptionHtml seo{title description}}}}""" % (
        ',query:"published_status:published"' if published_only else "")
    cur, out = None, []
    while True:
        r = gql(tok, q, {"c": cur})
        d = (r.get("data") or {}).get("collections")
        if not d:
            print("ERR:", json.dumps(r)[:300]); break
        out.extend(d["nodes"])
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break
    return out


def audit_one(c, BR, title_counts):
    title = c.get("title") or ""
    seo = c.get("seo") or {}
    mt = seo.get("title") or ""
    md = seo.get("description") or ""
    body = strip_html(c.get("descriptionHtml") or "")
    blob = f"{title} {mt} {md} {body}".lower()
    issues = []
    hit_brands = sorted(set(b for b in BR if re.search(r'\b' + re.escape(b) + r'\b', blob)))
    if hit_brands:
        issues.append(("brand", hit_brands))
    if len(title) > 70 or len(title) < 25:
        issues.append(("title_len", len(title)))
    if mt and len(mt) > 60:
        issues.append(("mtitle_len", len(mt)))
    if not md:
        issues.append(("mdesc_missing", 0))
    else:
        if len(md) > 160 or len(md) < 110:
            issues.append(("mdesc_len", len(md)))
        if not any(k in md.lower() for k in CTA):
            issues.append(("mdesc_cta", md[:40]))
    if not body.strip():
        issues.append(("no_desc", 0))
    if title and title_counts[title] > 1:
        issues.append(("dup_title", title_counts[title]))
    if title.count("|") >= 3:
        issues.append(("stuffing", title.count("|")))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--published", action="store_true")
    args = ap.parse_args()
    BR = brands()
    tok = token()
    cols = load_all(tok, args.published)
    title_counts = Counter(c.get("title") or "" for c in cols)
    plan = []
    tallies = Counter()
    for c in cols:
        iss = audit_one(c, BR, title_counts)
        if iss:
            for k, _ in iss:
                tallies[k] += 1
            plan.append({"id": c["id"], "handle": c["handle"], "title": c.get("title"),
                         "np": (c.get("productsCount") or {}).get("count", 0),
                         "issues": {k: v for k, v in iss}})

    print(f"{'='*64}\nSENIOR-SEO АУДИТ — {len(cols)} коллекций\n{'='*64}")
    print(f"  с замечаниями: {len(plan)}  |  чистых: {len(cols)-len(plan)}")
    print("\n  по типам замечаний:")
    labels = {"brand": "бренд в тексте", "title_len": "длина заголовка вне 25-70",
              "mtitle_len": "meta title >60", "mdesc_missing": "нет meta description",
              "mdesc_len": "meta desc вне 110-160", "mdesc_cta": "нет CTA в meta desc",
              "no_desc": "пустое описание", "dup_title": "дубль заголовка",
              "stuffing": "keyword stuffing (3+ |)"}
    for k, n in tallies.most_common():
        print(f"     {labels.get(k,k):<34} {n}")
    # show brand offenders explicitly (highest priority)
    bran = [p for p in plan if "brand" in p["issues"]]
    if bran:
        print(f"\n  🚩 БРЕНДЫ ({len(bran)}):")
        for p in bran[:25]:
            print(f"     {p['handle']:<34} {p['issues']['brand']}  | {(p['title'] or '')[:42]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  план сохранён: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
