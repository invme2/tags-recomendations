#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme_edit.py — small helper: fetch / snapshot / upload a live theme asset
via the Shopify Asset REST API. Reusable for surgical Liquid/template edits.
Snapshots every fetched asset to pipeline/theme_assets/.snapshots/ before any
upload so edits are reversible.
"""
from __future__ import annotations
import os, time, requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
BASE = f"https://{STORE}/admin/api/2024-10"
SNAP = ROOT / "pipeline" / "theme_assets" / ".snapshots"


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def main_theme_id(tok):
    th = requests.get(f"{BASE}/themes.json", headers={"X-Shopify-Access-Token": tok}, timeout=30).json()["themes"]
    return next(t["id"] for t in th if t.get("role") == "main")


def fetch(tok, tid, key):
    r = requests.get(f"{BASE}/themes/{tid}/assets.json", headers={"X-Shopify-Access-Token": tok},
                     params={"asset[key]": key}, timeout=30).json()
    return (r.get("asset") or {}).get("value") or ""


def snapshot(key, value, ts):
    SNAP.mkdir(parents=True, exist_ok=True)
    safe = key.replace("/", "__")
    p = SNAP / f"{ts}_{safe}"
    p.write_text(value, encoding="utf-8")
    return p


def upload(tok, tid, key, value):
    r = requests.put(f"{BASE}/themes/{tid}/assets.json",
                     headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                     json={"asset": {"key": key, "value": value}}, timeout=40)
    return r.status_code, r.json()
