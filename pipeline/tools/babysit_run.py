#!/usr/bin/env python3
"""babysit_run.py — generic resilient runner for ANY category upload.

Generalises babysit_chunk2.py: keep a pipeline run alive until the queue drains,
restarting on death (resume picks up where it stopped), then do the final
cleanup (dedup → collection backfill → keyword-collection fill).

SINGLE-WRITER GUARANTEE: before every restart, force-kill any lingering runner
for this run name and block until it is gone — two processes writing the same
pipeline.db is what corrupted the chunk2 DB (grew to ~1 GiB, malformed).

USAGE
  python pipeline/tools/babysit_run.py \
    --csv "C:/wanelo/CVSs/Beauty & Health_CSV/Tools & Accessories.csv" \
    --name tools-accessories-2026-06-04
"""
from __future__ import annotations
import argparse, os, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "pipeline" / "tools" / "run_pipeline_local.py"


def alive(name: str) -> bool:
    # Match ONLY the runner (run_pipeline_local + this run name), NOT the
    # babysitter itself — the babysitter's own commandline also contains `name`
    # (via --name), so matching name alone would always self-match.
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*run_pipeline_local*' -and "
            "$_.CommandLine -like '*" + name + "*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=40).stdout.strip()
        return out not in ("", "0")
    except Exception:
        return False


def _live_db(name: str) -> Path:
    """run_pipeline_local works on runs/<name>/.db/pipeline.db (live) and only
    periodically copies it to runs/<name>/pipeline.db (stale). Prefer the live
    one for an accurate queue; fall back to the root copy."""
    live = ROOT / "runs" / name / ".db" / "pipeline.db"
    root = ROOT / "runs" / name / "pipeline.db"
    return live if live.exists() else root


def queued(name: str) -> int:
    try:
        c = sqlite3.connect(f"file:{_live_db(name)}?mode=ro", uri=True, timeout=10)
        n = c.execute("SELECT COUNT(*) FROM products WHERE status NOT IN ('done','error')").fetchone()[0]
        c.close()
        return n
    except Exception:
        return -1  # DB not created yet, or mid-write — treat as "not done"


def kill_stragglers(name: str) -> bool:
    """Force-kill any lingering runner for this run, then block until gone.
    The babysitter's own commandline does NOT contain `name`, so it survives."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*run_pipeline_local*' -and "
            "$_.CommandLine -like '*" + name + "*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, text=True, timeout=40)
    except Exception:
        pass
    for _ in range(20):
        if not alive(name):
            time.sleep(2)
            return True
        time.sleep(2)
    return not alive(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--max-restarts", type=int, default=30)
    ap.add_argument("--queue-done", type=int, default=3, help="treat <=N stuck items as done")
    ap.add_argument("--no-fill", action="store_true", help="skip keyword-collection fill at the end")
    args = ap.parse_args()

    NAME = args.name
    LOG = ROOT / "pipeline" / "runs" / "_logs" / f"{NAME}.log"
    LOG.parent.mkdir(parents=True, exist_ok=True)

    restarts = 0
    print(f"[babysit:{NAME}] start. queue={queued(NAME)} alive={alive(NAME)}", flush=True)
    while True:
        if alive(NAME):
            time.sleep(120)
            continue
        q = queued(NAME)
        if (0 <= q <= args.queue_done) or restarts >= args.max_restarts:
            print(f"[babysit:{NAME}] FINISHED (queue={q}, restarts={restarts}). "
                  f"Final dedup + backfill" + ("" if args.no_fill else " + fill") + "...", flush=True)
            subprocess.run([sys.executable, str(ROOT / "pipeline/tools/delete_duplicate_products.py"),
                            "--execute"], cwd=str(ROOT))
            subprocess.run([sys.executable, str(ROOT / "pipeline/tools/backfill_collections.py")],
                           cwd=str(ROOT))
            if not args.no_fill:
                # corruption-proof: source products from live Shopify, not local DB
                subprocess.run([sys.executable, str(ROOT / "pipeline/tools/fill_collections.py"),
                                "--from-shopify", "--include-thin", "--prod-sim", "0.16", "--execute"],
                               cwd=str(ROOT))
            print(f"[babysit:{NAME}] done.", flush=True)
            return 0
        restarts += 1
        print(f"[babysit:{NAME}] not running ({q} queued) — (re)start #{restarts}", flush=True)
        if not kill_stragglers(NAME):
            print(f"[babysit:{NAME}] ⚠ a runner is still alive after kill — skip this cycle "
                  f"to avoid a writer race.", flush=True)
            time.sleep(120)
            continue
        with open(LOG, "a", encoding="utf-8") as lf:
            subprocess.Popen([sys.executable, str(RUNNER), "--csv", args.csv, "--name", NAME],
                             cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)
        time.sleep(240)  # warmup (setup + FAISS/SEO) before next poll


if __name__ == "__main__":
    sys.exit(main())
