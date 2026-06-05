"""bundle_photo_packs.py — assemble a single master ZIP containing one
folder per product (photos + prompt.txt + manifest.json), pulled from
each product's `custom.photo_pack` URL in Shopify Files.

WHY: the pipeline writes individual per-product photo_pack ZIPs as
`custom.photo_pack` (admin-only). The operator wants ONE archive with
all batches' photos so he can edit them in bulk on disk, then re-upload
via `upload_edited_photos.py`.

USAGE:
    # Bundle every product that has a custom.photo_pack URL
    python pipeline/tools/bundle_photo_packs.py

    # Bundle only products created in the last 14 days
    python pipeline/tools/bundle_photo_packs.py --since-days 14

    # Bundle only products from a specific local run dir (uses pipeline.db
    # to filter to that batch)
    python pipeline/tools/bundle_photo_packs.py --run beauty-essentials

    # Bundle a specific list of Shopify product IDs (numeric)
    python pipeline/tools/bundle_photo_packs.py --product-ids 1234,5678

OUTPUT (default `runs/<name>/photo_pack_master_<timestamp>.zip` or
`./photo_pack_master_<timestamp>.zip` if --run not given):

    photo_pack_master_20260527_104500.zip
    ├── manifest.json                       # folder → {shopify_product_id, eprolo_url, title, handle}
    ├── 8889396__crest-3d-white-strips/
    │   ├── prompt.txt                      # photo-editor instructions (copy to ChatGPT)
    │   ├── README.md                       # operator workflow notes
    │   ├── manifest.json                   # per-product audit (slot, brief, source)
    │   └── photos/
    │       ├── 01-carousel-hero.jpg
    │       ├── 02-carousel-lifestyle.jpg
    │       └── ...
    └── 8889396265138__teeth-whitening-kit/
        └── ...

Folder names are deterministic and human-readable so you can spot products
visually while editing. `manifest.json` at root authoritatively maps
folder name → shopify_product_id for `upload_edited_photos.py`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timedelta
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
RUNS_DIR = REPO_ROOT / "pipeline" / "runs"

API_VERSION = "2024-10"


# ── Shopify auth ────────────────────────────────────────────────────────────
def get_shopify_token() -> Tuple[str, str]:
    """Return (store_domain, admin_token). Exchanges client_credentials if
    SHOPIFY_ACCESS_TOKEN not preset; OAuth token TTL is 24h."""
    store = os.environ["SHOPIFY_STORE"]
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not token:
        cid = os.environ["SHOPIFY_CLIENT_ID"]
        sec = os.environ["SHOPIFY_CLIENT_SECRET"]
        r = requests.post(
            f"https://{store}/admin/oauth/access_token",
            json={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
    return store, token


def shopify_gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    """5 req/sec hard cap; basic retry on 429."""
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    body = {"query": query, "variables": variables or {}}
    for attempt in range(4):
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify GQL failed after retries: {r.status_code} {r.text[:200]}")


# ── Product discovery ───────────────────────────────────────────────────────
def list_products_with_photopack(
    store: str, token: str,
    since_days: Optional[int] = None,
    product_ids: Optional[List[str]] = None,
    db_path: Optional[Path] = None,
) -> List[dict]:
    """Return [{id, title, handle, photo_pack_url, eprolo_url}] for every
    product that has a `custom.photo_pack` URL set."""
    if db_path and db_path.exists():
        # Local DB filter: only include products this DB knows about
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT shopify_product_id, eprolo_url, name FROM products "
            "WHERE shopify_product_id IS NOT NULL AND shopify_product_id != ''"
        ).fetchall()
        conn.close()
        wanted_ids = {r["shopify_product_id"] for r in rows}
        url_map = {r["shopify_product_id"]: r["eprolo_url"] for r in rows}
        print(f"  filter: only {len(wanted_ids)} products from {db_path}")
    else:
        wanted_ids = None
        url_map = {}

    # Paginate via products query — include photo_pack + source_url metafields
    products: List[dict] = []
    cursor = None
    q_filter = ""
    if since_days:
        cutoff = (datetime.utcnow() - timedelta(days=since_days)).strftime("%Y-%m-%d")
        q_filter = f'created_at:>={cutoff}'
    while True:
        query = """
        query($cursor: String, $q: String) {
          products(first: 50, after: $cursor, query: $q) {
            edges {
              cursor
              node {
                id
                title
                handle
                photopack: metafield(namespace: "custom", key: "photo_pack") { value }
                source_url: metafield(namespace: "custom", key: "source_url") { value }
                source: metafield(namespace: "custom", key: "source") { value }
              }
            }
            pageInfo { hasNextPage }
          }
        }
        """
        r = shopify_gql(store, token, query, {"cursor": cursor, "q": q_filter or None})
        edges = r.get("data", {}).get("products", {}).get("edges", [])
        for e in edges:
            n = e["node"]
            pid = n["id"]
            pid_num = pid.rsplit("/", 1)[-1]
            if product_ids and pid_num not in product_ids:
                continue
            if wanted_ids and pid not in wanted_ids:
                continue
            pack = (n.get("photopack") or {}).get("value", "") or ""
            if not pack.startswith("http"):
                continue
            # Resolve EPROLO URL: prefer source_url metafield → source JSON → local DB
            eprolo = (n.get("source_url") or {}).get("value", "") or ""
            if not eprolo:
                src_raw = (n.get("source") or {}).get("value", "") or ""
                if src_raw:
                    try:
                        eprolo = json.loads(src_raw).get("url", "")
                    except Exception:
                        pass
            if not eprolo:
                eprolo = url_map.get(pid, "")
            products.append({
                "id": pid, "id_short": pid_num, "title": n["title"], "handle": n["handle"],
                "photo_pack_url": pack, "eprolo_url": eprolo,
            })
        page = r.get("data", {}).get("products", {}).get("pageInfo", {})
        if not page.get("hasNextPage"):
            break
        cursor = edges[-1]["cursor"]
    return products


# ── Master ZIP assembly ─────────────────────────────────────────────────────
_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def safe_folder_name(pid_short: str, title: str, max_len: int = 30) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")[:max_len].strip("-")
    if not slug:
        slug = "product"
    return f"{pid_short}__{slug}"


def download_zip(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"    DOWNLOAD FAIL: {str(e)[:120]}")
        return None


def repack_into_master(products: List[dict], out_zip_path: Path) -> Tuple[int, int]:
    """Download each per-product ZIP, unpack contents into master ZIP under
    a deterministic folder. Returns (ok_count, fail_count)."""
    out_zip_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "shopify_store": os.environ.get("SHOPIFY_STORE", ""),
        "folders": {},
    }
    ok = 0
    fail = 0
    with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_DEFLATED) as out_zip:
        for i, p in enumerate(products, 1):
            folder = safe_folder_name(p["id_short"], p["title"])
            print(f"  [{i:3d}/{len(products)}] {folder}")
            print(f"      pack url: {p['photo_pack_url'][:70]}...")
            blob = download_zip(p["photo_pack_url"])
            if blob is None:
                fail += 1
                continue
            # Open inner ZIP, copy each entry into master under <folder>/
            try:
                with zipfile.ZipFile(io.BytesIO(blob)) as inner:
                    n_entries = 0
                    for name in inner.namelist():
                        if name.endswith("/"):
                            continue
                        data = inner.read(name)
                        # inner ZIPs put photos under photos/, plus prompt.txt /
                        # README.md / manifest.json at root. Preserve structure
                        # by prefixing with our folder name.
                        out_zip.writestr(f"{folder}/{name}", data)
                        n_entries += 1
                    print(f"      packed: {n_entries} files")
            except zipfile.BadZipFile:
                print(f"      BAD ZIP — skipped")
                fail += 1
                continue
            manifest["folders"][folder] = {
                "shopify_product_id": p["id"],
                "shopify_product_id_short": p["id_short"],
                "title": p["title"],
                "handle": p["handle"],
                "eprolo_url": p["eprolo_url"],
                "photo_pack_url": p["photo_pack_url"],
            }
            ok += 1
        # Root manifest.json — primary source of truth for upload_edited_photos.py
        out_zip.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return ok, fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since-days", type=int, default=None,
                        help="only include products created within last N days")
    parser.add_argument("--product-ids", default=None,
                        help="comma-separated Shopify product IDs (numeric, e.g. 8889396002994)")
    parser.add_argument("--run", default=None,
                        help="local run-dir name under runs/ — uses runs/<name>/.db/pipeline.db "
                             "to filter to products from that batch, and writes master ZIP into runs/<name>/")
    parser.add_argument("--out", type=Path, default=None,
                        help="explicit output ZIP path (overrides default)")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)

    store, token = get_shopify_token()
    print(f"Shopify: {store} (token: {token[:6]}...{token[-4:]})")

    db_path = None
    out_dir = REPO_ROOT
    if args.run:
        run_dir = RUNS_DIR / args.run
        if not run_dir.exists():
            sys.exit(f"--run dir not found: {run_dir}")
        db_path = run_dir / ".db" / "pipeline.db"
        if not db_path.exists():
            print(f"  warning: {db_path} not found — listing ALL products from Shopify instead")
            db_path = None
        out_dir = run_dir

    pids = [s.strip() for s in (args.product_ids or "").split(",") if s.strip()] or None

    print("Listing products with custom.photo_pack ...")
    products = list_products_with_photopack(
        store, token, since_days=args.since_days, product_ids=pids, db_path=db_path,
    )
    if not products:
        print("No products with custom.photo_pack found. Nothing to bundle.")
        return 0
    print(f"Found {len(products)} products with a photo_pack URL.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (out_dir / f"photo_pack_master_{ts}.zip")
    print(f"\nBundling into {out_path} ...")
    ok, fail = repack_into_master(products, out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\nDone: {ok} packed, {fail} failed | {size_mb:.1f} MB")
    print(f"\nMaster ZIP: {out_path}")
    print(f"  Extract, edit photos in each folder, then push back via:")
    print(f"  python pipeline/tools/upload_edited_photos.py --folder <extracted-path> --replace")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
