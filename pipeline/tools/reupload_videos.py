#!/usr/bin/env python3
"""reupload_videos.py — swap improved video clips into a product's video
metafield. Companion to video_bundle_archive.py.

Reads pipeline/runs/video_bundles/<handle>/improved/*.mp4, where each file
is named by the slot index it replaces (leading number: `0.mp4`, `3_v2.mp4`).
For each improved clip:
  1. upload to Shopify Files as VIDEO (staged upload → fileCreate → poll READY)
  2. swap custom.videos.items[index].url to the new Shopify-hosted URL
The distributed video slots on the product page pick up the new URL.

After a successful swap the improved file is moved to improved/_applied/ so
re-runs don't re-upload it.

USAGE:
  python pipeline/tools/reupload_videos.py --handle <handle>
  python pipeline/tools/reupload_videos.py --all          # every bundle folder with improved/*.mp4
  python pipeline/tools/reupload_videos.py --handle <h> --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
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
BUNDLE_DIR = REPO_ROOT / "pipeline" / "runs" / "video_bundles"
API_VERSION = "2024-10"


def load_env() -> None:
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
    for attempt in range(4):
        r = requests.post(url, headers=headers,
                          json={"query": query, "variables": variables or {}}, timeout=60)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"GQL failed: {r.status_code}")


def upload_video_to_shopify(store, token, mp4_path: Path) -> Optional[str]:
    """Staged upload an mp4 to Shopify Files as VIDEO → poll READY → return URL."""
    video_bytes = mp4_path.read_bytes()
    print(f"      uploading {mp4_path.name} ({len(video_bytes)/1024/1024:.1f} MB)...")
    q = """mutation($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets { url resourceUrl parameters { name value } }
        userErrors { field message } } }"""
    stage = gql(store, token, q, {"input": [{
        "filename": mp4_path.name, "mimeType": "video/mp4",
        "httpMethod": "POST", "resource": "VIDEO", "fileSize": str(len(video_bytes))}]})
    targets = (stage.get("data") or {}).get("stagedUploadsCreate", {}).get("stagedTargets") or []
    if not targets:
        print(f"      staged FAIL: {(stage.get('data') or {}).get('stagedUploadsCreate', {}).get('userErrors')}")
        return None
    t = targets[0]
    form = {p["name"]: p["value"] for p in t["parameters"]}
    up = requests.post(t["url"], data=form,
                       files={"file": (mp4_path.name, video_bytes, "video/mp4")}, timeout=300)
    if up.status_code >= 400:
        print(f"      POST FAIL {up.status_code}")
        return None
    q2 = """mutation($f: [FileCreateInput!]!) {
      fileCreate(files: $f) { files { id ... on Video { id fileStatus } }
        userErrors { field message code } } }"""
    fc = gql(store, token, q2, {"f": [{"originalSource": t["resourceUrl"], "contentType": "VIDEO"}]})
    files = (fc.get("data") or {}).get("fileCreate", {}).get("files") or []
    if not files or not files[0].get("id"):
        print(f"      fileCreate FAIL: {(fc.get('data') or {}).get('fileCreate', {}).get('userErrors')}")
        return None
    file_id = files[0]["id"]
    q3 = """query($id: ID!){ node(id:$id){ ... on Video {
        fileStatus sources { url } originalSource { url } } } }"""
    for _ in range(60):  # ~4 min
        time.sleep(4)
        n = (gql(store, token, q3, {"id": file_id}).get("data") or {}).get("node") or {}
        if n.get("fileStatus") == "READY":
            src = ((n.get("sources") or [{}])[0].get("url")
                   or (n.get("originalSource") or {}).get("url"))
            print(f"      ✓ READY")
            return src
        if n.get("fileStatus") == "FAILED":
            print(f"      transcode FAILED")
            return None
    print(f"      timed out")
    return None


def process_folder(store, token, folder: Path, dry_run: bool) -> int:
    mf_path = folder / "manifest.json"
    improved = folder / "improved"
    if not mf_path.exists() or not improved.exists():
        return 0
    clips = [f for f in improved.glob("*.mp4") if f.is_file()]
    if not clips:
        return 0
    manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    gid = manifest["gid"]
    print(f"\n→ {folder.name}: {len(clips)} improved clip(s)")

    # current metafield
    r = gql(store, token,
            'query($id:ID!){product(id:$id){metafield(namespace:"custom",key:"videos"){value}}}',
            {"id": gid})
    raw = (((r.get("data") or {}).get("product") or {}).get("metafield") or {}).get("value")
    payload = json.loads(raw) if raw else {"head": {"kicker": "WATCH IN ACTION"}, "items": []}
    items = payload.get("items") or []

    applied = 0
    for clip in sorted(clips):
        m = re.match(r"(\d+)", clip.name)
        if not m:
            print(f"  SKIP {clip.name}: no leading index number")
            continue
        idx = int(m.group(1))
        if idx >= len(items):
            print(f"  SKIP {clip.name}: index {idx} out of range ({len(items)} items)")
            continue
        print(f"  slot {idx} ({items[idx].get('preset','?')}) ← {clip.name}")
        if dry_run:
            print("    [dry-run] would upload + swap")
            continue
        url = upload_video_to_shopify(store, token, clip)
        if not url:
            print(f"    upload failed, leaving slot unchanged")
            continue
        items[idx]["url"] = url
        items[idx]["video_id"] = "shopify-file"
        items[idx]["platform"] = "higgsfield-mp4"  # renderer routes any .mp4 url to <video>
        applied += 1
        done_dir = improved / "_applied"
        done_dir.mkdir(exist_ok=True)
        clip.rename(done_dir / clip.name)

    if applied and not dry_run:
        payload["items"] = items
        sq = ("mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){"
              "metafields{id} userErrors{field message code}}}")
        s = gql(store, token, sq, {"m": [{
            "ownerId": gid, "namespace": "custom", "key": "videos",
            "type": "json", "value": json.dumps(payload, ensure_ascii=False)}]})
        errs = s["data"]["metafieldsSet"]["userErrors"]
        print(f"  metafield updated ({applied} swapped)" if not errs else f"  errs: {errs}")
    return applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--handle", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.handle and not args.all:
        sys.exit("pass --handle <h> or --all")
    load_env()
    store, token = get_token()

    folders = ([BUNDLE_DIR / args.handle] if args.handle
               else [d for d in BUNDLE_DIR.iterdir() if d.is_dir()] if BUNDLE_DIR.exists() else [])
    total = 0
    for f in folders:
        total += process_folder(store, token, f, args.dry_run)
    print(f"\nTotal swapped: {total}{'  [dry-run]' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
