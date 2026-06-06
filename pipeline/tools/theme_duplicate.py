#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme_duplicate.py — create an UNPUBLISHED draft theme and upload every asset
from a local backup folder (a true duplicate to build/preview on safely).
Usage: python theme_duplicate.py <backup_dir> "<new theme name>"
"""
from __future__ import annotations
import sys, time, base64, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_edit as T
import requests

def main():
    src = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else "Wanelo Vibe (draft)"
    tok = T.token()
    H = {"X-Shopify-Access-Token": tok}
    # 1) create unpublished theme
    r = requests.post(f"{T.BASE}/themes.json", headers=H,
                      json={"theme": {"name": name, "role": "unpublished"}}, timeout=30)
    th = r.json().get("theme")
    if not th:
        print("CREATE FAIL", r.status_code, r.text[:300]); return 1
    tid = th["id"]
    print(f"created draft theme id={tid} name={name!r}")
    # 2) upload all files
    files = [p for p in src.rglob("*") if p.is_file()]
    ok = fail = 0
    for i, p in enumerate(files, 1):
        key = p.relative_to(src).as_posix()
        # decide text vs binary
        try:
            txt = p.read_text(encoding="utf-8")
            payload = {"asset": {"key": key, "value": txt}}
        except Exception:
            payload = {"asset": {"key": key, "attachment": base64.b64encode(p.read_bytes()).decode()}}
        for attempt in range(5):
            rr = requests.put(f"{T.BASE}/themes/{tid}/assets.json", headers=H, json=payload, timeout=60)
            if rr.status_code == 429:
                time.sleep(2); continue
            break
        if rr.status_code in (200, 201):
            ok += 1
        else:
            fail += 1
            if fail <= 8:
                print("  FAIL", key, rr.status_code, rr.text[:120])
        if i % 40 == 0:
            print(f"  {i}/{len(files)} (ok={ok} fail={fail})", flush=True)
        time.sleep(0.32)  # ~3/s under the 2/s sustained limit w/ bucket
    shop = T.BASE.split('/admin')[0].replace('https://', '')
    print(f"\nDuplicate done: theme {tid} | {ok} ok / {fail} fail of {len(files)}")
    print(f"PREVIEW: https://{shop}/?preview_theme_id={tid}")
    print(f"DRAFT_THEME_ID={tid}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
