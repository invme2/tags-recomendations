"""marketing_studio_batch.py — Shopify-side helper for the chat-driven
Marketing Studio video pipeline.

ARCHITECTURE — TWO MODES
========================
This tool supports two workflows depending on Higgsfield access:

* MCP-driven (default, no API key needed):
  Claude (in chat) is the worker. Roman tags products in Admin → this
  script LISTS them → Claude generates videos via MCP → this script
  TAKES the results and writes manifest+HTML feed.

* CLI direct (requires HIGGSFIELD_API_KEY in .env):
  Fully autonomous — script generates videos itself. Use when you have
  an API key and want hands-off operation.

WORKFLOW (MCP-driven, primary)
==============================
1. Operator: tag products in Shopify Admin with `videos-needed`.
2. Operator: chat with Claude → "запускай видео для тегированных".
3. Claude:
     a) `python marketing_studio_batch.py --list` — read tagged products
     b) For each product: generate 6 Marketing Studio videos via MCP
     c) Save MCP results to JSON file (see schema below)
     d) `python marketing_studio_batch.py --from-mcp-results <json>` —
        writes per-product manifest + HTML feed + flips Shopify tag
4. Claude tells operator: "Open file:///.../video_feed/index.html"
5. Operator reviews videos, marks Carousel/Metafield/Skip per video,
   downloads decisions.json into each product folder.
6. `python apply_video_decisions.py` — pushes approved videos to Shopify.

MCP-RESULTS JSON SCHEMA
=======================
    {
      "products": [
        {
          "product_id": "gid://shopify/Product/8889680691378",
          "product_id_short": "8889680691378",
          "title": "...",
          "handle": "...",
          "primary_image_url": "https://...",
          "videos": [
            {
              "preset": "UGC",
              "job_id": "<higgsfield-uuid>",
              "raw_url": "https://...mp4",
              "thumbnail_url": "https://...",
              "prompt": "<enhanced prompt from MCP>"
            },
            ...
          ]
        },
        ...
      ]
    }

USAGE
=====
    # 1. LIST — print all products tagged 'videos-needed' with metadata.
    #    Claude reads this to know what to generate via MCP.
    python pipeline/tools/marketing_studio_batch.py --list

    # 1b. List as JSON for programmatic consumption
    python pipeline/tools/marketing_studio_batch.py --list --json

    # 2. FROM-MCP-RESULTS — write feed from JSON of MCP-generated videos.
    #    Run this AFTER Claude has generated videos via chat.
    python pipeline/tools/marketing_studio_batch.py --from-mcp-results results.json

    # 3. CLI-DIRECT — generate via Higgsfield API directly (needs HIGGSFIELD_API_KEY)
    python pipeline/tools/marketing_studio_batch.py --direct

    # Other flags
    python pipeline/tools/marketing_studio_batch.py --tag videos-needed
    python pipeline/tools/marketing_studio_batch.py --product-id 8889680691378
    python pipeline/tools/marketing_studio_batch.py --max-products 3

COST (Marketing Studio)
=======================
6 presets × 75 credits each = 450 credits per product.
Roman's typical balance: ~5000 credits = ~11 products per topup.
"""
from __future__ import annotations

import argparse
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

# Default 6-preset batch (per operator preference, balances variety vs credit cost)
# NB: "Unboxing" intentionally EXCLUDED — the model invents fictional box
# contents (operator rule 2026-05-29). Standard composition per product:
# 2x Hyper Motion (1 pinned top), 3x UGC, 1x Product Review, 1x TV Spot,
# 1x Wild Card = 8 videos. Hyper Motion (product_showcase) always index 0.
DEFAULT_PRESETS = [
    "Hyper Motion",
    "UGC",
    "Product Review",
    "Hyper Motion",
    "UGC",
    "TV Spot",
    "UGC",
    "Wild Card",
]
CREDITS_PER_VIDEO = 75  # Marketing Studio video pricing
HIGGSFIELD_API_BASE = "https://api.higgsfield.ai"


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


