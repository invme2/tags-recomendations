#!/usr/bin/env python3
"""upload_theme_assets.py — PUT local theme files to a Shopify theme via the
Asset REST API. Used to ship edits in pipeline/theme_assets/ to the live theme.

OAuth via client_credentials (same token exchange as resume_with_retries).
Maps each local file under pipeline/theme_assets/ to its theme asset key
(sections/..., snippets/..., assets/...).

USAGE:
  python pipeline/tools/upload_theme_assets.py --theme 153321242802 \
      snippets/wanelo-icon.liquid sections/wanelo-collection-grid.liquid

  # or upload every changed file passed as relative-to-theme_assets keys.
"""
from __future__ import annotations

import argparse
import os
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
THEME_ASSETS = REPO_ROOT / "pipeline" / "theme_assets"
API_VERSION = "2024-10"


def get_token() -> tuple[str, str]:
    load_dotenv(ENV_FILE, override=True)
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    return store, r.json()["access_token"]


def put_asset(store: str, token: str, theme: str, key: str, value: str) -> tuple[bool, str]:
    url = f"https://{store}/admin/api/{API_VERSION}/themes/{theme}/assets.json"
    r = requests.put(url,
                     headers={"X-Shopify-Access-Token": token,
                              "Content-Type": "application/json"},
                     json={"asset": {"key": key, "value": value}}, timeout=60)
    if r.status_code in (200, 201):
        return True, "ok"
    return False, f"{r.status_code}: {r.text[:300]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theme", required=True, help="Shopify theme id")
    ap.add_argument("keys", nargs="+",
                    help="asset keys relative to theme_assets/ (e.g. snippets/x.liquid)")
    args = ap.parse_args()

    store, token = get_token()
    ok = 0
    for key in args.keys:
        path = THEME_ASSETS / key
        if not path.exists():
            print(f"[skip] {key}: local file missing ({path})")
            continue
        value = path.read_text(encoding="utf-8")
        good, msg = put_asset(store, token, args.theme, key, value)
        flag = "OK " if good else "ERR"
        print(f"[{flag}] {key} ({len(value)} bytes) {msg if not good else ''}".rstrip())
        ok += 1 if good else 0
        time.sleep(0.4)
    print(f"\n[done] {ok}/{len(args.keys)} assets uploaded to theme {args.theme}.")
    return 0 if ok == len(args.keys) else 1


if __name__ == "__main__":
    sys.exit(main())
