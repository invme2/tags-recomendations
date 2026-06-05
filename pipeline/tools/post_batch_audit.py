#!/usr/bin/env python3
"""post_batch_audit.py — health check on every live product after a batch.

Runs 9 critical sanity checks per product + summarizes failures. Catches
the kinds of bugs we hit during initial launch:
  - $329.90 mispriced product (MAX-cost scrape bug)
  - Crest 3D White with 0 photos (CDN whitelist too narrow)
  - Products invisible on storefront (no publication on Online Store)
  - Out-of-stock badge (inventory policy DENY)

Exit code:
  0 = all green
  1 = WARN-level issues (review recommended)
  2 = FAIL-level issues (immediate fix needed)

USAGE:
  python pipeline/tools/post_batch_audit.py                 # all live products
  python pipeline/tools/post_batch_audit.py --pid 8892...   # one product
  python pipeline/tools/post_batch_audit.py --csv out.csv   # export CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
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

# Thresholds — adjust if business model changes
PRICE_MIN = 7.90        # below = suspect (cost detection failed)
PRICE_MAX = 399.90      # above = suspect. Premium LED devices + 20-pack
                        # bundles legitimately reach $200-300, so the
                        # threshold sits above those to avoid false-positives.
MIN_METAFIELDS = 11     # designer should fill ≥11 sections per product
MIN_MEDIA_ITEMS = 3     # at least 3 photos for credible product
REQUIRED_PUBLICATIONS = {"Online Store", "Shop"}


@dataclass
class Issue:
    severity: str   # 'FAIL' or 'WARN'
    code: str
    detail: str


@dataclass
class ProductReport:
    pid: str
    handle: str
    title: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(i.severity == "FAIL" for i in self.issues):
            return "FAIL"
        if any(i.severity == "WARN" for i in self.issues):
            return "WARN"
        return "OK"


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


PROD_QUERY = """
query($id: ID!) {
  product(id: $id) {
    id handle title status totalInventory
    variants(first: 5) {
      nodes {
        price compareAtPrice
        inventoryPolicy
        inventoryItem { tracked unitCost { amount } }
      }
    }
    media(first: 50) { nodes { mediaContentType } }
    resourcePublications(first: 10) {
      nodes { publication { name } isPublished }
    }
    metafields(first: 100, namespace: "custom") {
      edges { node { key type } }
    }
  }
}
"""


def audit_product(store: str, token: str, pid: str) -> ProductReport:
    """Run 9 checks on one product. Return report with issues found."""
    r = gql(store, token, PROD_QUERY, {"id": pid})
    p = r.get("data", {}).get("product")
    if not p:
        rep = ProductReport(pid=pid.split("/")[-1], handle="?", title="?")
        rep.issues.append(Issue("FAIL", "PRODUCT_NOT_FOUND", f"Could not load {pid}"))
        return rep

    rep = ProductReport(pid=p["id"].split("/")[-1], handle=p["handle"],
                        title=p["title"])

    # Check 1: status must be ACTIVE
    if p["status"] != "ACTIVE":
        rep.issues.append(Issue("FAIL", "STATUS_NOT_ACTIVE",
                                f"product.status = {p['status']}, expected ACTIVE"))

    # Check 2: published on Online Store + Shop
    pub_names = {n["publication"]["name"] for n in p["resourcePublications"]["nodes"]
                 if n["isPublished"]}
    missing_pubs = REQUIRED_PUBLICATIONS - pub_names
    if missing_pubs:
        rep.issues.append(Issue("FAIL", "NOT_PUBLISHED",
                                f"missing publications: {sorted(missing_pubs)} "
                                f"(have {sorted(pub_names)})"))

    # Check 3 & 4: variant inventory policy + tracking
    variants = p["variants"]["nodes"]
    for v in variants:
        if v["inventoryPolicy"] != "CONTINUE":
            rep.issues.append(Issue("WARN", "INVENTORY_POLICY_DENY",
                                    f"variant inventoryPolicy={v['inventoryPolicy']}, "
                                    "expected CONTINUE (else Out of Stock badge)"))
        if v["inventoryItem"]["tracked"]:
            rep.issues.append(Issue("WARN", "INVENTORY_TRACKED",
                                    "variant inventoryItem.tracked=True, "
                                    "expected False for unlimited dropship inventory"))

    # Check 5: price sanity range
    for v in variants:
        try:
            price = float(v["price"])
        except (TypeError, ValueError):
            rep.issues.append(Issue("FAIL", "PRICE_INVALID",
                                    f"variant price={v.get('price')!r}"))
            continue
        if price < PRICE_MIN:
            rep.issues.append(Issue("WARN", "PRICE_TOO_LOW",
                                    f"${price:.2f} < ${PRICE_MIN} (cost detection may have failed)"))
        elif price > PRICE_MAX:
            rep.issues.append(Issue("FAIL", "PRICE_TOO_HIGH",
                                    f"${price:.2f} > ${PRICE_MAX} (MAX-cost bug suspect)"))

    # Check 6: at least 3 media items (photos OR videos)
    n_media = len(p["media"]["nodes"])
    if n_media < MIN_MEDIA_ITEMS:
        sev = "FAIL" if n_media == 0 else "WARN"
        rep.issues.append(Issue(sev, "LOW_MEDIA",
                                f"only {n_media} media items, expected ≥{MIN_MEDIA_ITEMS}"))

    # Check 7: enough metafields
    n_mf = len(p["metafields"]["edges"])
    if n_mf < MIN_METAFIELDS:
        rep.issues.append(Issue("WARN", "LOW_METAFIELDS",
                                f"only {n_mf} custom.* metafields, expected ≥{MIN_METAFIELDS}"))

    # Check 8: required core sections present
    mf_keys = {e["node"]["key"] for e in p["metafields"]["edges"]}
    REQUIRED_CORE = {"hero", "story", "features"}
    missing_core = REQUIRED_CORE - mf_keys
    if missing_core:
        rep.issues.append(Issue("FAIL", "MISSING_CORE_SECTIONS",
                                f"missing required sections: {sorted(missing_core)}"))

    # Check 9: compare-at must be ≥ price (so strikethrough shows)
    for v in variants:
        try:
            price = float(v["price"])
            cp = float(v.get("compareAtPrice") or 0)
            if cp and cp <= price:
                rep.issues.append(Issue("WARN", "COMPARE_AT_TOO_LOW",
                                        f"compareAtPrice ${cp:.2f} ≤ price ${price:.2f} "
                                        "(no strikethrough discount visual)"))
        except (TypeError, ValueError):
            pass

    return rep


def fetch_all_pids(store: str, token: str) -> list[str]:
    pids: list[str] = []
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
    return pids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=str, default=None,
                        help="Audit one product (numeric PID, no gid:// prefix)")
    parser.add_argument("--csv", type=Path, default=None,
                        help="Export full report to CSV")
    args = parser.parse_args()

    load_env()
    store, token = get_token()

    if args.pid:
        pids = [f"gid://shopify/Product/{args.pid}"]
    else:
        pids = fetch_all_pids(store, token)
        print(f"Auditing {len(pids)} live products...\n")

    reports: list[ProductReport] = []
    n_fail = n_warn = n_ok = 0
    for i, pid in enumerate(pids, 1):
        rep = audit_product(store, token, pid)
        reports.append(rep)
        status = rep.status
        if status == "FAIL":
            n_fail += 1
        elif status == "WARN":
            n_warn += 1
        else:
            n_ok += 1
        marker = {"OK": "\033[92m OK \033[0m",
                  "WARN": "\033[93mWARN\033[0m",
                  "FAIL": "\033[91mFAIL\033[0m"}[status]
        print(f"  [{i:3d}/{len(pids)}] {marker}  {rep.handle[:50]:50s}  "
              f"({len(rep.issues)} issues)")
        for iss in rep.issues:
            sev_mark = "\033[91m✗\033[0m" if iss.severity == "FAIL" else "\033[93m!\033[0m"
            print(f"           {sev_mark} {iss.code}: {iss.detail}")

    print(f"\n{'=' * 60}")
    print(f"  \033[92mOK\033[0m: {n_ok:3d}  \033[93mWARN\033[0m: {n_warn:3d}  \033[91mFAIL\033[0m: {n_fail:3d}  /  {len(reports)} total")

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["pid", "handle", "title", "status", "issue_code",
                        "severity", "detail"])
            for rep in reports:
                if not rep.issues:
                    w.writerow([rep.pid, rep.handle, rep.title, rep.status, "",
                                "", ""])
                else:
                    for iss in rep.issues:
                        w.writerow([rep.pid, rep.handle, rep.title, rep.status,
                                    iss.code, iss.severity, iss.detail])
        print(f"\n  CSV written: {args.csv}")

    if n_fail > 0:
        return 2
    if n_warn > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
