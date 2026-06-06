#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_failed_media_staged.py — re-upload product images that Shopify's URL
fetcher rejected (EPROLO/Aliyun CDN serves them as application/octet-stream, so
productCreateMedia(originalSource=url) ends in status FAILED). Downloads the
bytes locally, detects the real image type, pushes them through Shopify staged
uploads with a proper mimeType, then attaches the Shopify-hosted files.

Targeted: pass --gid + --run-db + --name-like (defaults to the Cold Compress
product). Deletes existing FAILED media first.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, time
import requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=60).json()


def detect(b):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/jpeg", "jpg"


def stage_upload(tok, fname, mime, data):
    r = gql(tok, """mutation($input:[StagedUploadInput!]!){stagedUploadsCreate(input:$input){
        stagedTargets{url resourceUrl parameters{name value}} userErrors{message}}}""",
        {"input": [{"filename": fname, "mimeType": mime, "resource": "IMAGE", "httpMethod": "POST"}]})
    t = (((r.get("data") or {}).get("stagedUploadsCreate") or {}).get("stagedTargets") or [None])[0]
    if not t:
        return None
    files = {p["name"]: (None, p["value"]) for p in t["parameters"]}
    files["file"] = (fname, data, mime)
    up = requests.post(t["url"], files=files, timeout=60)
    if up.status_code not in (200, 201, 204):
        print(f"    ! staged POST {up.status_code}")
        return None
    return t["resourceUrl"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gid", default=None)
    ap.add_argument("--run-db", default="runs/health-care-chunk2-2026-06-01/.db/pipeline.db")
    ap.add_argument("--name-like", default="Cold Compress Foot Massager")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    tok = token()
    gid = args.gid
    if not gid and Path("pipeline/tools/_nofeat.json").exists():
        try:
            gid = json.load(open("pipeline/tools/_nofeat.json"))[0]
        except Exception:
            pass
    if not gid:
        raise SystemExit("no --gid")

    c = sqlite3.connect(f"file:{Path(args.run_db).as_posix()}?mode=ro", uri=True)
    row = c.execute("SELECT image_urls_json FROM products WHERE name LIKE ?", (f"%{args.name_like}%",)).fetchone()
    c.close()
    urls = [re.sub(r"\?.*$", "", x.get("url")) for x in (json.loads(row[0] or "{}").get("top") or []) if x.get("url")][:12]
    print(f"product {gid} | source urls: {len(urls)} | {'EXECUTE' if args.execute else 'DRY-RUN'}")
    if not args.execute:
        print("DRY-RUN — add --execute"); return 0

    # delete current (failed) media
    p = gql(tok, "query($id:ID!){product(id:$id){media(first:50){nodes{id}}}}", {"id": gid})
    failed = [m["id"] for m in (((p.get("data") or {}).get("product") or {}).get("media") or {}).get("nodes", [])]
    if failed:
        gql(tok, "mutation($id:ID!,$m:[ID!]!){productDeleteMedia(productId:$id,mediaIds:$m){deletedMediaIds userErrors{message}}}", {"id": gid, "m": failed})
        print(f"  deleted {len(failed)} failed media")
        time.sleep(1)

    # download + stage
    resource_urls = []
    with requests.Session() as s:
        for i, u in enumerate(urls):
            try:
                b = s.get(u, timeout=30).content
            except Exception as e:
                print(f"    ! download {i}: {str(e)[:50]}"); continue
            if len(b) < 1000:
                continue
            mime, ext = detect(b)
            ru = stage_upload(tok, f"img-{i+1:02d}.{ext}", mime, b)
            if ru:
                resource_urls.append(ru)
            time.sleep(0.2)
    print(f"  staged {len(resource_urls)}/{len(urls)} images")
    if not resource_urls:
        print("  nothing staged — abort"); return 1

    media = [{"originalSource": ru, "mediaContentType": "IMAGE", "alt": args.name_like} for ru in resource_urls]
    rc = gql(tok, """mutation($id:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$id,media:$m){
        media{id} mediaUserErrors{message}}}""", {"id": gid, "m": media})
    d = (rc.get("data") or {}).get("productCreateMedia") or {}
    print(f"  created {len(d.get('media') or [])} | errors {d.get('mediaUserErrors') or 'none'}")
    time.sleep(10)
    p2 = gql(tok, "query($id:ID!){product(id:$id){featuredMedia{id} media(first:3){nodes{status ... on MediaImage{image{url}}}}}}", {"id": gid})
    pp = (p2.get("data") or {}).get("product") or {}
    print(f"  featuredMedia now: {bool(pp.get('featuredMedia'))} | first: {[(m.get('status'), bool(m.get('image'))) for m in (pp.get('media') or {}).get('nodes', [])]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
