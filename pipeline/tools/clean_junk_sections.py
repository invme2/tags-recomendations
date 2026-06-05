#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_junk_sections.py — remove the junk sections the Designer leaked, from
(2) dynamic_schemas.json caches (so they stop being re-injected into prompts)
and (3) each product's stored final_html.sections in every run DB.

Junk = typo/variant keys shadowing real sections (timerline/comparison/
ingredients_explanation/idline) + photo-brief slots leaked as top-level keys
(inline_*, *_inline_photos, image_url/alt-only shapes) + placeholders
(variant_key, additional_keys).

DRY-RUN by default; --execute applies. Local only (no Shopify).
"""
from __future__ import annotations
import argparse, glob, json, re, sqlite3, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARD = {'hero','story','features','stats','reviews','faq','cta','palette','interlinks','how_to','specs','whats_included','ingredients','timeline','trust','compare','size_guide','care','dimensions','variants','gift_options','safety','protocol','target_profile','video_demo','compatibility','assembly','brand_story','lifestyle_gallery','nutrition_facts','clinical_evidence','app_showcase','room_placement','subscription_refill','sustainability','unboxing_journey','progress_milestones','mistake_warnings','use_scenarios','meta','photo_briefs','visual_style','review_scenes','source','designer_prompt','photo_pack'}
ALIAS = {'timerline': 'timeline', 'comparison': 'compare', 'ingredients_explanation': 'ingredients', 'idline': 'timeline'}
JUNK_DROP = {'variant_key', 'additional_keys'}


def is_pb(v):
    if isinstance(v, dict):
        ks = set(v.keys())
        return bool(ks) and ks <= {'image_url', 'image_alt', 'source_index', 'slot', 'concept', 'edit_instructions', 'id', 'caption', 'alt'}
    if isinstance(v, list) and v:
        return all(is_pb(x) for x in v)
    return False


def is_junk(k, v):
    return (k not in HARD) and (k in JUNK_DROP or bool(re.match(r'^inline[-_]', k)) or 'inline_photo' in k or k.endswith('_inline_photos') or is_pb(v))


def clean_sections(secs):
    """rename aliases to canonical (if absent) else drop; drop junk. -> dropped list"""
    dropped = []
    for bad, good in ALIAS.items():
        if bad in secs:
            if not secs.get(good):
                secs[good] = secs.pop(bad)
                dropped.append(bad + '->' + good)
            else:
                secs.pop(bad); dropped.append(bad + '(dup)')
    for k in [k for k in list(secs) if is_junk(k, secs.get(k))]:
        secs.pop(k); dropped.append(k)
    return dropped


def run_dbs():
    seen, out = set(), []
    for p in sorted(glob.glob(str(ROOT / "runs" / "*" / ".db" / "pipeline.db"))) + \
             sorted(glob.glob(str(ROOT / "runs" / "*" / "pipeline.db"))):
        run = Path(p).parts[-3] if Path(p).parts[-2] == ".db" else Path(p).parts[-2]
        if run in seen:
            continue
        seen.add(run); out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    # ── caches ──
    print(f"=== dynamic_schemas.json caches [{mode}] ===")
    cache_drops = Counter()
    for cf in glob.glob(str(ROOT / "runs" / "*" / ".db" / "dynamic_schemas.json")) + \
              glob.glob(str(ROOT / "runs" / "*" / "dynamic_schemas.json")):
        try:
            d = json.loads(Path(cf).read_text(encoding="utf-8"))
        except Exception:
            continue
        drop = [k for k in list(d) if k in ALIAS or is_junk(k, d.get(k))]
        if not drop:
            continue
        for k in drop:
            cache_drops[k] += 1
        rel = cf.split("runs")[-1]
        print(f"  {rel}: drop {drop}")
        if args.execute:
            for k in drop:
                d.pop(k, None)
            Path(cf).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  cache keys dropped (by key): {dict(cache_drops)}\n")

    # ── DB meta sections ──
    print(f"=== run-DB final_html.sections [{mode}] ===")
    total_prod = total_clean = 0
    key_drops = Counter()
    for db in run_dbs():
        try:
            c = sqlite3.connect(db, timeout=30)
            c.execute("PRAGMA busy_timeout=30000")
            rows = c.execute("SELECT id, final_html FROM products WHERE final_html IS NOT NULL").fetchall()
        except Exception as e:
            print(f"  ! {db}: {str(e)[:50]}"); continue
        n = 0
        for pid, fh in rows:
            try:
                obj = json.loads(fh or "{}")
            except Exception:
                continue
            secs = obj.get("sections") if isinstance(obj, dict) else None
            if not isinstance(secs, dict):
                continue
            total_prod += 1
            dropped = clean_sections(secs)
            if dropped:
                for d in dropped:
                    key_drops[d.split("->")[0].replace("(dup)", "")] += 1
                n += 1
                if args.execute:
                    obj["sections"] = secs
                    c.execute("UPDATE products SET final_html=? WHERE id=?",
                              (json.dumps(obj, ensure_ascii=False), pid))
        if args.execute:
            c.commit()
        c.close()
        if n:
            print(f"  {Path(db).parts[-3] if Path(db).parts[-2]=='.db' else Path(db).parts[-2]}: cleaned {n} products")
        total_clean += n
    print(f"\n  products with junk sections: {total_clean}/{total_prod}")
    print(f"  junk keys removed (by key): {dict(key_drops.most_common())}")
    if not args.execute:
        print("\nDRY-RUN — re-run with --execute to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
