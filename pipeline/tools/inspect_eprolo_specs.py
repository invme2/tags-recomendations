#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect_eprolo_specs.py — load ONE EPROLO product page (authed) and dump the
DOM structure of its attribute / specification table, so we can find the real
CSS selectors (the current scrape selectors miss it -> specs empty for 99.7%).
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
DEFAULT_STATE = ROOT / "pipeline" / ".eprolo_state.json"
STATE = Path(os.environ.get("EPROLO_STATE_FILE", str(DEFAULT_STATE)))

ATTR_KEYS = ["material", "model number", "quantity", "color", "function", "brand",
             "origin", "size", "application", "weight", "type", "feature", "style",
             "specification", "package", "voltage", "power", "capacity"]


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://eprolo.com/app/product/rohwxy-48w-uv-lamp-gel-led-nail-lamp-high-power-for-nails-all-gel-polish-nail-dryer-sensor-sun-led-light-nail-art-manicure-tools"
    if not STATE.exists():
        sys.exit(f"no storage_state at {STATE}")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=str(STATE))
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print("goto warn:", str(e)[:80])
        page.wait_for_timeout(2500)
        print("URL:", page.url)
        print("TITLE:", (page.title() or "")[:80])

        # 1) JS scan: find smallest elements whose text contains >=3 attribute keys,
        # report tag+class + a sample of their row structure.
        js = """
        () => {
          const KEYS = %s;
          const out = [];
          const all = document.querySelectorAll('div,section,ul,table,dl');
          for (const el of all) {
            const t = (el.innerText||'').toLowerCase();
            let hits = 0; for (const k of KEYS) if (t.includes(k)) hits++;
            if (hits >= 3 && (el.innerText||'').length < 3000) {
              // prefer the smallest container (fewest children chars)
              out.push({
                tag: el.tagName.toLowerCase(),
                cls: el.className && el.className.toString ? el.className.toString().slice(0,80) : '',
                hits, len: (el.innerText||'').length,
                html: el.outerHTML.slice(0, 900),
                kids: Array.from(el.children).slice(0,3).map(c => c.tagName.toLowerCase()+'.'+(c.className&&c.className.toString?c.className.toString().slice(0,40):''))
              });
            }
          }
          out.sort((a,b)=>a.len-b.len);
          return out.slice(0,4);
        }
        """ % json.dumps(ATTR_KEYS)
        cands = page.evaluate(js)
        print(f"\n=== candidate attribute containers: {len(cands)} ===")
        for c in cands:
            print(f"\n--- <{c['tag']} class='{c['cls']}'> hits={c['hits']} len={c['len']} children={c['kids']}")
            print(c["html"][:900])
        ctx.close(); b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
