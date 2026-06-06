#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrape_specs_to_metafield.py — give EVERY live product a factual marketplace
spec table by re-scraping EPROLO's attribute list (ul.product-property-list >
li > span.propery-title / span.propery-des) and pushing it to custom.specs.
NO Anthropic — pure scrape -> metafield. Renders via existing wanelo-specs.liquid.

Idempotent-ish: --skip-existing leaves products that already have a factual
(scraped) specs table. DRY-RUN by default.
"""
from __future__ import annotations
import argparse, glob, json, os, re, sqlite3, sys, time
from pathlib import Path
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
STATE = Path(os.environ.get("EPROLO_STATE_FILE", str(ROOT / "pipeline" / ".eprolo_state.json")))

# labels we don't want on the storefront table
DROP_LABELS = {"keyword", "keyword 1", "keyword 2", "keyword 3", "model number",
               "origin", "place of origin", "is customized", "after-sale service",
               "cn;", "certification"}
MAX_ROWS = 14


def norm(u):
    u = (u or "").strip().lower().rstrip("/")
    u = re.sub(r"\?.*$", "", u)
    return re.sub(r"(--\d+)-\d+$", r"\1", u)


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=40).json()


def clean_pairs(raw):
    seen, out = set(), []
    for label, value in raw:
        lab = re.sub(r":$", "", (label or "").strip()).strip()
        val = (value or "").strip()
        if not lab or not val or len(val) > 120:
            continue
        if lab.lower() in DROP_LABELS or lab.lower().startswith("keyword"):
            continue
        lab = lab[:1].upper() + lab[1:]  # cap first letter
        key = (lab.lower(), val.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": lab, "value": val})
        if len(out) >= MAX_ROWS:
            break
    return out


EXTRACT_JS = r"""()=>{const out=[];
// Format 1: structured property list (span.propery-title / .propery-des)
document.querySelectorAll('ul.product-property-list li, .content-con p, .content-con li').forEach(li=>{
  const t=li.querySelector('.propery-title'), d=li.querySelector('.propery-des');
  if(t&&d){ out.push([t.innerText, d.innerText]); return; }
  // Format 2: plain "<p>Label: Value</p>" attribute paragraphs (beauty etc.)
  const tx=(li.innerText||'').replace(/ /g,' ').trim();
  const m=tx.match(/^([A-Za-z][A-Za-z0-9 &\/_.()-]{1,28}):\s*(.+)$/);
  if(m && m[2].trim().length<=80 && m[2].indexOf(':')===-1) out.push([m[1], m[2]]);
});return out;}"""


def product_list(tok, limit, ids):
    """(gid, eprolo_url, has_factual_specs) for unique live products."""
    seen, items = set(), []
    for p in sorted(glob.glob(str(ROOT / "runs" / "*" / ".db" / "pipeline.db"))) + \
             sorted(glob.glob(str(ROOT / "runs" / "*" / "pipeline.db"))):
        run = Path(p).parts[-3] if Path(p).parts[-2] == ".db" else Path(p).parts[-2]
        if run in seen:
            continue
        seen.add(run)
        try:
            c = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True, timeout=8)
            rows = c.execute("SELECT eprolo_url, shopify_product_id, final_html FROM products "
                             "WHERE shopify_product_id IS NOT NULL AND eprolo_url IS NOT NULL").fetchall()
            c.close()
        except Exception:
            continue
        for eu, gid, fh in rows:
            k = norm(eu)
            if k in {i[3] for i in items}:
                continue
            try:
                sp = (json.loads(fh or "{}").get("sections") or {}).get("specs") or {}
            except Exception:
                sp = {}
            has_factual = bool((sp.get("head") or {}).get("kicker") == "SPECIFICATIONS")
            items.append((gid if str(gid).startswith("gid") else f"gid://shopify/Product/{gid}", eu, has_factual, k))
    if ids:
        items = [i for i in items if i[0].split("/")[-1] in ids]
    if limit:
        items = items[:limit]
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    if not STATE.exists():
        sys.exit(f"no storage_state at {STATE}")
    tok = token()
    ids = set(x for x in args.ids.split(",") if x.strip())
    plist = product_list(tok, args.limit, ids)
    print(f"products: {len(plist)} | {'EXECUTE' if args.execute else 'DRY-RUN'}")

    done = empty = skip = 0
    _logf = ROOT / "runs" / ".specs_backfill.log"
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=str(STATE))
        page = ctx.new_page()
        for _i, (gid, eu, has_factual, _) in enumerate(plist, 1):
            if _i % 50 == 0:
                msg = time.strftime("%H:%M:%S ") + f"progress {_i}/{len(plist)} pushed={done} empty={empty} skip={skip}"
                print(msg, flush=True)
                try:
                    open(_logf, "a", encoding="utf-8").write(msg + "\n")
                except Exception:
                    pass
            if args.skip_existing and has_factual:
                skip += 1
                continue
            try:
                page.goto(eu, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector(".content-con, ul.product-property-list, .propery-title", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(700)
                raw = page.evaluate(EXTRACT_JS)
            except Exception as e:
                print(f"  ! {gid.split('/')[-1]} scrape: {str(e)[:50]}")
                continue
            items = clean_pairs(raw)
            if len(items) < 3:
                empty += 1
                print(f"  - {gid.split('/')[-1]}: only {len(items)} attrs ({eu.split('/')[-1][:30]})")
                continue
            print(f"  ✓ {gid.split('/')[-1]}: {len(items)} attrs -> {[i['label'] for i in items[:6]]}")
            done += 1
            if not args.execute:
                continue
            specs = {"head": {"kicker": "SPECIFICATIONS", "h2": "Specifications", "desc": ""}, "items": items}
            gql(tok, """mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){userErrors{message}}}""",
                {"m": [{"ownerId": gid, "namespace": "custom", "key": "specs", "type": "json",
                        "value": json.dumps(specs, ensure_ascii=False)}]})
            time.sleep(0.15)
        ctx.close(); b.close()
    print(f"\nscraped+pushed={done} | too-few-attrs={empty} | skipped={skip}")
    if not args.execute:
        print("DRY-RUN — add --execute to push to custom.specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
