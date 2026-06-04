#!/usr/bin/env python3
"""babysit_chunk2.py — keep chunk2 alive until done, then final cleanup.

chunk2 dies periodically (memory pressure on the bulk scrape/SEO phase). This
watcher: polls the process; if it died with products still queued, restarts it
(resume picks up where it stopped); when the queue is drained (or a restart cap
is hit for permanently-stuck items), runs the final duplicate sweep + collection
tag backfill, then exits.
"""
from __future__ import annotations
import os, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "health-care-chunk2-2026-06-01"
DB = ROOT / "runs" / NAME / "pipeline.db"
CSV = "C:/wanelo/CVSs/Beauty & Health_CSV/Health Care - chunk2.csv"
LOG = ROOT / "pipeline" / "runs" / "_logs" / "chunk2.log"
RUNNER = ROOT / "pipeline" / "tools" / "run_pipeline_local.py"
MAX_RESTARTS = 30
QUEUE_DONE = 3   # treat <=3 stuck items as "done"


def alive() -> bool:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*" + NAME + "*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=40).stdout.strip()
        return out not in ("", "0")
    except Exception:
        return False


def queued() -> int:
    try:
        c = sqlite3.connect(str(DB))
        n = c.execute("SELECT COUNT(*) FROM products WHERE status NOT IN ('done','error')").fetchone()[0]
        c.close()
        return n
    except Exception:
        return -1


def kill_stragglers() -> bool:
    """Force-kill ANY lingering runner for this run, then block until none remain.
    Prevents two processes writing the same pipeline.db across a restart — that
    writer race corrupted the chunk2 DB (grew to ~1 GiB, 'database disk image is
    malformed'). Single-writer guarantee = no corruption. The babysitter's own
    commandline does NOT contain NAME, so this never kills the watcher itself."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*" + NAME + "*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, text=True, timeout=40)
    except Exception:
        pass
    for _ in range(20):                      # up to ~40s for the OS to release the file lock
        if not alive():
            time.sleep(2)                    # grace for WAL/lock release after exit
            return True
        time.sleep(2)
    return not alive()


def main() -> int:
    restarts = 0
    print(f"[babysit] start. queue={queued()} alive={alive()}", flush=True)
    while True:
        if alive():
            time.sleep(120)
            continue
        q = queued()
        if 0 <= q <= QUEUE_DONE or restarts >= MAX_RESTARTS:
            print(f"[babysit] chunk2 FINISHED (queue={q}, restarts={restarts}). "
                  f"Final dedup + backfill...", flush=True)
            subprocess.run([sys.executable, str(ROOT / "pipeline/tools/delete_duplicate_products.py"),
                            "--execute"], cwd=str(ROOT))
            subprocess.run([sys.executable, str(ROOT / "pipeline/tools/backfill_collections.py")],
                           cwd=str(ROOT))
            print("[babysit] done.", flush=True)
            return 0
        restarts += 1
        print(f"[babysit] chunk2 died with {q} queued — restart #{restarts}", flush=True)
        # SINGLE-WRITER GUARANTEE: make sure no half-dead runner is still touching
        # pipeline.db before launching the next one (else SQLite corruption).
        if not kill_stragglers():
            print("[babysit] ⚠ a runner is still alive after kill — skipping this "
                  "restart cycle to avoid a writer race.", flush=True)
            time.sleep(120)
            continue
        with open(LOG, "a", encoding="utf-8") as lf:
            subprocess.Popen([sys.executable, str(RUNNER), "--csv", CSV, "--name", NAME],
                             cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)
        time.sleep(240)  # warmup (setup + FAISS/SEO) before next poll


if __name__ == "__main__":
    sys.exit(main())
