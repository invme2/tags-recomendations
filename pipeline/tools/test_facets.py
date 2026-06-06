#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_facets.py — PROTOTYPE of the Designer `facets` extraction. For a handful
of diverse products: scrape EPROLO attribute table + read Shopify variants, then
ask DeepSeek to emit canonical, category-aware facet tags (type + facets[]).
Read-only demo (does NOT write anything). No Anthropic.
"""
from __future__ import annotations
import glob, json, os, re, sqlite3, sys
from pathlib import Path
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
APIGQL = f"https://{STORE}/admin/api/2024-10/graphql.json"
STATE = Path(os.environ.get("EPROLO_STATE_FILE", str(ROOT / "pipeline" / ".eprolo_state.json")))
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

KEYWORDS = ["screwdriver", "serum", "massager", "perfume", "nail lamp"]

EXTRACT_JS = r"""()=>{const out=[];
document.querySelectorAll('ul.product-property-list li, .content-con p, .content-con li').forEach(li=>{
  const t=li.querySelector('.propery-title'), d=li.querySelector('.propery-des');
  if(t&&d){ out.push([t.innerText, d.innerText]); return; }
  const tx=(li.innerText||'').trim();
  const m=tx.match(/^([A-Za-z][A-Za-z0-9 &\/_.()-]{1,28}):\s*(.+)$/);
  if(m && m[2].trim().length<=80 && m[2].indexOf(':')===-1) out.push([m[1], m[2]]);
});return out;}"""

SYSTEM = ("You are a product taxonomy engineer for an e-commerce search/filter system. "
          "You output ONE JSON object only, no prose.")

USER_TMPL = """Product title: {title}
Category tags: {tags}
Color/option variants: {variants}
Supplier spec attributes: {specs}

Emit canonical FACET tags for THIS product, using the natural filter dimensions of ITS category
(nail lamp -> wattage, uv/led tech, color; screwdriver set -> tip types, bit count, magnetic, case;
face serum -> skin type, key ingredient, form). Rules:
- "type": ONE canonical product-type slug (e.g. nail-lamp, screwdriver-set, face-serum).
- "facets": array of {{"key","value"}}; key = lowercase dimension (tech, power, color, tip, bits,
  ingredient, skin_type, form, feature ...); value = canonical short slug (uv, led, 48w, white,
  phillips, 25, retinol, oily, cream, cordless, magnetic, case ...).
- NORMALIZE values (Rose->pink, "48 Watt"->48w, "With case"->case, multi-value split into separate facets).
- CONTEXT-AWARE: never emit a feature the product lacks (e.g. "no UV needed" -> do NOT add tech:uv).
- Only category-relevant dimensions; skip noise (model number, certification, origin, keyword).
- 4-10 facets.
Output JSON: {{"type":"...","facets":[{{"key":"...","value":"..."}}]}}"""


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def find_products():
    """one product per keyword: (title, eprolo_url, gid)"""
    out, seen_run = {}, set()
    for p in sorted(glob.glob(str(ROOT / "runs" / "*" / ".db" / "pipeline.db"))):
        try:
            c = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True, timeout=8)
            rows = c.execute("SELECT name,eprolo_url,shopify_product_id FROM products WHERE shopify_product_id IS NOT NULL").fetchall()
            c.close()
        except Exception:
            continue
        for name, eu, gid in rows:
            nl = (name or "").lower()
            for kw in KEYWORDS:
                if kw in nl and kw not in out:
                    out[kw] = (name, eu, gid if str(gid).startswith("gid") else f"gid://shopify/Product/{gid}")
        if len(out) == len(KEYWORDS):
            break
    return list(out.values())


def ds_facets(title, tags, variants, specs):
    import time as _t
    user = USER_TMPL.format(title=title[:200], tags=", ".join(tags)[:200] or "(none)",
                            variants=", ".join(variants)[:200] or "(none)",
                            specs="; ".join(f"{k}: {v}" for k, v in specs)[:900] or "(none)")
    for a in range(4):
        try:
            r = requests.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer " + DS_KEY, "Content-Type": "application/json"},
                json={"model": DS_MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                      "max_tokens": 1400, "temperature": 0.4, "response_format": {"type": "json_object"}}, timeout=180).json()
            txt = (((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if txt:
                return json.loads(txt)
        except Exception:
            pass
        _t.sleep(1.5 + a)
    return {"type": "?", "facets": []}


def main():
    if not DS_KEY:
        sys.exit("no DEEPSEEK_API_KEY")
    tok = token()
    prods = find_products()
    print(f"found {len(prods)} test products\n")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=str(STATE))
        page = ctx.new_page()
        for name, eu, gid in prods:
            # variants from Shopify
            q = 'query($id:ID!){product(id:$id){tags options{name optionValues{name}}}}'
            pd = requests.post(APIGQL, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                               json={"query": q, "variables": {"id": gid}}, timeout=30).json().get("data", {}).get("product", {}) or {}
            tags = [t for t in (pd.get("tags") or []) if t.startswith("cluster:") or t.startswith("intent:")][:6]
            variants = []
            for o in (pd.get("options") or []):
                variants += [f"{o['name']}:{v['name']}" for v in o["optionValues"][:8]]
            # scrape attrs
            try:
                page.goto(eu, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector(".content-con, ul.product-property-list, .propery-title", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(700)
                raw = page.evaluate(EXTRACT_JS)
            except Exception:
                raw = []
            seen, specs = set(), []
            for lab, val in raw:
                lab = re.sub(r":$", "", (lab or "").strip()); val = (val or "").strip()
                k = (lab.lower(), val.lower())
                if lab and val and len(val) <= 60 and k not in seen:
                    seen.add(k); specs.append((lab, val))
            print("=" * 74)
            print(name[:64])
            print("  scrape attrs:", len(specs), "| variants:", variants[:4])
            try:
                fac = ds_facets(name, tags, variants, specs[:14])
                print("  TYPE:", fac.get("type"))
                print("  FACETS:", ", ".join(f"{f['key']}:{f['value']}" for f in fac.get("facets", []) if isinstance(f, dict)))
            except Exception as e:
                print("  ! deepseek:", str(e)[:80])
        ctx.close(); b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
