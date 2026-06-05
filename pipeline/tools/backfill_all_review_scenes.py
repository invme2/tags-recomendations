#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_all_review_scenes.py — run enrich_review_scenes across the WHOLE
catalog (all run DBs). Dedups by normalized eprolo_url so each unique LIVE
product costs exactly ONE DeepSeek call; the resulting scenes are written to
every DB row sharing that url (so any future pack-regen, from any run DB, has
them). Resumable + idempotent: rows that already have review_scenes are skipped.

Does NOT touch Shopify.

Usage:
  python tools/backfill_all_review_scenes.py [--limit N] [--workers 10] [--dry-run]
"""
from __future__ import annotations
import argparse, glob, json, re, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_review_scenes import ds_call, DS_KEY  # reuse the exact call

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "runs" / ".review_scenes_backfill.log"


def norm(u):
    u = (u or "").strip().lower().rstrip("/")
    u = re.sub(r"\?.*$", "", u)
    return re.sub(r"(--\d+)-\d+$", r"\1", u)


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_dbs():
    seen, out = set(), []
    for p in sorted(glob.glob(str(ROOT / "runs" / "*" / ".db" / "pipeline.db"))) + \
             sorted(glob.glob(str(ROOT / "runs" / "*" / "pipeline.db"))):
        run = Path(p).parts[-3] if Path(p).parts[-2] == ".db" else Path(p).parts[-2]
        if run in seen:
            continue
        seen.add(run)
        out.append(p)
    return out


def collect():
    """norm_url -> {title, tags, desc, rows:[(db,pid)], scenes:list|None}"""
    prods = {}
    for db in run_dbs():
        try:
            c = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=10)
            rows = c.execute("SELECT id,name,eprolo_url,final_html,seo_description FROM products "
                             "WHERE final_html IS NOT NULL AND shopify_product_id IS NOT NULL").fetchall()
            c.close()
        except Exception as e:
            log(f"  ! read {db}: {str(e)[:60]}")
            continue
        for pid, name, eu, fh, seod in rows:
            try:
                meta = (json.loads(fh or "{}") or {}).get("meta") or {}
            except Exception:
                meta = {}
            if not meta:
                continue
            k = norm(eu)
            e = prods.get(k)
            if e is None:
                tags = meta.get("product_tags") or []
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except Exception:
                        tags = [tags]
                e = prods[k] = {"title": name or "", "tags": [str(t) for t in tags],
                                "desc": meta.get("short_description") or (seod or ""),
                                "rows": [], "scenes": None}
            e["rows"].append((db, pid))
            if meta.get("review_scenes") and not e["scenes"]:
                e["scenes"] = meta["review_scenes"]
    return prods


def write_scene(db, pid, scenes):
    for attempt in range(5):
        try:
            c = sqlite3.connect(db, timeout=60)
            c.execute("PRAGMA busy_timeout=60000")
            row = c.execute("SELECT final_html,stage2_json FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                c.close(); return False
            fh = json.loads(row[0] or "{}")
            meta = fh.get("meta") or {}
            if meta.get("review_scenes"):  # already (idempotent)
                c.close(); return True
            meta["review_scenes"] = scenes
            fh["meta"] = meta
            try:
                s2 = json.loads(row[1] or "{}")
            except Exception:
                s2 = {}
            s2["review_scenes"] = scenes
            c.execute("UPDATE products SET final_html=?, stage2_json=? WHERE id=?",
                      (json.dumps(fh, ensure_ascii=False), json.dumps(s2, ensure_ascii=False), pid))
            c.commit(); c.close()
            return True
        except sqlite3.OperationalError as e:
            time.sleep(1 + attempt)
        except Exception as e:
            log(f"    ! write {Path(db).parts[-2]}#{pid}: {str(e)[:60]}")
            return False
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not DS_KEY:
        raise SystemExit("DEEPSEEK_API_KEY missing in .env")

    log(f"=== backfill start (limit={args.limit or 'ALL'}, workers={args.workers}) ===")
    prods = collect()
    need = {k: v for k, v in prods.items() if not v["scenes"]}
    reuse = {k: v for k, v in prods.items() if v["scenes"]}
    log(f"unique products={len(prods)} | need API={len(need)} | reuse existing={len(reuse)}")

    # 1) propagate already-existing scenes to sibling rows (no API)
    if not args.dry_run:
        for v in reuse.values():
            for db, pid in v["rows"]:
                write_scene(db, pid, v["scenes"])

    keys = list(need.keys())
    if args.limit:
        keys = keys[:args.limit]
    log(f"calling DeepSeek for {len(keys)} products...")

    done = fail = 0
    t0 = time.time()

    def work(k):
        v = need[k]
        scenes, _ = ds_call(v["title"], v["tags"], v["desc"])
        return k, scenes

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, k): k for k in keys}
        for i, fut in enumerate(as_completed(futs), 1):
            k, scenes = fut.result()
            if not scenes:
                fail += 1
            else:
                if not args.dry_run:
                    for db, pid in need[k]["rows"]:
                        write_scene(db, pid, scenes)
                done += 1
            if i % 25 == 0 or i == len(keys):
                rate = i / max(1e-6, time.time() - t0)
                eta = (len(keys) - i) / max(1e-6, rate)
                log(f"  progress {i}/{len(keys)} ok={done} fail={fail} | {rate:.1f}/s ETA {eta/60:.1f}m")

    log(f"=== DONE enriched={done} failed={fail} reused={len(reuse)} in {(time.time()-t0)/60:.1f}m ===")


if __name__ == "__main__":
    sys.exit(main())
