#!/usr/bin/env python3
"""prioritize_video_products.py — auto-select the highest-traffic products
(by UNIQUE visitors) that don't yet have a video, tag them `videos-needed`,
and (optionally) kick off the existing generation pipeline.

WHY
===
Videos are expensive (Higgsfield credits) so we should make them for the
products people actually look at. This tool is the "brain" that decides
WHICH products deserve a video next, instead of tagging by hand.

THE LOOP
========
  unique-visitor ranking ──▶ filter (skip done / in-flight)
                          ──▶ take top-K within credit budget
                          ──▶ tag `videos-needed`  (--apply)
                          ──▶ [optional] trigger generation  (--generate)
                          ──▶ marketing_studio_batch → review → apply_video_decisions

The generation + publish machinery already exists:
  - pipeline/tools/marketing_studio_batch.py   (generate via Higgsfield)
  - pipeline/tools/apply_video_decisions.py     (push to carousel / metafield)

PLUGGABLE TRAFFIC SOURCE
========================
Shopify's per-product unique-visitor data is NOT exposed to our app
(no read_reports scope, ShopifyQL removed). So the ranking comes from a
pluggable source — pick whichever you wire up:

  --source json   --input ranking.json
        {"handle-a": 412, "handle-b": 88, ...}   (handle → unique visitors)
        This is the shape a GA4 exporter or a self-hosted view-counter
        (Cloudflare Worker etc.) writes. Fully autonomous once wired.

  --source csv    --input export.csv
        A Shopify Admin analytics export (e.g. "Sessions by landing page").
        The adapter auto-detects a path/handle column + a numeric metric
        column and maps /products/<handle> → handle. Zero setup, but you
        export the CSV periodically (semi-manual).

  --source ga4    (scaffold — needs google-analytics-data + GA4 creds)
        See GA4RankingSource below. Pulls totalUsers per /products/ path.

SAFETY
======
- Default is DRY-RUN. Nothing is tagged or generated without --apply.
- --generate additionally triggers paid video creation; off by default.
- A ledger (runs/video_priority/ledger.json) records what was already
  queued so reruns don't re-tag the same products.
- --budget caps how many credits a run may commit (6 videos × 75 = 450
  credits per product).

USAGE
=====
  # preview the ranking + what would be tagged (no writes)
  python pipeline/tools/prioritize_video_products.py --source json --input ranking.json --top 5

  # actually tag the top 5 high-traffic video-less products
  python pipeline/tools/prioritize_video_products.py --source json --input ranking.json --top 5 --apply

  # tag AND start generation (needs HIGGSFIELD_API_KEY for autonomous mode)
  python pipeline/tools/prioritize_video_products.py --source json --input ranking.json --top 5 --apply --generate
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
LEDGER_DIR = REPO_ROOT / "pipeline" / "runs" / "video_priority"
LEDGER_FILE = LEDGER_DIR / "ledger.json"
API_VERSION = "2024-10"

CREDITS_PER_PRODUCT = 6 * 75  # 6 presets × 75 credits (marketing_studio_batch default)

# Tags that mean a product is already done or already in the video pipeline.
TAG_NEEDED = "videos-needed"
TAGS_IN_FLIGHT = {"videos-needed", "videos-ready-for-review", "videos-generating"}
TAG_DONE = "videos-applied"


# ── Shopify auth ────────────────────────────────────────────────────────────
def shopify_token() -> Tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not token:
        r = requests.post(
            f"https://{store}/admin/oauth/access_token",
            json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
                  "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
                  "grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
    return store, token


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    for attempt in range(4):
        r = requests.post(url, headers=headers,
                          json={"query": query, "variables": variables or {}}, timeout=60)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify GQL failed: {r.status_code} {r.text[:200]}")


# ── Ranking sources (pluggable) ─────────────────────────────────────────────
class RankingSource:
    """Returns {handle: unique_visitors}. Higher = more traffic."""

    def fetch(self) -> Dict[str, float]:
        raise NotImplementedError


class JSONRankingSource(RankingSource):
    """ranking.json: {"handle": <unique_visitors>, ...}.
    The shape a GA4 exporter or self-hosted counter writes."""

    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> Dict[str, float]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "rows" in data:  # tolerate {rows:[{handle,visitors}]}
            out = {}
            for row in data["rows"]:
                h = row.get("handle") or row.get("path")
                if h:
                    out[_norm_handle(h)] = float(row.get("visitors") or row.get("count") or 0)
            return out
        return {_norm_handle(k): float(v) for k, v in data.items()}


class CSVRankingSource(RankingSource):
    """Shopify Admin analytics CSV export. Auto-detects a path/handle column
    and a numeric metric column (visitors/sessions/views)."""

    PATH_HINTS = ("landing page", "page path", "path", "url", "handle", "product")
    METRIC_HINTS = ("visitor", "session", "view", "users", "traffic")

    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> Dict[str, float]:
        rows = list(csv.reader(self.path.open(encoding="utf-8-sig")))
        if not rows:
            return {}
        header = [c.strip().lower() for c in rows[0]]
        path_col = _pick_col(header, self.PATH_HINTS)
        metric_col = _pick_col(header, self.METRIC_HINTS)
        if path_col is None or metric_col is None:
            raise SystemExit(
                f"CSV: could not find path+metric columns in header {header}. "
                "Expected something like 'Landing page path' + 'Visitors'.")
        out: Dict[str, float] = {}
        for r in rows[1:]:
            if len(r) <= max(path_col, metric_col):
                continue
            h = _norm_handle(r[path_col])
            if not h:
                continue
            try:
                val = float(re.sub(r"[^0-9.]", "", r[metric_col]) or 0)
            except ValueError:
                val = 0.0
            out[h] = out.get(h, 0.0) + val
        return out


class GA4RankingSource(RankingSource):
    """Scaffold — uncomment deps to use. Pulls totalUsers per /products/ path.

    Requires:  pip install google-analytics-data
    .env:      GA4_PROPERTY_ID=123456789
               GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
    And the GA4 property must have the gtag installed on the storefront
    (theme snippet) so /products/ pageviews are collected.
    """

    def __init__(self, days: int = 30):
        self.days = days

    def fetch(self) -> Dict[str, float]:
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                DateRange, Dimension, Metric, RunReportRequest, Filter,
                FilterExpression)
        except ImportError:
            raise SystemExit("GA4 source needs: pip install google-analytics-data")
        prop = os.environ.get("GA4_PROPERTY_ID")
        if not prop:
            raise SystemExit("GA4_PROPERTY_ID missing in .env")
        client = BetaAnalyticsDataClient()
        req = RunReportRequest(
            property=f"properties/{prop}",
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="totalUsers")],
            date_ranges=[DateRange(start_date=f"{self.days}daysAgo", end_date="today")],
            dimension_filter=FilterExpression(filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.CONTAINS,
                    value="/products/"))),
            limit=1000,
        )
        resp = client.run_report(req)
        out: Dict[str, float] = {}
        for row in resp.rows:
            path = row.dimension_values[0].value
            users = float(row.metric_values[0].value or 0)
            h = _norm_handle(path)
            if h:
                out[h] = out.get(h, 0.0) + users
        return out


def _norm_handle(s: str) -> str:
    """Map a path / url / handle to a bare product handle.
    '/products/foo-bar?x=1' -> 'foo-bar' ; 'foo-bar' -> 'foo-bar'."""
    s = (s or "").strip()
    if not s:
        return ""
    m = re.search(r"/products/([^/?#]+)", s)
    if m:
        return m.group(1).strip().lower()
    if "/" in s or s.startswith("http"):
        return ""  # a non-product path
    return s.strip().lower()


def _pick_col(header: List[str], hints: Tuple[str, ...]) -> Optional[int]:
    for i, col in enumerate(header):
        if any(h in col for h in hints):
            return i
    return None


def make_source(kind: str, input_path: Optional[str], days: int) -> RankingSource:
    if kind == "json":
        return JSONRankingSource(Path(input_path))
    if kind == "csv":
        return CSVRankingSource(Path(input_path))
    if kind == "ga4":
        return GA4RankingSource(days=days)
    raise SystemExit(f"unknown --source {kind}")


# ── Product inventory scan (one pass) ───────────────────────────────────────
def scan_products(store: str, token: str) -> List[dict]:
    """Returns per-product: {id, id_short, handle, tags, has_video, in_flight}."""
    out: List[dict] = []
    cursor = None
    q = """
    query($c: String) {
      products(first: 100, after: $c) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id handle tags
          media(first: 25) { nodes { mediaContentType } }
          metafield(namespace: "custom", key: "videos") { value }
        }
      }
    }
    """
    while True:
        r = gql(store, token, q, {"c": cursor})
        pg = r["data"]["products"]
        for n in pg["nodes"]:
            tags = set(n.get("tags") or [])
            has_video_media = any(
                m.get("mediaContentType") == "VIDEO" for m in n["media"]["nodes"])
            mf_items = 0
            mfv = (n.get("metafield") or {}).get("value")
            if mfv:
                try:
                    mfj = json.loads(mfv)
                    mf_items = len(mfj.get("items") or []) if isinstance(mfj, dict) else 0
                except Exception:
                    mf_items = 0
            has_video = has_video_media or mf_items > 0 or (TAG_DONE in tags)
            in_flight = bool(tags & TAGS_IN_FLIGHT)
            out.append({
                "id": n["id"],
                "id_short": n["id"].rsplit("/", 1)[-1],
                "handle": n["handle"],
                "tags": sorted(tags),
                "has_video": has_video,
                "in_flight": in_flight,
            })
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]
    return out


def add_tag(store: str, token: str, product_gid: str, tag: str) -> List[str]:
    cur = gql(store, token, "query($id: ID!){product(id:$id){tags}}", {"id": product_gid})
    current = set((cur.get("data") or {}).get("product", {}).get("tags") or [])
    if tag in current:
        return sorted(current)
    new = sorted(current | {tag})
    r = gql(store, token,
            "mutation($i: ProductInput!){productUpdate(input:$i){userErrors{field message}}}",
            {"i": {"id": product_gid, "tags": new}})
    errs = (((r.get("data") or {}).get("productUpdate") or {}).get("userErrors") or [])
    if errs:
        print(f"      tag error: {errs}")
    return new


# ── Ledger ──────────────────────────────────────────────────────────────────
def load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"queued": {}, "runs": []}


def save_ledger(led: dict) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_FILE.write_text(json.dumps(led, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["json", "csv", "ga4"], required=True)
    ap.add_argument("--input", default=None, help="path to ranking.json / export.csv")
    ap.add_argument("--days", type=int, default=30, help="GA4 lookback window")
    ap.add_argument("--top", type=int, default=5, help="how many products to queue")
    ap.add_argument("--min-visitors", type=float, default=1.0,
                    help="ignore products below this unique-visitor count")
    ap.add_argument("--budget", type=int, default=None,
                    help="max Higgsfield credits this run may commit "
                         f"(each product = {CREDITS_PER_PRODUCT})")
    ap.add_argument("--apply", action="store_true", help="actually tag (else dry-run)")
    ap.add_argument("--generate", action="store_true",
                    help="after tagging, trigger marketing_studio_batch")
    args = ap.parse_args()

    if args.source in ("json", "csv") and not args.input:
        sys.exit(f"--source {args.source} requires --input <path>")
    load_dotenv(ENV_FILE, override=True)
    store, token = shopify_token()

    # 1. ranking
    ranking = make_source(args.source, args.input, args.days).fetch()
    if not ranking:
        print("Ranking source returned no rows. Nothing to do.")
        return 0
    print(f"Ranking source: {len(ranking)} handles with traffic data.\n")

    # 2. product inventory
    products = scan_products(store, token)
    by_handle = {p["handle"]: p for p in products}
    n_video = sum(1 for p in products if p["has_video"])
    print(f"Catalog: {len(products)} products | {n_video} already have video | "
          f"{sum(1 for p in products if p['in_flight'])} in-flight.\n")

    # 3. eligible = has traffic, no video, not in-flight
    eligible = []
    for handle, visitors in ranking.items():
        p = by_handle.get(handle)
        if not p:
            continue  # ranking handle not in catalog (renamed / stale)
        if p["has_video"] or p["in_flight"]:
            continue
        if visitors < args.min_visitors:
            continue
        eligible.append((visitors, p))
    eligible.sort(key=lambda x: x[0], reverse=True)

    if not eligible:
        print("No eligible products (every high-traffic product already has a "
              "video or is in-flight). Nothing to queue.")
        return 0

    # 4. budget cap
    top = eligible[: args.top]
    if args.budget is not None:
        max_by_budget = args.budget // CREDITS_PER_PRODUCT
        if len(top) > max_by_budget:
            print(f"Budget {args.budget} credits caps this run to {max_by_budget} "
                  f"product(s) (of {len(top)} requested).\n")
            top = top[:max_by_budget]

    credits = len(top) * CREDITS_PER_PRODUCT
    print(f"{'APPLYING' if args.apply else 'DRY-RUN'} — queue {len(top)} product(s) "
          f"(~{credits} credits):\n")
    for visitors, p in top:
        print(f"  {int(visitors):>6} uv  {p['handle'][:48]:48s}  ({p['id_short']})")

    if not args.apply:
        print("\n[dry-run] no tags written. Re-run with --apply to tag these "
              f"'{TAG_NEEDED}'.")
        return 0

    # 5. tag + ledger
    led = load_ledger()
    queued_handles = []
    for visitors, p in top:
        add_tag(store, token, p["id"], TAG_NEEDED)
        led["queued"][p["handle"]] = {
            "id": p["id_short"], "visitors": visitors,
            "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        queued_handles.append(p["handle"])
        print(f"  tagged {TAG_NEEDED}: {p['handle']}")
    led["runs"].append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": args.source, "queued": queued_handles, "credits": credits,
    })
    save_ledger(led)
    print(f"\nTagged {len(queued_handles)} product(s). Ledger: {LEDGER_FILE}")

    # 6. optional generation hand-off
    if args.generate:
        has_key = bool(os.environ.get("HIGGSFIELD_API_KEY", "").strip())
        batch = REPO_ROOT / "pipeline" / "tools" / "marketing_studio_batch.py"
        if has_key:
            print("\n--generate: HIGGSFIELD_API_KEY found → launching autonomous "
                  "generation (marketing_studio_batch --direct)...\n")
            subprocess.run([sys.executable, str(batch), "--direct",
                            "--tag", TAG_NEEDED, "--max-products", str(len(top))],
                           check=False)
        else:
            print("\n--generate: no HIGGSFIELD_API_KEY → can't auto-generate via CLI.")
            print("Generate via the chat/MCP flow instead:")
            print(f"  python {batch.relative_to(REPO_ROOT)} --list --json")
            print("  (then Claude generates the videos via the Higgsfield MCP)")
    else:
        print(f"\nNext: generate videos for the '{TAG_NEEDED}' products:")
        print("  python pipeline/tools/marketing_studio_batch.py --list")

    return 0


if __name__ == "__main__":
    sys.exit(main())
