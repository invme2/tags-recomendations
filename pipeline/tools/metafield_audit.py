#!/usr/bin/env python3
"""metafield_audit.py — operator visibility for the metafield ecosystem.

Three sub-commands:

  coverage   — Show every metafield definition + how many live products use it.
               Spot rare / never-used / over-emitted keys.

                 python pipeline/tools/metafield_audit.py coverage

  drift      — Replay the audit log (.db/metafield_audit.jsonl) and show
               every shape-drift event. Tells you which dynamic keys are
               inconsistent across products.

                 python pipeline/tools/metafield_audit.py drift

  candidates — Show auto-created keys + product count + first sample.
               These are candidates for building a dedicated wanelo-*.liquid
               snippet (instead of falling back to wanelo-auto-section).

                 python pipeline/tools/metafield_audit.py candidates --min-uses 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
API_VERSION = "2024-10"


def load_env() -> None:
    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)


def get_token() -> tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"},
        timeout=15,
    )
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers,
                      json={"query": query, "variables": variables or {}},
                      timeout=30)
    r.raise_for_status()
    return r.json()


# ── coverage: count which products use which metafield keys ──
def cmd_coverage() -> int:
    load_env()
    store, token = get_token()

    # All metafield definitions in custom namespace
    r = gql(store, token,
            'query{metafieldDefinitions(first:250, ownerType:PRODUCT, namespace:"custom"){nodes{key name type{name} pinnedPosition}}}')
    defs = r["data"]["metafieldDefinitions"]["nodes"]
    def_meta = {d["key"]: d for d in defs}

    # All products + their custom metafield keys
    counts: Counter = Counter()
    cursor = None
    total_products = 0
    while True:
        r = gql(store, token,
                'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} nodes{id metafields(first:50, namespace:"custom"){edges{node{key}}}}}}',
                {"c": cursor})
        page = r["data"]["products"]
        for p in page["nodes"]:
            total_products += 1
            for e in p["metafields"]["edges"]:
                counts[e["node"]["key"]] += 1
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    print(f"\n=== Metafield coverage across {total_products} live products ===\n")
    print(f"{'key':32s} {'name':38s} {'pin':4s} {'used':>5s} {'%':>5s}")
    print("-" * 90)
    # Sort by usage count desc
    for key in sorted(set(def_meta.keys()) | set(counts.keys()),
                      key=lambda k: (-counts.get(k, 0), k)):
        d = def_meta.get(key, {})
        name = d.get("name", "(no definition!)")[:38]
        pin = "P" if (d.get("pinnedPosition") is not None) else "-"
        used = counts.get(key, 0)
        pct = (used / total_products * 100) if total_products else 0
        marker = ""
        if used == 0 and d:
            marker = "  ← UNUSED"
        elif used == total_products and total_products > 0:
            marker = "  ← ALL"
        print(f"  {key:30s} {name:38s} [{pin}] {used:5d} {pct:4.0f}% {marker}")
    return 0


# ── drift: replay audit log for shape drift events ──
def cmd_drift() -> int:
    load_env()
    audit_path = REPO_ROOT / "pipeline" / "runs"
    found_any = False
    for run_dir in audit_path.glob("*/.db/metafield_audit.jsonl"):
        print(f"\n=== {run_dir.parent.parent.name} / metafield_audit.jsonl ===")
        n_drift = 0
        for line in run_dir.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "shape_drift":
                n_drift += 1
                found_any = True
                print(f"  {rec.get('ts','?')[:19]} pid={rec.get('product_id','?')[-13:]}")
                print(f"    key:    {rec.get('key')}")
                print(f"    cached: {rec.get('cached_shape')}")
                print(f"    new:    {rec.get('new_shape')}")
                print(f"    title:  {rec.get('product_title','?')[:60]}")
        if not n_drift:
            print("  (no drift events)")
    if not found_any:
        print("No audit logs found. Run a pipeline batch first.")
    return 0


# ── candidates: auto-created keys + product count ──
def cmd_candidates(min_uses: int) -> int:
    load_env()
    audit_path = REPO_ROOT / "pipeline" / "runs"

    # Find every "new_key" event across all runs
    new_key_events: list[dict] = []
    for run_log in audit_path.glob("*/.db/metafield_audit.jsonl"):
        for line in run_log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "new_key":
                new_key_events.append(rec)
    if not new_key_events:
        print("No auto-created metafield keys found in audit logs.")
        return 0

    # Group by key
    by_key: dict[str, list[dict]] = {}
    for ev in new_key_events:
        by_key.setdefault(ev["key"], []).append(ev)

    # Now also count live products using each key (so old/unused don't bloat list)
    store, token = get_token()
    counts: Counter = Counter()
    cursor = None
    while True:
        r = gql(store, token,
                'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} nodes{metafields(first:50, namespace:"custom"){edges{node{key}}}}}}',
                {"c": cursor})
        page = r["data"]["products"]
        for p in page["nodes"]:
            for e in p["metafields"]["edges"]:
                counts[e["node"]["key"]] += 1
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    print(f"\n=== Auto-created metafield candidates (min_uses={min_uses}) ===\n")
    print("These keys started as auto-created by the pipeline.")
    print("If a key has high usage, consider building a dedicated")
    print("`wanelo-<key>.liquid` snippet for better styling.\n")

    for key, events in sorted(by_key.items(), key=lambda kv: -counts.get(kv[0], 0)):
        used = counts.get(key, 0)
        if used < min_uses:
            continue
        first = events[0]
        print(f"  {key} — used by {used} products (first emitted by '{first.get('product_title','?')[:50]}')")
        print(f"    Shape: {first.get('shape')}")
        print(f"    Sample (first 200 chars): {first.get('sample','')[:200]}")
        print()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("coverage", help="Show usage % per metafield definition")
    sub.add_parser("drift", help="Show shape-drift events from audit log")
    c_cand = sub.add_parser("candidates",
                            help="Show auto-created keys + usage count")
    c_cand.add_argument("--min-uses", type=int, default=1,
                        help="Only show keys used by >= N products (default 1)")
    args = p.parse_args()

    if args.cmd == "coverage":
        return cmd_coverage()
    if args.cmd == "drift":
        return cmd_drift()
    if args.cmd == "candidates":
        return cmd_candidates(args.min_uses)
    return 1


if __name__ == "__main__":
    sys.exit(main())