# ── Higgsfield API (direct REST) ────────────────────────────────────────────
def hf_headers() -> dict:
    key = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    if not key:
        sys.exit(
            "HIGGSFIELD_API_KEY missing in .env. Either:\n"
            "  1. Add it (get from https://higgsfield.ai/settings/api)\n"
            "  2. OR use the chat-driven flow via MCP — see docstring."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def hf_balance() -> int:
    r = requests.get(f"{HIGGSFIELD_API_BASE}/v1/balance", headers=hf_headers(), timeout=15)
    r.raise_for_status()
    return r.json().get("credits", 0)


def hf_upload_image(file_url: str, filename: str) -> str:
    """Upload an image to Higgsfield by URL → returns media_id.
    Higgsfield supports passing an https URL directly as media value, so we
    don't strictly need to upload — but having a stable media_id is cleaner
    and lets us reuse the source across N generations without re-fetching."""
    r = requests.post(
        f"{HIGGSFIELD_API_BASE}/v1/media/upload",
        headers=hf_headers(),
        json={"filename": filename, "content_type": "image/jpeg",
              "source_url": file_url},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("media_id") or r.json().get("id")


def hf_generate_video(media_id: str, mode: str, aspect_ratio: str = "9:16",
                      duration: int = 8) -> str:
    """Submit a Marketing Studio video generation job.
    Returns job_id. Poll separately for status/results."""
    r = requests.post(
        f"{HIGGSFIELD_API_BASE}/v1/video/generate",
        headers=hf_headers(),
        json={
            "model": "marketing_studio_video",
            "params": {
                "medias": [{"value": media_id, "role": "image"}],
                "mode": mode,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
                "resolution": "720p",
                "generate_audio": True,
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["results"][0]["id"]


def hf_poll_job(job_id: str) -> dict:
    """Returns {status, raw_url?, thumbnail_url?, error?, prompt?, mode?}."""
    r = requests.get(f"{HIGGSFIELD_API_BASE}/v1/jobs/{job_id}",
                     headers=hf_headers(), timeout=15)
    r.raise_for_status()
    j = r.json().get("results", [{}])[0]
    return {
        "status": j.get("status"),
        "raw_url": (j.get("results") or {}).get("rawUrl"),
        "thumbnail_url": (j.get("results") or {}).get("thumbnailUrl"),
        "prompt": (j.get("params") or {}).get("enhanced_prompt") or
                  (j.get("params") or {}).get("user_prompt") or "",
        "mode": (j.get("params") or {}).get("mode") or "",
    }


# ── Shopify product discovery ───────────────────────────────────────────────
def list_tagged_products(store: str, token: str, tag: str) -> List[dict]:
    """Returns list of {id, title, handle, primary_image_url, tags}."""
    products: List[dict] = []
    cursor = None
    while True:
        q = """
        query($cursor: String, $q: String!) {
          products(first: 50, after: $cursor, query: $q) {
            edges {
              cursor
              node {
                id
                title
                handle
                tags
                featuredImage { url }
                media(first: 1) { edges { node { ... on MediaImage { image { url } } } } }
              }
            }
            pageInfo { hasNextPage }
          }
        }
        """
        r = gql(store, token, q, {"cursor": cursor, "q": f"tag:{tag}"})
        edges = (r.get("data") or {}).get("products", {}).get("edges", [])
        for e in edges:
            n = e["node"]
            img_url = ((n.get("featuredImage") or {}).get("url")
                       or ((n.get("media", {}).get("edges") or [{}])[0]
                           .get("node", {}).get("image") or {}).get("url"))
            products.append({
                "id": n["id"],
                "id_short": n["id"].rsplit("/", 1)[-1],
                "title": n["title"],
                "handle": n["handle"],
                "tags": n["tags"],
                "primary_image_url": img_url,
            })
        if not edges or not r.get("data", {}).get("products", {}).get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = edges[-1]["cursor"]
    return products


def get_product_by_id(store: str, token: str, pid: str) -> Optional[dict]:
    gid = f"gid://shopify/Product/{pid}" if pid.isdigit() else pid
    q = """
    query($id: ID!) {
      product(id: $id) {
        id title handle tags
        featuredImage { url }
        media(first: 1) { edges { node { ... on MediaImage { image { url } } } } }
      }
    }
    """
    r = gql(store, token, q, {"id": gid})
    n = (r.get("data") or {}).get("product")
    if not n:
        return None
    img_url = ((n.get("featuredImage") or {}).get("url")
               or ((n.get("media", {}).get("edges") or [{}])[0]
                   .get("node", {}).get("image") or {}).get("url"))
    return {
        "id": n["id"], "id_short": n["id"].rsplit("/", 1)[-1],
        "title": n["title"], "handle": n["handle"], "tags": n["tags"],
        "primary_image_url": img_url,
    }


def update_product_tags(store: str, token: str, product_id: str,
                        remove: List[str], add: List[str]) -> None:
    q_get = "query($id: ID!) { product(id: $id) { tags } }"
    cur = gql(store, token, q_get, {"id": product_id})
    current = set((cur.get("data") or {}).get("product", {}).get("tags") or [])
    new = (current - set(remove)) | set(add)
    q_set = """
    mutation($input: ProductInput!) {
      productUpdate(input: $input) { product { id tags } userErrors { field message } }
    }
    """
    r = gql(store, token, q_set,
            {"input": {"id": product_id, "tags": sorted(new)}})
    errs = (r.get("data") or {}).get("productUpdate", {}).get("userErrors", [])
    if errs:
        print(f"  tag update errors: {errs}")


# ── Per-product generation pipeline ─────────────────────────────────────────
def process_product(store: str, token: str, product: dict, presets: List[str],
                    dry_run: bool) -> dict:
    """Returns {product_id, status, videos: [{preset, job_id, url?, ...}]}."""
    pid = product["id"]
    pid_short = product["id_short"]
    title = product["title"]

    if not product.get("primary_image_url"):
        print(f"  SKIP {pid_short} ({title[:50]}): no primary image")
        return {"product_id": pid, "status": "no_image", "videos": []}

    print(f"\n→ {pid_short} | {title[:60]}")
    print(f"  primary image: {product['primary_image_url'][:80]}...")
    print(f"  generating {len(presets)} Marketing Studio videos "
          f"({len(presets) * CREDITS_PER_VIDEO} credits)")

    if dry_run:
        print(f"  [dry-run] would generate {len(presets)} videos: {presets}")
        return {"product_id": pid, "status": "dry_run", "videos": [
            {"preset": p, "job_id": None} for p in presets
        ]}

    # 1. Upload product image to Higgsfield
    print(f"  uploading product image to Higgsfield...")
    media_id = hf_upload_image(product["primary_image_url"],
                               f"{pid_short}_primary.jpg")
    print(f"  media_id: {media_id}")

    # 2. Submit one job per preset
    jobs = []
    for preset in presets:
        try:
            job_id = hf_generate_video(media_id, mode=preset)
            jobs.append({"preset": preset, "job_id": job_id, "status": "pending"})
            print(f"    submitted [{preset}] → {job_id}")
        except Exception as e:
            print(f"    FAIL submit [{preset}]: {str(e)[:150]}")
            jobs.append({"preset": preset, "job_id": None,
                         "status": "submit_failed", "error": str(e)[:300]})

    # 3. Poll until all complete (or timeout)
    print(f"  polling {len([j for j in jobs if j['job_id']])} jobs (max 10 min)...")
    deadline = time.time() + 600
    while time.time() < deadline:
        pending = [j for j in jobs if j.get("job_id") and
                   j["status"] not in ("completed", "nsfw", "failed", "submit_failed")]
        if not pending:
            break
        for j in pending:
            try:
                info = hf_poll_job(j["job_id"])
                j["status"] = info["status"] or j["status"]
                if info.get("raw_url"):
                    j["raw_url"] = info["raw_url"]
                    j["thumbnail_url"] = info.get("thumbnail_url") or ""
                    j["prompt"] = info.get("prompt", "")
                    j["mode_actual"] = info.get("mode", "")
            except Exception as e:
                print(f"    poll [{j['preset']}] error: {str(e)[:100]}")
        time.sleep(20)

    ok = sum(1 for j in jobs if j.get("raw_url"))
    print(f"  {ok}/{len(presets)} videos completed")
    return {"product_id": pid, "product_id_short": pid_short, "status": "complete",
            "videos": jobs, "title": title, "handle": product["handle"],
            "primary_image_url": product["primary_image_url"]}


# ── Write per-product manifest + HTML preview ───────────────────────────────
def write_product_feed(out_dir: Path, product_result: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **product_result,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    html = render_product_html(product_result)
    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def render_product_html(p: dict) -> str:
    """Per-product review page with embedded video players + Carousel/
    Metafield/Skip radio per video + Save button (downloads decisions.json)."""
    video_cards = []
    for i, v in enumerate(p.get("videos", [])):
        if not v.get("raw_url"):
            continue
        vid_idx = i
        preset = v["preset"]
        url = v["raw_url"]
        prompt_excerpt = (v.get("prompt") or "")[:300].replace("<", "&lt;").replace(">", "&gt;")
        card = f"""
<div class="video-card" data-idx="{vid_idx}" data-preset="{preset}">
  <div class="preset-label">{preset}</div>
  <video controls preload="metadata" playsinline>
    <source src="{url}" type="video/mp4">
  </video>
  <div class="prompt-excerpt">{prompt_excerpt}...</div>
  <div class="decision-row">
    <label><input type="radio" name="d{vid_idx}" value="carousel"> 🎬 Carousel</label>
    <label><input type="radio" name="d{vid_idx}" value="metafield"> 📝 Metafield</label>
    <label><input type="radio" name="d{vid_idx}" value="skip" checked> ❌ Skip</label>
  </div>
</div>
"""
        video_cards.append(card)

    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review: """ + p["title"] + """</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, Inter, Helvetica, sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f7fa; color: #001a34; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  .product-image { max-width: 200px; border-radius: 8px; margin-bottom: 16px; }
  .video-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 16px; }
  .video-card { background: white; border-radius: 12px; padding: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .preset-label { font-weight: 700; font-size: 14px; color: rgb(0,91,255);
                  margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.06em; }
  video { width: 100%; border-radius: 8px; background: #000; aspect-ratio: 9/16; object-fit: cover; }
  .prompt-excerpt { font-size: 11px; color: #888; margin-top: 8px; line-height: 1.4;
                    max-height: 60px; overflow: hidden; }
  .decision-row { display: flex; flex-direction: column; gap: 6px; margin-top: 10px;
                  padding-top: 10px; border-top: 1px solid #eee; }
  .decision-row label { font-size: 13px; cursor: pointer; padding: 6px 8px;
                        border-radius: 6px; }
  .decision-row label:hover { background: #f5f7fa; }
  .actions { position: sticky; bottom: 16px; background: white; padding: 16px;
             border-radius: 12px; box-shadow: 0 -4px 12px rgba(0,0,0,0.08);
             display: flex; gap: 12px; align-items: center; margin-top: 24px; }
  .btn { padding: 10px 20px; border: 0; border-radius: 8px; font-size: 14px;
         font-weight: 600; cursor: pointer; }
  .btn-primary { background: rgb(0,91,255); color: white; }
  .btn-secondary { background: #eef1f5; color: #001a34; }
  pre#json-preview { background: #1e1e2e; color: #cdd6f4; padding: 12px;
                     border-radius: 8px; font-size: 11px; overflow-x: auto;
                     max-height: 200px; margin-top: 12px; display: none; }
</style></head><body>

<h1>""" + p["title"] + """</h1>
<div class="subtitle">Product ID: """ + p.get("product_id_short", "") + """ &middot;
  """ + str(sum(1 for v in p.get("videos", []) if v.get("raw_url"))) + """ videos ready for review</div>
<img class="product-image" src=\"""" + (p.get("primary_image_url") or "") + """\" alt="product">

<div class="video-grid">
""" + "\n".join(video_cards) + """
</div>

<div class="actions">
  <button class="btn btn-primary" onclick="saveDecisions()">💾 Save decisions</button>
  <button class="btn btn-secondary" onclick="copyJson()">📋 Copy JSON to clipboard</button>
  <button class="btn btn-secondary" onclick="document.getElementById('json-preview').style.display='block'">👁 Show JSON</button>
</div>
<pre id="json-preview"></pre>

<script>
function collectDecisions() {
  const cards = document.querySelectorAll('.video-card');
  const decisions = {};
  cards.forEach(card => {
    const idx = card.dataset.idx;
    const preset = card.dataset.preset;
    const checked = card.querySelector('input[type=radio]:checked');
    decisions[idx] = { preset: preset, decision: checked ? checked.value : 'skip' };
  });
  return {
    product_id: """ + json.dumps(p.get("product_id", "")) + """,
    product_id_short: """ + json.dumps(p.get("product_id_short", "")) + """,
    decided_at: new Date().toISOString(),
    decisions: decisions
  };
}
function saveDecisions() {
  const blob = new Blob([JSON.stringify(collectDecisions(), null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'decisions.json';
  a.click();
  alert('Saved decisions.json — drop it into ' +
        'pipeline/runs/video_feed/""" + p.get("product_id_short", "") + """/ ' +
        'then run apply_video_decisions.py');
}
function copyJson() {
  const json = JSON.stringify(collectDecisions(), null, 2);
  navigator.clipboard.writeText(json).then(() => alert('Copied!'));
  document.getElementById('json-preview').textContent = json;
  document.getElementById('json-preview').style.display = 'block';
}
</script>
</body></html>"""


def regenerate_master_index(feed_dir: Path) -> Path:
    """List all per-product folders + link to each."""
    feed_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for pdir in sorted(feed_dir.iterdir()):
        if not pdir.is_dir():
            continue
        mf = pdir / "manifest.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_videos = sum(1 for v in data.get("videos", []) if v.get("raw_url"))
        has_decisions = (pdir / "decisions.json").exists()
        status = "✅ decisions saved" if has_decisions else "👁 ready for review"
        cards.append(f"""
<a class="row" href="{pdir.name}/index.html">
  <img src="{data.get('primary_image_url', '')}" alt="">
  <div class="meta">
    <div class="title">{data.get('title', '?')[:80]}</div>
    <div class="sub">PID {data.get('product_id_short', '?')} &middot; {n_videos} videos &middot; {status}</div>
  </div>
</a>""")

    html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video Feed — Wanelo</title><style>
body { font-family: -apple-system,Inter,Helvetica,sans-serif; max-width: 800px;
       margin: 0 auto; padding: 24px; background: #f5f7fa; color: #001a34; }
h1 { margin: 0 0 8px; }
.intro { color: #666; font-size: 14px; margin-bottom: 24px; }
.row { display: flex; align-items: center; gap: 16px; padding: 14px;
       background: white; border-radius: 12px; margin-bottom: 10px;
       text-decoration: none; color: inherit; box-shadow: 0 2px 6px rgba(0,0,0,0.05); }
.row:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.row img { width: 60px; height: 60px; border-radius: 8px; object-fit: cover; background: #eee; }
.title { font-weight: 600; font-size: 15px; }
.sub { color: #666; font-size: 13px; margin-top: 4px; }
.empty { color: #888; text-align: center; padding: 40px; font-style: italic; }
</style></head><body>
<h1>🎬 Video Review Feed</h1>
<div class="intro">Click a product to review its 6 Marketing Studio videos and
mark Carousel / Metafield / Skip per video.</div>
""" + ("\n".join(cards) if cards else
       '<div class="empty">No products with generated videos yet. Run marketing_studio_batch.py first.</div>') + """
</body></html>"""

    idx_path = feed_dir / "index.html"
    idx_path.write_text(html, encoding="utf-8")
    return idx_path


# ── Main ────────────────────────────────────────────────────────────────────
def cmd_list(store: str, token: str, args) -> int:
    """List tagged products → print info Claude needs for MCP generation."""
    if args.product_id:
        p = get_product_by_id(store, token, args.product_id)
        products = [p] if p else []
    else:
        products = list_tagged_products(store, token, args.tag)
    products = products[: args.max_products]

    if args.json:
        # JSON output for programmatic consumption (Claude reads + iterates)
        print(json.dumps({"products": products}, indent=2, ensure_ascii=False))
        return 0

    # Human-readable
    print(f"\n{len(products)} product(s) tagged '{args.tag}':\n")
    if not products:
        print("  (none)")
        return 0
    for p in products:
        print(f"  • {p['id_short']} | {p['title'][:60]}")
        print(f"      handle: {p['handle']}")
        print(f"      image:  {p.get('primary_image_url', '(no image)')[:80]}")
        print(f"      tags:   {p['tags']}")
        print()
    cost = len(products) * len(DEFAULT_PRESETS) * CREDITS_PER_VIDEO
    print(f"Generating 6 MS videos each = {cost} Higgsfield credits total")
    return 0


def cmd_from_mcp_results(store: str, token: str, args) -> int:
    """Take MCP-generated results JSON → write per-product feed + flip tags."""
    results_path = Path(args.from_mcp_results)
    if not results_path.exists():
        sys.exit(f"results file not found: {results_path}")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    products = data.get("products") or []
    if not products:
        sys.exit("results JSON has no 'products' key or empty list")

    args.feed_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing feed for {len(products)} product(s)...")

    for p in products:
        pid = p.get("product_id")
        pid_short = p.get("product_id_short")
        if not pid or not pid_short:
            print(f"  SKIP — missing product_id / product_id_short: {p.get('title', '?')[:50]}")
            continue
        # Normalize result shape — same as process_product output
        result = {
            "product_id": pid,
            "product_id_short": pid_short,
            "title": p.get("title", ""),
            "handle": p.get("handle", ""),
            "primary_image_url": p.get("primary_image_url", ""),
            "status": "complete",
            "videos": p.get("videos", []),
        }
        out_dir = args.feed_dir / pid_short
        html_path = write_product_feed(out_dir, result)
        ok = sum(1 for v in result["videos"] if v.get("raw_url"))
        print(f"  ✓ {pid_short} — {ok}/{len(result['videos'])} videos → {html_path}")

        # Flip tag: videos-needed → videos-ready-for-review
        if not args.skip_tag_update:
            try:
                update_product_tags(store, token, pid,
                                    remove=[args.tag], add=["videos-ready-for-review"])
                print(f"      tag: {args.tag} → videos-ready-for-review")
            except Exception as e:
                print(f"      tag update failed: {str(e)[:120]}")

    idx = regenerate_master_index(args.feed_dir)
    print(f"\nMaster feed: file:///{idx.as_posix()}")
    print("Next: open in browser → mark Carousel/Metafield/Skip → save decisions.json")
    print("Then: python pipeline/tools/apply_video_decisions.py")
    return 0


def cmd_direct(store: str, token: str, args) -> int:
    """Direct Higgsfield API mode (needs HIGGSFIELD_API_KEY)."""
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    print(f"Presets: {presets} ({len(presets)} × {CREDITS_PER_VIDEO} = "
          f"{len(presets) * CREDITS_PER_VIDEO} credits per product)")

    if args.product_id:
        p = get_product_by_id(store, token, args.product_id)
        products = [p] if p else []
    else:
        products = list_tagged_products(store, token, args.tag)
    if not products:
        print(f"\nNo products found (tag={args.tag}).")
        return 0
    products = products[: args.max_products]
    total = len(products) * len(presets) * CREDITS_PER_VIDEO
    print(f"\nFound {len(products)} product(s). Estimated: {total} credits")

    if not args.dry_run:
        try:
            balance = hf_balance()
            print(f"Higgsfield balance: {balance} credits")
            if balance < total:
                sys.exit(f"Balance too low ({balance} < {total}).")
        except Exception as e:
            print(f"  balance check failed: {str(e)[:80]}")

    args.feed_dir.mkdir(parents=True, exist_ok=True)
    for p in products:
        try:
            result = process_product(store, token, p, presets, args.dry_run)
            if not args.dry_run and result["status"] == "complete":
                out_dir = args.feed_dir / result["product_id_short"]
                write_product_feed(out_dir, result)
                update_product_tags(store, token, result["product_id"],
                                    remove=[args.tag],
                                    add=["videos-ready-for-review"])
        except Exception as e:
            print(f"  EXCEPTION on {p.get('id_short', '?')}: {str(e)[:200]}")

    if not args.dry_run:
        idx = regenerate_master_index(args.feed_dir)
        print(f"\nMaster feed: file:///{idx.as_posix()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", default="videos-needed",
                        help="Shopify product tag (default: videos-needed)")
    parser.add_argument("--product-id", default=None,
                        help="Single product (numeric ID), skips tag query")
    parser.add_argument("--max-products", type=int, default=10,
                        help="Safety cap on products processed per run")
    parser.add_argument("--feed-dir", type=Path, default=FEED_DIR,
                        help=f"Output dir (default: {FEED_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preflight only — no API calls / writes")

    # Mode selectors (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true",
                      help="LIST tagged products (read-only) — for Claude/MCP")
    mode.add_argument("--from-mcp-results", default=None, metavar="JSON_PATH",
                      help="Write feed from Claude-generated MCP results JSON")
    mode.add_argument("--direct", action="store_true",
                      help="Generate videos via Higgsfield REST API directly "
                           "(requires HIGGSFIELD_API_KEY in .env)")

    # Direct-mode + from-mcp options
    parser.add_argument("--json", action="store_true",
                        help="With --list: emit JSON instead of human-readable")
    parser.add_argument("--presets", default=",".join(DEFAULT_PRESETS),
                        help=f"Marketing Studio modes (default: {DEFAULT_PRESETS})")
    parser.add_argument("--skip-tag-update", action="store_true",
                        help="With --from-mcp-results: don't flip Shopify tag")

    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)

    store, token = shopify_token()

    # Default mode = --list (safest, no side effects)
    if not (args.list or args.from_mcp_results or args.direct):
        args.list = True
        print(f"(no mode specified — defaulting to --list. Use --direct or "
              f"--from-mcp-results <json> for actions)\n")

    if args.list:
        return cmd_list(store, token, args)
    elif args.from_mcp_results:
        return cmd_from_mcp_results(store, token, args)
    elif args.direct:
        return cmd_direct(store, token, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
