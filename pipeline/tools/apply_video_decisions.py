"""apply_video_decisions.py — push approved videos to Shopify based on
decisions.json files produced by the HTML review feed.

WORKFLOW
========
1. After `marketing_studio_batch.py` ran, you opened the HTML feed in
   browser, marked Carousel / Metafield / Skip per video, hit "Save".
2. decisions.json downloaded to your machine. Drop it into the matching
   product folder: pipeline/runs/video_feed/<product_id>/decisions.json
3. Run this script:
     python pipeline/tools/apply_video_decisions.py            # all ready
     python pipeline/tools/apply_video_decisions.py --product-id 8889680691378

WHAT IT DOES (per product, per video decision)
==============================================
  decision == "carousel":
    - Download mp4 from Higgsfield CDN
    - Stage upload to Shopify Files as VIDEO type
    - fileCreate + poll until fileStatus=READY
    - productCreateMedia(mediaContentType: VIDEO, originalSource: file URL)
    Video appears as a new item in the product's media gallery
    (alongside photos in the carousel).

  decision == "metafield":
    - Append entry to custom.videos JSON metafield
        { platform: "higgsfield-mp4", video_id: <hf job id>,
          url: <hf cdn url>, title: <preset>, thumbnail_url: <hf thumb> }
    - Theme already renders custom.videos in `wanelo-videos` snippet
      ("WATCH IN ACTION" block above the long-form description)

  decision == "skip":
    Nothing — video stays in Higgsfield archive only.

After all decisions applied for a product:
  - Tag flipped: videos-ready-for-review → videos-applied
  - Per-product log written to runs/video_feed/<pid>/applied.log
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime
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
FEED_DIR = REPO_ROOT / "pipeline" / "runs" / "video_feed"
API_VERSION = "2024-10"


# ── Shopify auth ────────────────────────────────────────────────────────────
def shopify_token() -> Tuple[str, str]:
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


# ── Carousel video upload (Shopify Files → product media) ──────────────────
def upload_video_to_shopify(store: str, token: str, mp4_url: str,
                            filename: str, alt: str) -> Optional[str]:
    """Download mp4 → stagedUploadsCreate(VIDEO) → POST → fileCreate(VIDEO) →
    poll until READY → return Shopify file URL for productCreateMedia.
    Returns None on failure."""
    print(f"      downloading {mp4_url[-50:]}...")
    r = requests.get(mp4_url, timeout=120, stream=True)
    r.raise_for_status()
    video_bytes = r.content
    print(f"      ↓ {len(video_bytes)/1024/1024:.1f} MB")

    # 1. stagedUploadsCreate
    q = """
    mutation($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets { url resourceUrl parameters { name value } }
        userErrors { field message }
      }
    }
    """
    stage = gql(store, token, q, {"input": [{
        "filename": filename, "mimeType": "video/mp4",
        "httpMethod": "POST", "resource": "VIDEO",
        "fileSize": str(len(video_bytes)),
    }]})
    targets = (stage.get("data") or {}).get("stagedUploadsCreate", {}).get("stagedTargets") or []
    if not targets:
        errs = (stage.get("data") or {}).get("stagedUploadsCreate", {}).get("userErrors")
        print(f"      stagedUploadsCreate failed: {errs}")
        return None
    t = targets[0]
    form = {p["name"]: p["value"] for p in t["parameters"]}

    # 2. POST to staged URL
    print(f"      uploading to Shopify staged URL...")
    up = requests.post(t["url"], data=form,
                       files={"file": (filename, video_bytes, "video/mp4")}, timeout=300)
    if up.status_code >= 400:
        print(f"      staged POST failed: {up.status_code} {up.text[:200]}")
        return None

    # 3. fileCreate
    q2 = """
    mutation($f: [FileCreateInput!]!) {
      fileCreate(files: $f) {
        files { id ... on Video { id fileStatus originalSource { url } } }
        userErrors { field message code }
      }
    }
    """
    fc = gql(store, token, q2, {"f": [{
        "originalSource": t["resourceUrl"], "contentType": "VIDEO", "alt": alt,
    }]})
    files = (fc.get("data") or {}).get("fileCreate", {}).get("files") or []
    if not files or not files[0].get("id"):
        errs = (fc.get("data") or {}).get("fileCreate", {}).get("userErrors")
        print(f"      fileCreate failed: {errs}")
        return None
    file_id = files[0]["id"]

    # 4. Poll until READY (Shopify transcode video — can take 1-2 min)
    print(f"      polling Shopify video transcode (max 3 min)...")
    q3 = """query($id: ID!) {
      node(id: $id) { ... on Video {
        id fileStatus sources { url mimeType } originalSource { url }
      } }
    }"""
    for _ in range(45):  # ~3 min @ 4s
        time.sleep(4)
        r3 = gql(store, token, q3, {"id": file_id})
        n = (r3.get("data") or {}).get("node") or {}
        st = n.get("fileStatus")
        if st == "READY":
            src = (n.get("originalSource") or {}).get("url") or \
                  ((n.get("sources") or [{}])[0].get("url") if n.get("sources") else None)
            print(f"      ✓ READY: {src[-60:] if src else '(no url)'}")
            return file_id  # return Shopify file ID for productCreateMedia originalSource
        if st == "FAILED":
            print(f"      FAILED")
            return None
    print(f"      timed out after 3 min")
    return None


def attach_video_to_product(store: str, token: str, product_id: str,
                            video_file_id: str, alt: str) -> bool:
    """Attach a Shopify-hosted video file to a product as media.
    Uses productCreateMedia with VIDEO contentType."""
    # For productCreateMedia, originalSource must be Shopify file URL,
    # not file_id directly. We fetch the URL from the file_id first.
    q_get = "query($id: ID!) { node(id: $id) { ... on Video { originalSource { url } } } }"
    rg = gql(store, token, q_get, {"id": video_file_id})
    src_url = (((rg.get("data") or {}).get("node") or {})
               .get("originalSource") or {}).get("url")
    if not src_url:
        print(f"      cannot resolve video URL for file_id {video_file_id}")
        return False
    q = """
    mutation($pid: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $pid, media: $media) {
        media { ... on Video { id status } }
        mediaUserErrors { code field message }
      }
    }
    """
    r = gql(store, token, q, {"pid": product_id, "media": [{
        "originalSource": src_url,
        "alt": alt,
        "mediaContentType": "VIDEO",
    }]})
    errs = ((r.get("data") or {}).get("productCreateMedia") or {}).get("mediaUserErrors") or []
    if errs:
        print(f"      productCreateMedia errors: {errs}")
        return False
    return True


# ── Metafield video append ──────────────────────────────────────────────────
def append_to_videos_metafield(store: str, token: str, product_id: str,
                               new_items: List[dict]) -> bool:
    """Append to product.metafields.custom.videos JSON. Read existing →
    extend items → metafieldsSet back."""
    if not new_items:
        return True
    q_get = """
    query($id: ID!) {
      product(id: $id) {
        metafield(namespace: "custom", key: "videos") { value }
      }
    }
    """
    r = gql(store, token, q_get, {"id": product_id})
    raw = (((r.get("data") or {}).get("product") or {}).get("metafield") or {}).get("value")
    try:
        current = json.loads(raw) if raw else {}
    except Exception:
        current = {}
    if not isinstance(current, dict):
        current = {}
    current.setdefault("head", {
        "kicker": "WATCH IN ACTION",
        "h2": "See it work in 30 seconds",
    })
    current.setdefault("items", [])
    # de-dupe by video_id
    have_ids = {it.get("video_id") for it in current["items"] if isinstance(it, dict)}
    for it in new_items:
        if it.get("video_id") not in have_ids:
            current["items"].append(it)

    q_set = """
    mutation($input: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $input) {
        metafields { id key }
        userErrors { field message code }
      }
    }
    """
    s = gql(store, token, q_set, {"input": [{
        "ownerId": product_id, "namespace": "custom", "key": "videos",
        "type": "json", "value": json.dumps(current, ensure_ascii=False),
    }]})
    errs = ((s.get("data") or {}).get("metafieldsSet") or {}).get("userErrors") or []
    if errs:
        print(f"      metafieldsSet errors: {errs}")
        return False
    return True


def update_product_tags(store: str, token: str, product_id: str,
                        remove: List[str], add: List[str]) -> None:
    cur = gql(store, token, "query($id: ID!) { product(id: $id) { tags } }",
              {"id": product_id})
    current = set((cur.get("data") or {}).get("product", {}).get("tags") or [])
    new = (current - set(remove)) | set(add)
    gql(store, token,
        "mutation($input: ProductInput!) { productUpdate(input: $input) "
        "{ userErrors { field message } } }",
        {"input": {"id": product_id, "tags": sorted(new)}})


# ── Per-product apply ──────────────────────────────────────────────────────
def apply_for_product(store: str, token: str, product_dir: Path, dry_run: bool) -> dict:
    mf_path = product_dir / "manifest.json"
    dc_path = product_dir / "decisions.json"
    if not mf_path.exists():
        return {"product_dir": str(product_dir), "skipped": "no manifest"}
    if not dc_path.exists():
        return {"product_dir": str(product_dir), "skipped": "no decisions.json"}

    manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    decisions = json.loads(dc_path.read_text(encoding="utf-8"))
    product_id = manifest.get("product_id")
    title = manifest.get("title", "")
    pid_short = manifest.get("product_id_short", "")
    videos = manifest.get("videos", [])
    print(f"\n→ {pid_short} | {title[:60]}")

    carousel_attached = 0
    metafield_appended = 0
    decision_map = decisions.get("decisions", {})

    metafield_payload: List[dict] = []

    for idx, vid in enumerate(videos):
        if not vid.get("raw_url"):
            continue
        decision = (decision_map.get(str(idx)) or {}).get("decision", "skip")
        preset = vid.get("preset", "")
        if decision == "skip":
            continue
        print(f"  video #{idx} [{preset}] → {decision}")
        if dry_run:
            print(f"    [dry-run] would apply")
            continue

        if decision == "carousel":
            file_id = upload_video_to_shopify(
                store, token, vid["raw_url"],
                filename=f"{pid_short}_{preset.lower().replace(' ', '_')}.mp4",
                alt=f"{title} — {preset}",
            )
            if file_id:
                if attach_video_to_product(store, token, product_id, file_id,
                                           alt=f"{title} — {preset}"):
                    carousel_attached += 1
                    print(f"    ✓ attached to product carousel")
        elif decision == "metafield":
            metafield_payload.append({
                "platform": "higgsfield-mp4",
                "video_id": vid.get("job_id", ""),
                "url": vid["raw_url"],
                "thumbnail_url": vid.get("thumbnail_url", ""),
                "title": f"{preset} preview",
                "preset": preset,
            })

    if metafield_payload and not dry_run:
        if append_to_videos_metafield(store, token, product_id, metafield_payload):
            metafield_appended = len(metafield_payload)
            print(f"  ✓ appended {metafield_appended} items to custom.videos metafield")

    if not dry_run and (carousel_attached or metafield_appended):
        update_product_tags(store, token, product_id,
                            remove=["videos-ready-for-review"],
                            add=["videos-applied"])
        print(f"  tag flipped: videos-ready-for-review → videos-applied")
        log_line = (f"{datetime.utcnow().isoformat()} | carousel={carousel_attached} "
                    f"| metafield={metafield_appended}\n")
        with (product_dir / "applied.log").open("a", encoding="utf-8") as f:
            f.write(log_line)

    return {"product_id": product_id, "title": title,
            "carousel_attached": carousel_attached,
            "metafield_appended": metafield_appended}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--product-id", default=None,
                        help="apply decisions for this product folder only (numeric ID)")
    parser.add_argument("--feed-dir", type=Path, default=FEED_DIR,
                        help=f"video feed dir (default: {FEED_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen without touching Shopify")
    parser.add_argument("--decisions-json", default=None,
                        help="inline decisions JSON string OR path to a .json file. "
                             "Lets Claude apply chat-driven decisions without the "
                             "operator dropping decisions.json on disk manually. "
                             "Must include product_id_short. Will be written into "
                             "<feed_dir>/<product_id_short>/decisions.json then applied.")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)
    store, token = shopify_token()
    print(f"Shopify: {store}{' [DRY-RUN]' if args.dry_run else ''}")

    if not args.feed_dir.exists():
        sys.exit(f"feed dir not found: {args.feed_dir}")

    # If --decisions-json provided, persist it as <feed_dir>/<pid_short>/decisions.json
    # so the regular per-folder flow picks it up. Accepts inline JSON string OR file path.
    if args.decisions_json:
        raw = args.decisions_json
        if Path(raw).exists():
            raw = Path(raw).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"--decisions-json: invalid JSON: {e}")
        pid_short = payload.get("product_id_short")
        if not pid_short:
            sys.exit("--decisions-json: payload missing 'product_id_short'")
        target_dir = args.feed_dir / pid_short
        if not target_dir.exists():
            sys.exit(f"product folder not found for pid={pid_short}: {target_dir}")
        decisions_path = target_dir / "decisions.json"
        decisions_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote decisions to: {decisions_path}")
        args.product_id = pid_short  # focus the apply on this one

    if args.product_id:
        dirs = [args.feed_dir / args.product_id]
    else:
        dirs = [d for d in args.feed_dir.iterdir() if d.is_dir()]
    if not dirs:
        print("No per-product folders found.")
        return 0

    print(f"\nProcessing {len(dirs)} product folder(s)...")
    results = []
    for d in dirs:
        try:
            r = apply_for_product(store, token, d, args.dry_run)
            results.append(r)
        except Exception as e:
            print(f"  EXCEPTION on {d.name}: {str(e)[:200]}")
            results.append({"product_dir": str(d), "error": str(e)[:300]})

    ok = sum(1 for r in results if not r.get("error") and not r.get("skipped"))
    print(f"\nDone: {ok}/{len(dirs)} products processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
