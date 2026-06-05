#!/usr/bin/env python3
"""resume_with_retries.py — run the product pipeline for a CSV with automatic
RETRIES, so a transient failure (Anthropic credits exhausted, rate limit,
network blip, EPROLO hiccup) doesn't permanently stall the upload.

Each attempt calls run_pipeline_local.py for the SAME csv. Because the pipeline
resumes/dedupes by product (already-pushed products are skipped), every retry
simply continues from where the previous one stopped — no duplicates.

Operator rule (2026-05-29): the Anthropic API ran out of credits mid-batch and
killed the run with no retry. Give it several attempts with a pause between, so
a top-up (or a transient error clearing) lets it carry on automatically.

USAGE:
  python pipeline/tools/resume_with_retries.py \
      --csv "C:/wanelo/CVSs/Beauty & Health_CSV/Health Care.csv" \
      --name health-care --limit 100 --attempts 5 --pause 900

  --attempts  max pipeline runs (default 5)
  --pause     seconds to wait between attempts (default 900 = 15 min)
  --limit     products to process per attempt (passed through)

Run only ONE pipeline process at a time per DB (they share pipeline.db).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
RUNNER = REPO_ROOT / "pipeline" / "tools" / "run_pipeline_local.py"


def product_count() -> int:
    load_dotenv(ENV_FILE, override=True)
    store = os.environ["SHOPIFY_STORE"]
    tok = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]
    r = requests.post(f"https://{store}/admin/api/2024-10/graphql.json",
                      headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                      json={"query": "{productsCount{count}}"}, timeout=30)
    return r.json()["data"]["productsCount"]["count"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--name", default="resume")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--attempts", type=int, default=5)
    ap.add_argument("--pause", type=int, default=900, help="seconds between attempts (default 900=15min)")
    args = ap.parse_args()

    total_start = product_count()
    print(f"[resume] start: {total_start} products in store. "
          f"Up to {args.attempts} attempts, {args.pause}s pause, limit {args.limit}/attempt.\n")

    for attempt in range(1, args.attempts + 1):
        before = product_count()
        print(f"[resume] === attempt {attempt}/{args.attempts} (store has {before}) ===")
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--csv", args.csv,
             "--name", f"{args.name}-a{attempt}", "--limit", str(args.limit)],
            cwd=str(REPO_ROOT))
        after = product_count()
        added = after - before
        print(f"[resume] attempt {attempt}: exit={proc.returncode}, +{added} products "
              f"({before} -> {after}), total so far +{after - total_start}")

        if proc.returncode == 0 and added == 0:
            # Clean finish AND nothing new = CSV exhausted (or all already done).
            print("[resume] clean exit with no new products — done (CSV exhausted).")
            break
        if attempt < args.attempts:
            print(f"[resume] waiting {args.pause}s before next attempt "
                  f"(lets credits/transient errors recover)...\n")
            time.sleep(args.pause)

    print(f"\n[resume] finished. Net added this session: "
          f"+{product_count() - total_start} products.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
