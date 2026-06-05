#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enrich_review_scenes.py — SURGICAL backfill: add product-specific
`review_scenes` (8 UGC scene ideas) to a product's stored Designer meta, WITHOUT
re-running the full Designer and WITHOUT touching Shopify. One cheap DeepSeek
JSON call per product. Writes meta.review_scenes into final_html.meta AND
stage2_json so the reviews builder / regen tool picks them up.

Idempotent: skips products that already have review_scenes (unless --force).

Usage:
  python tools/enrich_review_scenes.py <run_db> --ids 48,50
  python tools/enrich_review_scenes.py <run_db> --all [--limit N] [--force]
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

SYSTEM = ("You are a UGC photo art director for an e-commerce catalog. "
          "You output ONE JSON object only — no prose, no markdown fences.")

USER_TMPL = """Product: {title}
Category tags: {tags}
What it is / who it is for: {desc}

Produce 8 ideas for AUTHENTIC customer review photos (UGC, candid iPhone snapshots) for THIS product. Each scene MUST be where and how a REAL owner of THIS specific product would photograph it — derive the place and activity from the product's actual category and use. Grounding examples: a fishing rod -> on a riverbank holding the catch / casting at dawn / rod in the boat; a cordless drill -> mid-repair on a workbench / installing a shelf at home; a perfume -> at the vanity before a night out / in the handbag / gifted with a ribbon.

Rules: all 8 in DIFFERENT places/activities; real, lived-in, slightly cluttered; NO studio, NO white seamless, NO professional lighting; keep any packaging text intact.

Output JSON EXACTLY:
{{"review_scenes":[{{"title":"3-5 word name","scene":"one vivid sentence describing the candid photo","setting":"2-4 word place"}}, ... 8 total]}}"""


def ds_call(title, tags, desc, retries=3):
    user = USER_TMPL.format(title=title[:300], tags=", ".join(tags)[:300] or "(none)", desc=(desc or "")[:400])
    for a in range(retries):
        try:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer " + DS_KEY, "Content-Type": "application/json"},
                json={"model": DS_MODEL,
                      "messages": [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": user}],
                      "max_tokens": 2400, "temperature": 0.8,
                      "response_format": {"type": "json_object"}},
                timeout=180)
            j = r.json()
            if "choices" not in j:
                raise RuntimeError(str(j)[:160])
            txt = j["choices"][0]["message"]["content"].strip()
            try:
                scenes = (json.loads(txt).get("review_scenes")) or []
            except Exception:
                # salvage truncated JSON: pull out complete scene objects
                scenes = []
                for mobj in re.findall(r'\{[^{}]*?"title"[^{}]*?"scene"[^{}]*?\}', txt):
                    try:
                        scenes.append(json.loads(mobj))
                    except Exception:
                        pass
            clean = []
            for s in scenes:
                if not isinstance(s, dict):
                    continue
                t = (s.get("title") or "").strip()
                sc = (s.get("scene") or "").strip()
                st = (s.get("setting") or "").strip()
                if t and sc:
                    clean.append({"title": t[:60], "scene": sc[:300], "setting": st[:40]})
            if len(clean) >= 6:
                return clean[:8], (j.get("usage") or {})
        except Exception as e:
            if a == retries - 1:
                print(f"      ! deepseek failed: {str(e)[:120]}")
            time.sleep(1 + a)
    return None, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_db")
    ap.add_argument("--ids", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not DS_KEY:
        raise SystemExit("DEEPSEEK_API_KEY missing in .env")

    db = sqlite3.connect(args.run_db)
    db.row_factory = sqlite3.Row
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        rows = [db.execute("SELECT * FROM products WHERE id=?", (i,)).fetchone() for i in ids]
        rows = [r for r in rows if r]
    else:
        rows = db.execute("SELECT * FROM products WHERE status='done' OR final_html IS NOT NULL").fetchall()
    if args.limit:
        rows = rows[:args.limit]

    done = skip = fail = 0
    for r in rows:
        pid, name = r["id"], (r["name"] or "")
        try:
            fh = json.loads(r["final_html"] or "{}")
        except Exception:
            fh = {}
        meta = (fh.get("meta") if isinstance(fh, dict) else {}) or {}
        if not meta:
            skip += 1
            continue
        if meta.get("review_scenes") and not args.force:
            skip += 1
            continue
        tags = meta.get("product_tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tags]
        desc = meta.get("short_description") or (r["seo_description"] or "")
        scenes, usage = ds_call(name, [str(t) for t in tags], desc)
        if not scenes:
            fail += 1
            continue
        titles = ", ".join(s["title"] for s in scenes)
        print(f"  ✓ pid {pid} [{name[:34]}] -> {len(scenes)}: {titles[:90]}")
        if args.dry_run:
            done += 1
            continue
        meta["review_scenes"] = scenes
        fh["meta"] = meta
        try:
            s2 = json.loads(r["stage2_json"] or "{}")
        except Exception:
            s2 = {}
        s2["review_scenes"] = scenes
        db.execute("UPDATE products SET final_html=?, stage2_json=? WHERE id=?",
                   (json.dumps(fh, ensure_ascii=False), json.dumps(s2, ensure_ascii=False), pid))
        db.commit()
        done += 1
        time.sleep(0.2)
    db.close()
    print(f"\nenriched={done} skipped={skip} failed={fail} (db={args.run_db})")


if __name__ == "__main__":
    sys.exit(main())
