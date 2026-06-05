#!/usr/bin/env python3
"""csv_ledger.py — persistent ledger of which product CSVs have been
processed through the pipeline. Prevents double-upload of the same
catalog, tracks per-CSV results.

Ledger location: pipeline/runs/.csv_ledger.json

Schema (JSON object, key = absolute CSV path):
  {
    "C:\\\\wanelo\\\\CVSs\\\\...\\\\Bath & Shower.csv": {
      "first_seen":     "2026-05-28T09:00:00Z",
      "last_run":       "2026-05-28T09:30:00Z",
      "run_name":       "bath-shower-2026-05-28",
      "status":         "in_progress" | "done" | "error" | "partial",
      "products_in_csv": 26,
      "products_pushed": 24,
      "errors":         2,
      "sha256":         "abc123...",      # detect CSV content change
      "cost_usd":       3.42,
      "notes":          "..."
    },
    ...
  }

USAGE:
  python pipeline/tools/csv_ledger.py status                  # show all
  python pipeline/tools/csv_ledger.py status --pending        # un-processed only
  python pipeline/tools/csv_ledger.py check <path>            # is this CSV already done?
  python pipeline/tools/csv_ledger.py mark <path> in_progress --run-name X
  python pipeline/tools/csv_ledger.py mark <path> done --products-pushed N --errors N --cost-usd N
  python pipeline/tools/csv_ledger.py scan <dir>              # find new CSVs in dir
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "pipeline" / "runs" / ".csv_ledger.json"


def now_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"warning: ledger parse failed: {e} — starting fresh")
        return {}


def save_ledger(d: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def count_csv_rows(path: Path) -> int:
    """Count non-empty product rows (handle BOM, skip blank lines)."""
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and ("http" in line):
                n += 1
    return n


def normalize_path(p: str) -> str:
    """Absolute path with forward slashes for consistent ledger keys."""
    return str(Path(p).resolve()).replace("\\", "/")


# ─── commands ────────────────────────────────────────────────────────
def cmd_status(args):
    ledger = load_ledger()
    if not ledger:
        print("Ledger empty. Use 'mark' or 'scan' to populate.")
        return 0
    print(f"{'csv':70s} {'status':12s} {'run_name':25s} {'pushed':>7s} {'cost':>7s}")
    print("-" * 130)
    for path, rec in sorted(ledger.items()):
        if args.pending and rec.get("status") == "done":
            continue
        name = Path(path).name
        st = rec.get("status", "?")
        run = rec.get("run_name", "")[:25]
        pushed = rec.get("products_pushed", "")
        cost = f"${rec.get('cost_usd', 0):.2f}" if rec.get("cost_usd") else ""
        st_color = {"done": "\033[92m", "in_progress": "\033[93m",
                    "error": "\033[91m", "partial": "\033[93m"}.get(st, "")
        print(f"  {name[:68]:68s} {st_color}{st:12s}\033[0m {run:25s} {str(pushed):>7s} {cost:>7s}")
    print()
    return 0


def cmd_check(args):
    p = normalize_path(args.path)
    ledger = load_ledger()
    if p not in ledger:
        print(f"\033[92mNEW\033[0m — {Path(p).name} not in ledger")
        return 0
    rec = ledger[p]
    print(f"\033[93mEXISTS\033[0m — {Path(p).name}")
    print(f"  status:    {rec.get('status')}")
    print(f"  last_run:  {rec.get('last_run')}")
    print(f"  run_name:  {rec.get('run_name')}")
    print(f"  pushed:    {rec.get('products_pushed')} / {rec.get('products_in_csv')}")
    print(f"  cost:      ${rec.get('cost_usd', 0):.2f}")
    # Check if file content changed since last run
    try:
        current_hash = sha256_file(Path(args.path))
        if rec.get("sha256") and rec["sha256"] != current_hash:
            print(f"  \033[93m! CSV CONTENT CHANGED since last run\033[0m")
    except Exception:
        pass
    return 1 if rec.get("status") == "done" else 0


def cmd_mark(args):
    p = normalize_path(args.path)
    path_obj = Path(args.path)
    if not path_obj.exists():
        print(f"ERR: {args.path} not found", file=sys.stderr)
        return 1
    ledger = load_ledger()
    rec = ledger.get(p, {})
    rec.setdefault("first_seen", now_utc())
    rec["last_run"] = now_utc()
    rec["status"] = args.status
    if args.run_name:
        rec["run_name"] = args.run_name
    rec["products_in_csv"] = count_csv_rows(path_obj)
    rec["sha256"] = sha256_file(path_obj)
    if args.products_pushed is not None:
        rec["products_pushed"] = args.products_pushed
    if args.errors is not None:
        rec["errors"] = args.errors
    if args.cost_usd is not None:
        rec["cost_usd"] = args.cost_usd
    if args.notes:
        rec["notes"] = args.notes
    ledger[p] = rec
    save_ledger(ledger)
    print(f"OK — marked {Path(p).name} as '{args.status}'")
    return 0


def cmd_scan(args):
    """List CSVs in a directory + their status in the ledger."""
    d = Path(args.directory)
    if not d.is_dir():
        print(f"ERR: {args.directory} is not a directory", file=sys.stderr)
        return 1
    ledger = load_ledger()
    csvs = sorted(d.glob("*.csv"))
    if not csvs:
        print(f"No CSVs found in {d}")
        return 0
    print(f"\n{'CSV':50s} {'rows':>5s} {'status':12s} {'pushed':>7s}")
    print("-" * 90)
    n_new = n_done = n_other = 0
    for csv_path in csvs:
        key = normalize_path(str(csv_path))
        rows = count_csv_rows(csv_path)
        rec = ledger.get(key)
        if not rec:
            status = "\033[92mNEW\033[0m"
            pushed = ""
            n_new += 1
        else:
            st = rec.get("status", "?")
            pushed = str(rec.get("products_pushed", ""))
            if st == "done":
                status = "\033[2mdone\033[0m"
                n_done += 1
            else:
                status = f"\033[93m{st}\033[0m"
                n_other += 1
        print(f"  {csv_path.name[:48]:48s} {rows:5d} {status:20s} {pushed:>7s}")
    print(f"\n  \033[92mNEW\033[0m: {n_new}  done: {n_done}  other: {n_other}  /  {len(csvs)} total")
    return 0


# ─── main ────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s_status = sub.add_parser("status", help="Show ledger contents")
    s_status.add_argument("--pending", action="store_true",
                          help="Show only CSVs that are NOT done")
    s_status.set_defaults(func=cmd_status)

    s_check = sub.add_parser("check", help="Check if a specific CSV has been processed")
    s_check.add_argument("path")
    s_check.set_defaults(func=cmd_check)

    s_mark = sub.add_parser("mark", help="Update ledger entry")
    s_mark.add_argument("path")
    s_mark.add_argument("status", choices=["in_progress", "done", "error", "partial"])
    s_mark.add_argument("--run-name", type=str, default=None)
    s_mark.add_argument("--products-pushed", type=int, default=None)
    s_mark.add_argument("--errors", type=int, default=None)
    s_mark.add_argument("--cost-usd", type=float, default=None)
    s_mark.add_argument("--notes", type=str, default=None)
    s_mark.set_defaults(func=cmd_mark)

    s_scan = sub.add_parser("scan", help="Scan a directory for CSVs + show status")
    s_scan.add_argument("directory")
    s_scan.set_defaults(func=cmd_scan)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
