"""run_watchdog.py — sentinel process that monitors a live pipeline run
and exits early when something goes wrong, so the parent agent receives
a task-completion notification IMMEDIATELY instead of having to poll.

Exit codes:
    0 — pipeline finished cleanly (saw end-marker, log stable)
    1 — critical pattern detected in log (Anthropic 400, Bug B regression,
        ACCESS_DENIED, Shopify rejected, exceptions, etc.)
    2 — stall (no log activity for STALL_MIN minutes)
    3 — too many error products in DB

USAGE:
    python pipeline/tools/run_watchdog.py \
        --log <path-to-pipeline-stdout-log> \
        --db  <path-to-pipeline.db> \
        [--interval 15] [--stall-min 5]

Designed to run as a sibling background task to run_pipeline_local.py.
When watchdog exits the parent agent gets notification and the watchdog
output contains a structured report on what triggered the alert.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# Force UTF-8 stdout — otherwise box-chars / emojis in log content crash
# the prints on cp1251 Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Critical patterns — any match → immediate alert + exit 1.
CRITICAL_PATTERNS = [
    (r"ZERO metafields written",          "Bug B regression — metafields not writing"),
    (r"\[Anthropic FAILED",               "Anthropic API call failed after retries"),
    (r"LESS_THAN_OR_EQUAL_TO",            "Shopify mutation rejected (limit hit)"),
    # PINNED_LIMIT_REACHED is a known-state warning, not a critical fault:
    # the user's 20 curated definitions fill all pin slots. Cell 2 auto-ensure
    # tries to create 17 more (round 5+6 modules) and gets per-key warnings,
    # but the pipeline keeps running with the existing 20. Excluded from
    # critical patterns; the metafield-filtering patch will silence it.
    (r"ACCESS_DENIED",                    "Shopify scope-permission denied"),
    (r"app_not_installed",                "Shopify app uninstalled — OAuth fails"),
    (r"Could not resolve authentication", "Anthropic auth error (env var?)"),
    (r"`temperature` is deprecated",      "Opus 4.7 temperature param regression"),
    (r"\binvalid_request_error\b",        "Anthropic API request format invalid"),
    (r"NotImplementedError",              "Likely Windows asyncio.subprocess bug"),
    (r"UnboundLocalError",                "Code bug: variable used before assignment"),
    (r"\[COMPILE ERROR\]",                "Cell did not compile"),
    (r"\[SHELL EXCEPTION\]",              "IPython shell raised before cell ran"),
    (r"AuthenticationError",              "API auth error"),
    # Note: [RUNTIME ERROR] and SameFileError removed — they fire on known
    # local-vs-Colab quirks (xlsx self-copy, etc) that the IPython runner
    # gracefully continues past. Real downstream issues will surface via
    # the more specific patterns above + DB error-status checks.
]
COMPILED = [(re.compile(p, re.IGNORECASE), p, desc) for p, desc in CRITICAL_PATTERNS]

# End markers — pipeline finished cleanly.
END_MARKERS = (
    "=== Final DB state ===",
    "=== executed: ",
    "saved executed notebook to",
)


def read_new(log: Path, last_pos: int) -> tuple[int, str]:
    """Read bytes appended to `log` since `last_pos`. Return new position
    and decoded text."""
    if not log.exists():
        return last_pos, ""
    try:
        with open(log, "rb") as f:
            f.seek(last_pos)
            data = f.read()
            new_pos = f.tell()
    except OSError as e:
        return last_pos, f"\n[watchdog: read error {e}]\n"
    return new_pos, data.decode("utf-8", errors="replace")


def db_errored(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        db = sqlite3.connect(str(db_path))
        rows = db.execute(
            "SELECT id, name, error_msg FROM products WHERE status='error'"
        ).fetchall()
        db.close()
        return [{"id": r[0], "name": r[1], "error_msg": r[2]} for r in rows]
    except sqlite3.Error:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--stall-min", type=int, default=5,
                        help="alert if log has no new bytes for N minutes")
    parser.add_argument("--max-errors", type=int, default=3,
                        help="abort if N+ products in DB end up in status='error'")
    args = parser.parse_args()

    print(f"watchdog START at {time.strftime('%H:%M:%S')}")
    print(f"  log: {args.log}")
    print(f"  db:  {args.db}")
    print(f"  poll {args.interval}s, stall threshold {args.stall_min}min, "
          f"max errored products {args.max_errors}")
    print()

    last_pos = 0
    last_activity = time.time()
    seen_alerts: set[tuple] = set()
    seen_error_ids: set[int] = set()
    last_db_status_report = 0.0

    while True:
        time.sleep(args.interval)
        now = time.time()

        new_pos, chunk = read_new(args.log, last_pos)
        if new_pos > last_pos:
            last_activity = now
            last_pos = new_pos

            # End-of-pipeline detection
            for marker in END_MARKERS:
                if marker in chunk:
                    print(f"\n[{time.strftime('%H:%M:%S')}] END marker detected: {marker!r}")
                    print("\nwatchdog: pipeline finished cleanly")
                    _report_db(args.db)
                    return 0

            # Critical patterns
            for pat, raw, desc in COMPILED:
                for m in pat.finditer(chunk):
                    snippet = chunk[max(0, m.start() - 60): m.end() + 200]
                    # Truncate to a few lines for the alert
                    lines = snippet.splitlines()
                    sig = (raw, lines[0][:80] if lines else "")
                    if sig in seen_alerts:
                        continue
                    seen_alerts.add(sig)
                    print(f"\n!!! ALERT [{time.strftime('%H:%M:%S')}] pattern={raw!r}")
                    print(f"    description: {desc}")
                    for ln in lines[:6]:
                        print(f"    > {ln[:200]}")
                    # Exit on first critical
                    print("\nwatchdog: aborting on first critical pattern")
                    _report_db(args.db)
                    return 1

        # DB error products
        errored = db_errored(args.db)
        new_errs = [e for e in errored if e["id"] not in seen_error_ids]
        for e in new_errs:
            seen_error_ids.add(e["id"])
            print(f"\n!!! DB ALERT [{time.strftime('%H:%M:%S')}] "
                  f"product #{e['id']} → status=error")
            print(f"    name: {(e['name'] or '')[:80]}")
            print(f"    msg:  {(e['error_msg'] or '')[:240]}")

        if len(seen_error_ids) >= args.max_errors:
            print(f"\nwatchdog: aborting — {len(seen_error_ids)} errored "
                  f"products (limit {args.max_errors})")
            _report_db(args.db)
            return 3

        # Stall detection
        stall_sec = now - last_activity
        if stall_sec > args.stall_min * 60:
            print(f"\n!!! STALL [{time.strftime('%H:%M:%S')}] "
                  f"no log activity for {stall_sec / 60:.1f} min")
            print(f"    likely hung on network/API call or deadlocked")
            _report_db(args.db)
            return 2

        # Quiet heartbeat every ~2 min to show watchdog is alive
        if now - last_db_status_report > 120:
            last_db_status_report = now
            counts = _db_status_counts(args.db)
            err_count = len(db_errored(args.db))
            log_age = now - last_activity
            print(f"  [{time.strftime('%H:%M:%S')}] heartbeat — "
                  f"log age {log_age:.0f}s, db: {counts}, errors: {err_count}")


def _db_status_counts(db_path: Path) -> dict:
    if not db_path.exists():
        return {}
    try:
        db = sqlite3.connect(str(db_path))
        out = {}
        for row in db.execute("SELECT status, COUNT(*) FROM products GROUP BY status"):
            out[row[0]] = row[1]
        db.close()
        return out
    except sqlite3.Error:
        return {}


def _report_db(db_path: Path) -> None:
    print("\n=== DB snapshot at exit ===")
    counts = _db_status_counts(db_path)
    for s, n in sorted(counts.items()):
        print(f"  {s:18s} {n}")
    errored = db_errored(db_path)
    if errored:
        print(f"\n  Errored products:")
        for e in errored:
            print(f"    [{e['id']}] {(e['name'] or '')[:60]}")
            print(f"          msg: {(e['error_msg'] or '')[:200]}")


if __name__ == "__main__":
    sys.exit(main())
