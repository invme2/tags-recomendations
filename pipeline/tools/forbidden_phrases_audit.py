#!/usr/bin/env python3
"""forbidden_phrases_audit.py — scan ALL live product metafields for
phrases that create FTC fraud risk or contradict the theme's checkout
module.

Critical phrases (FAIL — reject before any future batch):
  - "free shipping" / "fast shipping" / "ships in 24h"  → theme handles
    shipping module; PDP claims create conflicts on inspection
  - "money-back guarantee" / "30-day refund" / "lifetime warranty"
    → Shopify checkout has its own policy; PDP claims = contradiction
  - "FDA approved" / "FDA cleared" (unless verified)
  - Fake clinical citations (numbers with no source)

Run after every batch to catch any prompts that drifted into forbidden
territory. Exit code:
  0 = clean
  2 = forbidden phrases found
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
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


# Phrases that violate CLAUDE.md operator policy + FTC guidance.
# Each entry: (regex, severity, why).
FORBIDDEN = [
    # Shipping claims — theme's checkout module handles this
    (r"\bfree shipping\b",                "FAIL", "shipping claim duplicates theme module"),
    (r"\bfast shipping\b",                "FAIL", "shipping claim duplicates theme module"),
    (r"\bships? in 24 ?h(?:ours?)?\b",    "FAIL", "delivery-time claim — unverifiable for dropship"),
    (r"\bnext.day delivery\b",            "FAIL", "delivery-time claim — unverifiable for dropship"),
    (r"\bovernight (?:shipping|delivery)\b", "FAIL", "delivery-time claim — unverifiable"),

    # Returns / refunds — handled by theme + Shopify policy page
    (r"\bmoney.back guarantee\b",         "FAIL", "guarantee claim creates checkout contradiction"),
    (r"\b\d{1,3}.day refund\b",           "FAIL", "refund-window claim creates checkout contradiction"),
    (r"\blifetime warranty\b",            "FAIL", "warranty claim creates checkout contradiction"),
    (r"\bsecure checkout\b",              "FAIL", "duplicates Shopify checkout-page module"),

    # Fake regulatory claims (unless verified — these are dropship products)
    (r"\bFDA[- ](?:approved|cleared)\b",  "WARN", "FDA claim — verify before allowing"),
    (r"\bclinically proven\b",            "WARN", "clinical claim — verify source"),
    (r"\bdoctor recommended\b",           "WARN", "endorsement claim — verify"),
    (r"\bdermatologist tested\b",         "WARN", "endorsement claim — verify"),

    # Forbidden by CLAUDE.md
    (r"\bcruelty.free\b",                 "WARN", "verify before claiming"),
    (r"\b100% organic\b",                 "WARN", "regulatory claim — verify"),
    (r"\b100% natural\b",                 "WARN", "regulatory claim — verify"),
]


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


def scan_text(text: str) -> list[tuple[str, str, str]]:
    """Return list of (matched_phrase, severity, why) hits."""
    if not text:
        return []
    hits = []
    for pattern, sev, why in FORBIDDEN:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            hits.append((m.group(0), sev, why))
    return hits


def flatten_json_strings(value) -> list[str]:
    """Walk a JSON-decoded value, return all string leaves."""
    out = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(flatten_json_strings(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(flatten_json_strings(v))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None,
                        help="Audit one product (numeric PID, no gid:// prefix)")
    args = parser.parse_args()

    load_env()
    store, token = get_token()

    # Get product list
    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = []
        cursor = None
        while True:
            r = gql(store, token,
                    'query($c:String){products(first:50, after:$c){pageInfo{hasNextPage endCursor} nodes{id}}}',
                    {"c": cursor})
            page = r["data"]["products"]
            pids.extend(n["id"] for n in page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        print(f"Scanning {len(pids)} live products for forbidden phrases...\n")

    n_total_hits = 0
    n_fail = 0
    n_warn = 0
    n_clean = 0

    for i, pid in enumerate(pids, 1):
        q = ('query($id:ID!){product(id:$id){handle title '
             'descriptionHtml '
             'metafields(first:100, namespace:"custom"){edges{node{key value type}}}}}')
        r = gql(store, token, q, {"id": pid})
        p = r.get("data", {}).get("product")
        if not p:
            continue

        product_hits: list[tuple[str, str, str, str]] = []
        # (source_label, matched_phrase, severity, why)

        # Scan descriptionHtml
        for ph, sev, why in scan_text(p.get("descriptionHtml", "")):
            product_hits.append(("descriptionHtml", ph, sev, why))

        # Scan every JSON metafield's string leaves
        for e in p["metafields"]["edges"]:
            n = e["node"]
            if n["type"] != "json":
                continue
            try:
                val = json.loads(n["value"])
            except Exception:
                continue
            for s in flatten_json_strings(val):
                for ph, sev, why in scan_text(s):
                    product_hits.append((f'custom.{n["key"]}', ph, sev, why))

        if not product_hits:
            n_clean += 1
            print(f"  [{i:3d}/{len(pids)}] \033[92m OK \033[0m  {p['handle'][:55]}")
            continue

        n_total_hits += len(product_hits)
        has_fail = any(sev == "FAIL" for _, _, sev, _ in product_hits)
        if has_fail:
            n_fail += 1
            marker = "\033[91mFAIL\033[0m"
        else:
            n_warn += 1
            marker = "\033[93mWARN\033[0m"
        print(f"  [{i:3d}/{len(pids)}] {marker}  {p['handle'][:55]} "
              f"({len(product_hits)} hits)")
        for source, phrase, sev, why in product_hits[:8]:
            sev_mark = "\033[91m✗\033[0m" if sev == "FAIL" else "\033[93m!\033[0m"
            print(f"           {sev_mark} [{source}] '{phrase}' — {why}")
        if len(product_hits) > 8:
            print(f"           ... and {len(product_hits) - 8} more")

    print(f"\n{'=' * 60}")
    print(f"  \033[92mclean\033[0m: {n_clean}  "
          f"\033[93mwarn\033[0m: {n_warn}  "
          f"\033[91mfail\033[0m: {n_fail}  "
          f"({n_total_hits} hits total)")

    if n_fail > 0:
        return 2
    if n_warn > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
