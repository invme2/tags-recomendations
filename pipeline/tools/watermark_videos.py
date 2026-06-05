#!/usr/bin/env python3
"""watermark_videos.py — overlay a 'wanelo.com' watermark on a product's
videos, re-host the watermarked copies on Shopify Files, and repoint the
custom.videos metafield at them. ORIGINALS are kept locally untouched in
pipeline/runs/video_bundles/<handle>/current/ (so you can still improve them).

Per product:
  read live custom.videos -> for each item:
    1. download item.url      -> current/<i>_<preset>.mp4   (original, kept)
    2. ffmpeg drawtext        -> watermarked/<i>_<preset>.mp4 ('wanelo.com')
    3. upload watermarked     -> Shopify Files (VIDEO) -> poll READY -> url
    4. item.url = Shopify url  (renderer keeps showing it via the video slots)
  write metafield back.

Re-hosting on Shopify also future-proofs the videos (independent of the
Higgsfield CDN, which can expire).

USAGE:
  python pipeline/tools/watermark_videos.py --handle <handle>
  python pipeline/tools/watermark_videos.py --all
  python pipeline/tools/watermark_videos.py --handle <h> --skip-upload   # local watermark only, no Shopify write
  python pipeline/tools/watermark_videos.py --handle <h> --text "wanelo.com"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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
FONT = r"C\:/Windows/Fonts/arialbd.ttf"  # ffmpeg drawtext wants the colon escaped on Windows


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


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


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "clip"


def watermark(src: Path, dst: Path, text: str, enhance: bool = True) -> bool:
    """Enhance (optional) + overlay a FAINT, MOVING 'wanelo.com' watermark.

    The watermark is low-opacity and wanders across the whole frame over time
    (Lissajous drift) so cropping or inpainting a fixed region can't remove it.

    Enhancement (same pass): upscale to 1080-wide, light denoise, mild sharpen,
    slight contrast/saturation — makes the 720p AI render look crisper.
    """
    # faint, slowly-wandering watermark — position is a function of time t
    draw = (
        f"drawtext=fontfile='{FONT}':text='{text}':fontcolor=white@0.22:"
        f"fontsize=h/34:"
        f"x=(w-text_w)*(0.5+0.42*sin(t*0.8)):"
        f"y=(h-text_h)*(0.5+0.42*sin(t*0.55+1.2)):"
        f"shadowcolor=black@0.18:shadowx=1:shadowy=1"
    )
    if enhance:
        vf = (
            "scale=1080:-2:flags=lanczos,"
            "hqdn3d=1.5:1.5:6:6,"
            "unsharp=5:5:0.6:5:5:0.0,"
            "eq=contrast=1.04:saturation=1.06:brightness=0.01,"
            + draw
        )
    else:
        vf = draw
    cmd = [ffmpeg_exe(), "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"      ffmpeg FAIL: {r.stderr[-400:]}")
        return False
    return True


def upload_to_shopify(store, token, mp4: Path) -> Optional[str]:
    data = mp4.read_bytes()
    q = """mutation($input:[StagedUploadInput!]!){stagedUploadsCreate(input:$input){
      stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}}"""
    stage = gql(store, token, q, {"input": [{
        "filename": mp4.name, "mimeType": "video/mp4",
        "httpMethod": "POST", "resource": "VIDEO", "fileSize": str(len(data))}]})
    tg = (stage.get("data") or {}).get("stagedUploadsCreate", {}).get("stagedTargets") or []
    if not tg:
        print(f"      staged FAIL: {(stage.get('data') or {}).get('stagedUploadsCreate', {}).get('userErrors')}")
        return None
    t = tg[0]
    form = {p["name"]: p["value"] for p in t["parameters"]}
    up = requests.post(t["url"], data=form, files={"file": (mp4.name, data, "video/mp4")}, timeout=300)
    if up.status_code >= 400:
        print(f"      POST FAIL {up.status_code}")
        return None
    q2 = """mutation($f:[FileCreateInput!]!){fileCreate(files:$f){
      files{id ... on Video{id fileStatus}} userErrors{field message code}}}"""
    fc = gql(store, token, q2, {"f": [{"originalSource": t["resourceUrl"], "contentType": "VIDEO"}]})
    files = (fc.get("data") or {}).get("fileCreate", {}).get("files") or []
    if not files or not files[0].get("id"):
        print(f"      fileCreate FAIL: {(fc.get('data') or {}).get('fileCreate', {}).get('userErrors')}")
        return None
    fid = files[0]["id"]
    q3 = """query($id:ID!){node(id:$id){... on Video{fileStatus
        sources{url height format mimeType} originalSource{url}}}}"""
    for _ in range(60):
        time.sleep(4)
        n = (gql(store, token, q3, {"id": fid}).get("data") or {}).get("node") or {}
        if n.get("fileStatus") == "READY":
            # pick the highest-resolution MP4 rendition (Shopify also makes a
            # low SD-480p + an HLS m3u8; we want the best progressive mp4)
            mp4s = [s for s in (n.get("sources") or [])
                    if (s.get("format") == "mp4" or "mp4" in (s.get("mimeType") or ""))]
            if mp4s:
                return max(mp4s, key=lambda s: s.get("height") or 0).get("url")
            return (n.get("originalSource") or {}).get("url")
        if n.get("fileStatus") == "FAILED":
            return None
    return None


def process(store, token, handle, text, skip_upload, enhance) -> int:
    r = gql(store, token,
            'query($h:String!){productByHandle(handle:$h){id metafield(namespace:"custom",key:"videos"){value}}}',
            {"h": handle})
    p = r["data"]["productByHandle"]
    if not p:
        print(f"  {handle}: not found"); return 0
    gid = p["id"]
    raw = (p.get("metafield") or {}).get("value")
    if not raw:
        print(f"  {handle}: no custom.videos"); return 0
    payload = json.loads(raw)
    items = payload.get("items") or []
    folder = BUNDLE_DIR / handle
    (folder / "current").mkdir(parents=True, exist_ok=True)
    (folder / "watermarked").mkdir(parents=True, exist_ok=True)

    done = 0
    for i, it in enumerate(items):
        url = it.get("url", "")
        if not url:
            continue
        preset = it.get("preset") or f"video{i}"
        name = f"{i}_{slug(preset)}.mp4"
        orig = folder / "current" / name
        wm = folder / "watermarked" / name
        # 1. ensure original kept
        if not orig.exists():
            try:
                orig.write_bytes(requests.get(url, timeout=180).content)
            except Exception as e:
                print(f"  [{i}] {preset}: download FAIL {str(e)[:80]}"); continue
        # 2. watermark (+ optional enhance)
        if not watermark(orig, wm, text, enhance):
            continue
        print(f"  [{i}] {preset}: watermarked ({wm.stat().st_size//1024} KB)")
        # 3. upload + repoint
        if not skip_upload:
            shop_url = upload_to_shopify(store, token, wm)
            if shop_url:
                it["url"] = shop_url
                it["video_id"] = "shopify-file-wm"
                it["platform"] = "higgsfield-mp4"
                done += 1
                print(f"       -> Shopify: ...{shop_url[-40:]}")
            else:
                print(f"       upload failed, keeping original url")

    if done and not skip_upload:
        payload["items"] = items
        sq = ("mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){"
              "metafields{id} userErrors{field message code}}}")
        s = gql(store, token, sq, {"m": [{
            "ownerId": gid, "namespace": "custom", "key": "videos",
            "type": "json", "value": json.dumps(payload, ensure_ascii=False)}]})
        errs = s["data"]["metafieldsSet"]["userErrors"]
        print(f"  metafield repointed to {done} watermarked video(s)" if not errs else f"  errs:{errs}")
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--handle", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--text", default="wanelo.com")
    ap.add_argument("--skip-upload", action="store_true")
    ap.add_argument("--no-enhance", action="store_true", help="skip upscale/denoise/sharpen, watermark only")
    args = ap.parse_args()
    if not args.handle and not args.all:
        sys.exit("pass --handle <h> or --all")
    load_env()
    store, token = get_token()
    handles = ([args.handle] if args.handle
               else [d.name for d in BUNDLE_DIR.iterdir() if d.is_dir()] if BUNDLE_DIR.exists() else [])
    total = 0
    for h in handles:
        print(f"\n→ {h}")
        total += process(store, token, h, args.text, args.skip_upload, not args.no_enhance)
    print(f"\nWatermarked + re-hosted: {total}{'  [skip-upload]' if args.skip_upload else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
