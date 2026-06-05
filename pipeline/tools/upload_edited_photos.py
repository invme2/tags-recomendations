"""upload_edited_photos.py — push edited product photos back into Shopify.

TWO photo categories handled differently, based on `slot` in each product's
inner manifest.json (the per-product audit file that lives in every
bundle_photo_packs.py-produced folder):

  carousel-*  (carousel-hero / -lifestyle / -in-use / -detail / -scale)
    → REPLACE the product's media carousel
    → stagedUploadsCreate + productCreateMedia + productDeleteMedia(old)

  inline-*    (inline-story / -hero / -features / -brand-story / -lifestyle-gallery
               / -app-showcase / -room-placement / -timeline / ...)
    → UPLOAD to Shopify Files (no carousel attach) + swap URL in metafield JSONs
    → stagedUploadsCreate + fileCreate + poll until READY → get NEW CDN URL,
      then fetch all custom.* JSON metafields, str.replace(old_url → new_url),
      metafieldsSet to push patched JSON back

Photos with NO matching brief in the inner manifest default to carousel
(backward compat with old packs that don't have manifest.json).

INPUT layout (produced by bundle_photo_packs.py):

    <folder>/
    ├── manifest.json                       # ROOT: folder → shopify_product_id
    ├── 8889396__crest-3d-white-strips/
    │   ├── manifest.json                   # PER-PRODUCT: briefs[] with filename, slot, source_url
    │   ├── prompt.txt
    │   └── photos/
    │       ├── 01-carousel-hero.jpg
    │       ├── 02-carousel-lifestyle.jpg
    │       ├── 06-inline-story-1.jpg       ← slot 'inline-*' → swaps metafield URL
    │       └── ...
    └── 8889396265138__teeth-whitening-kit/
        └── ...

You can also point --folder at a ZIP file — it'll be extracted to temp,
processed, then cleaned up.

USAGE:
    # Default: full processing (carousel REPLACE + inline metafield swap)
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master

    # Carousel APPEND mode (keep old, add new at end). Inline still swaps.
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master --append

    # Dry-run: show what would happen without touching Shopify
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master --dry-run

    # Only carousel (skip inline metafield-URL swap)
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master --carousel-only

    # Only inline metafield URLs (skip carousel)
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master --inline-only

    # Limit to specific product folders
    python pipeline/tools/upload_edited_photos.py --folder ./edited_master \\
        --only 8889396__crest-3d-white-strips

SAFETY: old carousel media is deleted ONLY AFTER new media successfully
attaches (snapshot existing_before → upload → if any attached → delete old).
Metafield JSON is patched in-memory and only metafieldsSet if any URL
actually changed — no spurious writes.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
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
API_VERSION = "2024-10"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# ── Shopify auth (mirrors bundle_photo_packs.py) ────────────────────────────
def get_shopify_token() -> Tuple[str, str]:
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
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    body = {"query": query, "variables": variables or {}}
    for attempt in range(4):
        r = requests.post(url, headers=headers, json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify GQL failed: {r.status_code} {r.text[:200]}")


# ── Manifest + folder discovery ─────────────────────────────────────────────
def load_manifest(folder: Path) -> dict:
    """Find manifest.json next to the product folders. Raise if missing."""
    mf = folder / "manifest.json"
    if not mf.exists():
        raise FileNotFoundError(
            f"manifest.json not found at {mf}. The folder must come from "
            f"bundle_photo_packs.py (which writes a root manifest.json mapping "
            f"folder→shopify_product_id)."
        )
    return json.loads(mf.read_text(encoding="utf-8"))


def collect_photos(product_folder: Path) -> List[Path]:
    """Return all image files inside the product folder, sorted by filename.
    Photos may live directly in the folder OR under photos/ subdir OR under
    photos/carousel|inline subdirs (the simplified bucket layout)."""
    candidates: list[Path] = []
    photos_subdir = product_folder / "photos"
    if photos_subdir.is_dir():
        # Include carousel/ and inline/ buckets first (if present)
        for sub in ("carousel", "inline"):
            bucket = photos_subdir / sub
            if bucket.is_dir():
                candidates.extend(bucket.iterdir())
        # Then any files directly in photos/
        candidates.extend(photos_subdir.iterdir())
    candidates.extend(product_folder.iterdir())
    seen = set()
    result = []
    for p in candidates:
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.resolve() not in seen:
            seen.add(p.resolve())
            result.append(p)
    result.sort(key=lambda p: p.name)
    return result


def detect_bucket_layout(product_folder: Path) -> Optional[dict]:
    """If operator uses the simplified bucket layout (photos/carousel/ and/or
    photos/inline/), return a dict {scope: [Path, ...]} sorted by mtime.

    Returns None if no bucket subfolder found — caller falls back to flat
    auto-match by mtime across the whole photos/ directory.

    Bucket layout is operator-friendly because:
      - No need to rename ChatGPT output files
      - Slot is decided by which folder the file is in
      - Per-bucket position determines exact slot (matches manifest brief order)
    """
    photos_dir = product_folder / "photos"
    if not photos_dir.is_dir():
        return None
    buckets: dict[str, list[Path]] = {}
    for scope in ("carousel", "inline", "variants"):
        bdir = photos_dir / scope
        if not bdir.is_dir():
            continue
        files = [p for p in bdir.iterdir()
                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        if files:
            files.sort(key=lambda p: (p.stat().st_mtime, p.name))
            buckets[scope] = files
    return buckets or None


def remap_by_buckets(
    buckets: dict, inner_manifest: Dict[str, dict],
) -> Dict[str, dict]:
    """For each bucket (carousel/inline), order the manifest briefs of that
    scope, pair 1:1 with the user-provided files in mtime order, and re-key
    the manifest by actual filename.

    This means operator can drop any-name files into photos/carousel/ and
    photos/inline/, and the script figures out which brief each file fills.
    """
    if not inner_manifest:
        return inner_manifest

    # Group briefs by scope (carousel-* vs inline-*)
    def _scope_of(slot: str) -> str:
        if slot.startswith("inline-"):
            return "inline"
        return "carousel"

    def _brief_sort_key(fname: str) -> Tuple[int, str]:
        head = fname.split("-", 1)[0]
        try:
            return (int(head), fname)
        except ValueError:
            return (9999, fname)

    briefs_by_scope: dict[str, list[Tuple[str, dict]]] = {"carousel": [], "inline": []}
    for fname, brief in inner_manifest.items():
        scope = _scope_of(brief.get("slot", "") or "")
        briefs_by_scope[scope].append((fname, brief))
    for scope in briefs_by_scope:
        briefs_by_scope[scope].sort(key=lambda kv: _brief_sort_key(kv[0]))

    remapped: Dict[str, dict] = {}
    for scope, files in buckets.items():
        scope_briefs = briefs_by_scope.get(scope, [])
        if not scope_briefs:
            print(f"    [bucket: {scope}] {len(files)} files but manifest has 0 {scope}-* briefs — defaulting all to {scope}")
            for f in files:
                remapped[f.name] = {"slot": f"{scope}-extra", "filename": f.name}
            continue
        print(f"    [bucket: {scope}] {len(files)} files ↔ {len(scope_briefs)} briefs")
        for i, f in enumerate(files):
            if i < len(scope_briefs):
                orig_fname, brief = scope_briefs[i]
                slot = brief.get("slot", "?")
                print(f"      {i+1:2d}. {f.name:46.46s} → slot={slot}")
                remapped[f.name] = brief
            else:
                # More files than briefs — append as extras
                slot = f"{scope}-extra-{i - len(scope_briefs) + 1}"
                print(f"      {i+1:2d}. {f.name:46.46s} → slot={slot} (extra, will append)")
                remapped[f.name] = {"slot": slot, "filename": f.name}
    return remapped


def seo_filename(handle: str, slot: str, original_ext: str) -> str:
    """Generate SEO-friendly filename for Shopify upload:
       <handle>-<slot>.<ext> e.g. crest-3d-white-carousel-hero.png

    Keeps original extension. Used at staged_upload time so the file lands
    in Shopify Files with a search-engine-discoverable name."""
    safe_slot = slot.replace("_", "-")
    ext = original_ext.lower().lstrip(".") or "jpg"
    return f"{handle}-{safe_slot}.{ext}"


def load_inner_manifest(product_folder: Path) -> Dict[str, dict]:
    """Read <product_folder>/manifest.json and return {filename: brief_dict}.
    Each brief has slot, source_url, source_index, concept, etc.
    Returns {} if manifest missing or malformed (caller treats as all-carousel)."""
    mf = product_folder / "manifest.json"
    if not mf.exists():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"    warning: could not parse {mf}: {e}")
        return {}
    out = {}
    for b in data.get("briefs", []) or []:
        fname = b.get("filename") or ""
        if fname:
            out[fname] = b
    return out


def split_photos_by_slot(
    photos: List[Path], inner_manifest: Dict[str, dict],
) -> Tuple[List[Tuple[Path, dict]], List[Tuple[Path, dict]]]:
    """Split photos into (carousel_pairs, inline_pairs) — both keep brief info.
    A photo is INLINE iff its matching brief has slot starting with 'inline-'.
    Photos with no brief or with carousel-* slot go to carousel."""
    carousel: List[Tuple[Path, dict]] = []
    inline: List[Tuple[Path, dict]] = []
    for p in photos:
        brief = inner_manifest.get(p.name, {}) or {}
        slot = brief.get("slot", "") or ""
        if slot.startswith("inline-"):
            inline.append((p, brief))
        else:
            carousel.append((p, brief))
    return carousel, inline


def auto_match_by_position(
    photos: List[Path], inner_manifest: Dict[str, dict],
) -> Dict[str, dict]:
    """When ChatGPT-UI / Midjourney output edited photos with random names
    (operator can't bulk-rename), match by POSITION instead of filename.

    Strategy:
      1. Sort manifest briefs by their NN- prefix (canonical pipeline order).
      2. Sort actual photos by mtime ascending (ChatGPT saves in generation
         order; mtime preserves that). Fallback: alphabetical name sort.
      3. Pair 1:1: actual_photo[i] → brief[i]. Re-key the manifest by the
         ACTUAL filename so split_photos_by_slot can find the right slot.

    Falls back to original manifest unchanged when:
      - All actual filenames already exactly match manifest keys (no remap needed)
      - Manifest is empty (back-compat with old packs)

    Prints a mapping table so operator can sanity-check before pushing.
    """
    if not inner_manifest:
        return inner_manifest
    actual_names = {p.name for p in photos}
    manifest_names = set(inner_manifest.keys())
    # If all real photos already match manifest by name → no auto-match needed
    if actual_names and actual_names.issubset(manifest_names):
        return inner_manifest

    # Sort briefs by their NN- prefix (NN comes first in pipeline-generated names)
    def _brief_sort_key(fname: str) -> Tuple[int, str]:
        head = fname.split("-", 1)[0]
        try:
            return (int(head), fname)
        except ValueError:
            return (9999, fname)
    ordered_briefs = sorted(inner_manifest.items(), key=lambda kv: _brief_sort_key(kv[0]))

    # Sort actual photos by mtime ascending, fallback alphabetical on ties
    def _photo_sort_key(p: Path):
        try:
            return (p.stat().st_mtime, p.name)
        except OSError:
            return (0, p.name)
    ordered_photos = sorted(photos, key=_photo_sort_key)

    if not ordered_photos or not ordered_briefs:
        return inner_manifest

    # Print mapping table (operator can verify before push)
    print(f"    [auto-match by position] {len(ordered_photos)} photos ↔ {len(ordered_briefs)} briefs")
    remapped: Dict[str, dict] = {}
    pair_count = min(len(ordered_photos), len(ordered_briefs))
    for i in range(pair_count):
        actual = ordered_photos[i]
        orig_fname, brief = ordered_briefs[i]
        slot = brief.get("slot", "?")
        print(f"      {i+1:2d}. {actual.name:50.50s} → slot={slot}")
        # Re-key the brief by the actual filename so split_photos_by_slot
        # (which reads inner_manifest.get(p.name, {})) finds it.
        remapped[actual.name] = brief

    if len(ordered_photos) > len(ordered_briefs):
        extra = len(ordered_photos) - len(ordered_briefs)
        print(f"      WARN: {extra} extra photo(s) beyond manifest — default to carousel")
    elif len(ordered_briefs) > len(ordered_photos):
        miss = len(ordered_briefs) - len(ordered_photos)
        print(f"      INFO: {miss} brief(s) without a photo — operator skipped these slots")
    return remapped


# ── Shopify upload flow ─────────────────────────────────────────────────────
def staged_upload(store: str, token: str, file_path: Path,
                  upload_name: Optional[str] = None) -> Optional[str]:
    """Stage a file to Shopify Files. Returns resourceUrl for productCreateMedia.
    If upload_name is provided, the file is staged with that SEO-friendly name
    instead of the original local filename."""
    data = file_path.read_bytes()
    mime = mimetypes.guess_type(str(file_path))[0] or "image/jpeg"
    name_for_upload = upload_name or file_path.name
    q = """
    mutation($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters { name value }
        }
        userErrors { field message }
      }
    }
    """
    r = shopify_gql(store, token, q, {"input": [{
        "filename": name_for_upload,
        "mimeType": mime,
        "httpMethod": "POST",
        "resource": "IMAGE",
        "fileSize": str(len(data)),
    }]})
    targets = r.get("data", {}).get("stagedUploadsCreate", {}).get("stagedTargets", [])
    errs = r.get("data", {}).get("stagedUploadsCreate", {}).get("userErrors", [])
    if not targets or errs:
        print(f"    stagedUploadsCreate failed: {errs} / data={r.get('data')!r}")
        return None
    t = targets[0]
    # POST file to staged URL with all parameters as form fields.
    # Use SEO upload_name in the multipart filename too — Shopify Files panel
    # and CDN URL both keep this name.
    form = {p["name"]: p["value"] for p in t["parameters"]}
    files = {"file": (name_for_upload, data, mime)}
    up = requests.post(t["url"], data=form, files=files, timeout=120)
    if up.status_code >= 400:
        print(f"    staged POST failed: {up.status_code} {up.text[:200]}")
        return None
    return t["resourceUrl"]


def attach_media(store: str, token: str, product_id: str, resource_urls: List[str],
                 alts: Optional[List[str]] = None) -> List[str]:
    """productCreateMedia for each resourceUrl. Returns list of created media IDs."""
    if not resource_urls:
        return []
    alts = alts or [""] * len(resource_urls)
    q = """
    mutation($pid: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $pid, media: $media) {
        media { ... on MediaImage { id status } }
        mediaUserErrors { code field message }
      }
    }
    """
    media_inputs = [
        {"originalSource": url, "alt": alt or "", "mediaContentType": "IMAGE"}
        for url, alt in zip(resource_urls, alts)
    ]
    r = shopify_gql(store, token, q, {"pid": product_id, "media": media_inputs})
    data = r.get("data", {}).get("productCreateMedia", {})
    errs = data.get("mediaUserErrors", [])
    if errs:
        print(f"    productCreateMedia errors: {errs[:3]}")
    return [m["id"] for m in (data.get("media") or []) if m and m.get("id")]


def list_existing_media(store: str, token: str, product_id: str) -> List[str]:
    """Return list of MediaImage IDs currently attached to product."""
    q = """
    query($pid: ID!) {
      product(id: $pid) {
        media(first: 250) {
          edges { node { ... on MediaImage { id } } }
        }
      }
    }
    """
    r = shopify_gql(store, token, q, {"pid": product_id})
    edges = (r.get("data", {}).get("product") or {}).get("media", {}).get("edges", [])
    return [e["node"]["id"] for e in edges if e.get("node", {}).get("id")]


def get_variant_media_ids(store: str, token: str, product_id: str) -> set[str]:
    """Return set of media IDs that are assigned to a variant as its featured
    image. These must NOT be deleted during carousel REPLACE — they're the
    per-variant swatch photos that drive the image-switch-on-select feature."""
    q = """
    query($pid: ID!) {
      product(id: $pid) {
        variants(first: 100) {
          nodes { image { id } }
        }
      }
    }
    """
    r = shopify_gql(store, token, q, {"pid": product_id})
    nodes = (((r.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes", [])
    out = set()
    for n in nodes:
        img = n.get("image") or {}
        if img.get("id"):
            out.add(img["id"])
    return out


# ── Standalone Shopify Files upload (no product attach) ────────────────────
def upload_file_only(store: str, token: str, file_path: Path,
                     upload_name: Optional[str] = None) -> Optional[str]:
    """Upload an image to Shopify Files without attaching to a product.
    Returns the FINAL Shopify CDN URL (after Shopify processes the file).
    If upload_name is provided, that SEO-friendly name is used instead of
    the local file's name.

    Flow: stagedUploadsCreate → POST → fileCreate(IMAGE) → poll node fileStatus
    until READY → return image.url. Polls up to ~30s.
    """
    # Step 1+2: stage + POST (reuse same low-level path as staged_upload)
    resource_url = staged_upload(store, token, file_path, upload_name=upload_name)
    if not resource_url:
        return None
    alt_base = (upload_name or file_path.name).rsplit(".", 1)[0]

    # Step 3: fileCreate to materialise the staged upload as a Shopify File
    q = """
    mutation($f: [FileCreateInput!]!) {
      fileCreate(files: $f) {
        files { id ... on MediaImage { id fileStatus } }
        userErrors { field message code }
      }
    }
    """
    r = shopify_gql(store, token, q, {"f": [{
        "originalSource": resource_url,
        "contentType": "IMAGE",
        "alt": alt_base.replace("-", " "),
    }]})
    files = r.get("data", {}).get("fileCreate", {}).get("files") or []
    errs = r.get("data", {}).get("fileCreate", {}).get("userErrors") or []
    if errs:
        print(f"    fileCreate errors: {errs[:3]}")
    if not files or not files[0].get("id"):
        return None
    file_id = files[0]["id"]

    # Step 4: poll node(id) until fileStatus=READY → return image.url
    q_poll = """
    query($id: ID!) {
      node(id: $id) {
        ... on MediaImage { image { url } fileStatus }
      }
    }
    """
    for _ in range(15):  # ~30s max (15 * 2s)
        time.sleep(2)
        r2 = shopify_gql(store, token, q_poll, {"id": file_id})
        node = (r2.get("data") or {}).get("node") or {}
        st = node.get("fileStatus")
        if st == "READY":
            return (node.get("image") or {}).get("url")
        if st == "FAILED":
            print(f"    fileCreate FAILED status: {file_path.name}")
            return None
    print(f"    timeout waiting for fileStatus=READY: {file_path.name}")
    return None


# ── Slot → metafield JSON-path map (path-aware swap for inline photos) ─────
# Lets us target specific JSON paths even when multiple metafield image_url
# fields share the same source URL (Designer occasionally dedupes URLs across
# hero.image_url + story.chapters[0].image_url → a global str.replace would
# overwrite both, losing one of the edited photos).
SLOT_TARGETS: Dict[str, List[Tuple[str, str]]] = {
    # slot                → [(metafield_key, dotted_json_path)]
    'inline-hero':        [('hero',           'image_url')],
    'inline-story-1':     [('story',          'chapters[0].image_url')],
    'inline-story-2':     [('story',          'chapters[1].image_url')],
    'inline-story-3':     [('story',          'chapters[2].image_url')],
    'inline-features':    [('features',       'items[0].image_url')],
    'inline-cta':         [('cta',            'image_url')],
    'inline-brand-story': [('brand_story',    'founder_image_url')],
    'inline-video-demo':  [('video_demo',     'video.thumbnail_url')],
    'inline-app-showcase':[('app_showcase',   'screens[0].image_url')],
    'inline-room-placement': [('room_placement', 'scale_photos[0].image_url')],
    'inline-lifestyle-gallery': [('lifestyle_gallery', 'items[0].image_url')],
}

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _set_json_path(obj, path: str, value):
    """Set a nested value via a dotted-path with [N] index notation.
    Returns (success, old_value). E.g. path='chapters[0].image_url' → walks
    obj.chapters[0]['image_url'] = value."""
    tokens = []
    for m in _PATH_TOKEN_RE.finditer(path):
        if m.group(1) is not None:
            tokens.append(("key", m.group(1)))
        else:
            tokens.append(("idx", int(m.group(2))))
    cur = obj
    for i, (kind, t) in enumerate(tokens):
        is_last = (i == len(tokens) - 1)
        try:
            if kind == "key":
                if is_last:
                    old = cur.get(t)
                    cur[t] = value
                    return True, old
                cur = cur[t]
            else:
                if is_last:
                    old = cur[t] if t < len(cur) else None
                    if t >= len(cur):
                        return False, None
                    cur[t] = value
                    return True, old
                cur = cur[t]
        except (KeyError, IndexError, TypeError, AttributeError):
            return False, None
    return False, None


def swap_inline_targeted(store: str, token: str, product_id: str,
                         inline_targets: List[Tuple[str, str, str]],
                         dry_run: bool = False) -> int:
    """Path-aware swap. inline_targets = [(metafield_key, json_path, new_url)].
    Groups by metafield_key, applies all path-set ops to one fetched value,
    pushes back via metafieldsSet (one mutation per metafield_key).
    Returns count of metafields patched.
    """
    if not inline_targets:
        return 0
    # Group by metafield_key
    by_key: Dict[str, List[Tuple[str, str]]] = {}
    for mf_key, json_path, new_url in inline_targets:
        by_key.setdefault(mf_key, []).append((json_path, new_url))

    mfs = fetch_json_metafields(store, token, product_id)
    patched_inputs = []
    n_patched = 0
    for mf_key, ops in by_key.items():
        raw = mfs.get(mf_key)
        if not raw:
            print(f"      custom.{mf_key}: NOT SET — cannot path-swap (skipping {len(ops)} ops)")
            continue
        try:
            data = json.loads(raw)
        except Exception as e:
            print(f"      custom.{mf_key}: JSON parse failed: {e}")
            continue
        n_ops_applied = 0
        for json_path, new_url in ops:
            ok, old = _set_json_path(data, json_path, new_url)
            if ok:
                old_tail = (old[-30:] if isinstance(old, str) else "?")
                print(f"      custom.{mf_key}.{json_path}: ...{old_tail} → ...{new_url[-30:]}")
                n_ops_applied += 1
            else:
                print(f"      custom.{mf_key}.{json_path}: PATH NOT FOUND (skipped)")
        if n_ops_applied > 0:
            patched_inputs.append({
                "ownerId": product_id, "namespace": "custom",
                "key": mf_key, "type": "json",
                "value": json.dumps(data, ensure_ascii=False),
            })
            n_patched += 1
    if patched_inputs and not dry_run:
        q = """
        mutation($input: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $input) {
            metafields { id key }
            userErrors { field message code }
          }
        }
        """
        r = shopify_gql(store, token, q, {"input": patched_inputs})
        errs = ((r.get("data") or {}).get("metafieldsSet") or {}).get("userErrors", []) or []
        if errs:
            print(f"      metafieldsSet errors: {errs[:3]}")
    elif patched_inputs and dry_run:
        print(f"      [dry-run] would metafieldsSet {len(patched_inputs)} metafields")
    return n_patched


# ── Metafield URL swap (inline photos) ──────────────────────────────────────
def fetch_json_metafields(store: str, token: str, product_id: str) -> Dict[str, str]:
    """Fetch all custom-namespace JSON metafields of a product.
    Returns {key: raw_value_string}."""
    q = """
    query($id: ID!) {
      product(id: $id) {
        metafields(first: 50, namespace: "custom") {
          edges { node { id key type value } }
        }
      }
    }
    """
    r = shopify_gql(store, token, q, {"id": product_id})
    edges = ((r.get("data") or {}).get("product") or {}).get("metafields", {}).get("edges", [])
    out = {}
    for e in edges:
        n = e["node"]
        if n.get("type") == "json" and n.get("value"):
            out[n["key"]] = n["value"]
    return out


def swap_metafield_urls(store: str, token: str, product_id: str,
                        swap_map: Dict[str, str], dry_run: bool = False) -> int:
    """For each custom-namespace JSON metafield: str.replace(old, new) per
    swap_map entry. metafieldsSet only the metafields whose value actually
    changed. Returns number of metafields patched."""
    if not swap_map:
        return 0
    mfs = fetch_json_metafields(store, token, product_id)
    patched_inputs = []
    n_patched = 0
    for key, raw in mfs.items():
        new_raw = raw
        for old, new in swap_map.items():
            if old and old in new_raw:
                new_raw = new_raw.replace(old, new)
        if new_raw != raw:
            n_replaced = sum(1 for old in swap_map if old in raw)
            patched_inputs.append({
                "ownerId": product_id, "namespace": "custom",
                "key": key, "type": "json", "value": new_raw,
            })
            print(f"      custom.{key}: {n_replaced} URL replacement(s)")
            n_patched += 1
    if patched_inputs and not dry_run:
        q = """
        mutation($input: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $input) {
            metafields { id key }
            userErrors { field message code }
          }
        }
        """
        r = shopify_gql(store, token, q, {"input": patched_inputs})
        errs = ((r.get("data") or {}).get("metafieldsSet") or {}).get("userErrors", []) or []
        if errs:
            print(f"      metafieldsSet errors: {errs[:3]}")
    elif patched_inputs and dry_run:
        print(f"      [dry-run] would metafieldsSet {len(patched_inputs)} metafields")
    return n_patched


def delete_media(store: str, token: str, product_id: str, media_ids: List[str]) -> int:
    """productDeleteMedia. Returns count deleted."""
    if not media_ids:
        return 0
    q = """
    mutation($pid: ID!, $ids: [ID!]!) {
      productDeleteMedia(productId: $pid, mediaIds: $ids) {
        deletedMediaIds
        mediaUserErrors { code field message }
      }
    }
    """
    r = shopify_gql(store, token, q, {"pid": product_id, "ids": media_ids})
    data = r.get("data", {}).get("productDeleteMedia", {})
    errs = data.get("mediaUserErrors", [])
    if errs:
        print(f"    productDeleteMedia errors: {errs[:3]}")
    return len(data.get("deletedMediaIds") or [])


# ── Per-product processing ──────────────────────────────────────────────────
def process_carousel(store: str, token: str, product_id: str,
                     photo_pairs: List[Tuple[Path, dict]],
                     handle: str,
                     replace: bool, dry_run: bool) -> bool:
    """Replace (or append) carousel media for one product. Returns True on success.
    photo_pairs: List of (Path, brief) tuples. Brief.slot is used for SEO naming."""
    if not photo_pairs:
        return True  # nothing to do
    if dry_run:
        existing = list_existing_media(store, token, product_id) if replace else []
        print(f"    [dry-run carousel] would upload {len(photo_pairs)} photos "
              f"{'+ delete ' + str(len(existing)) + ' old' if replace else '(append)'}")
        for ph, brief in photo_pairs:
            slot = brief.get("slot", "carousel-extra")
            seo = seo_filename(handle, slot, ph.suffix)
            print(f"      {ph.name:46.46s} → {seo}")
        return True

    # 1. Snapshot existing media IDs BEFORE attaching new ones (so we can
    # delete the old set even if attach partially succeeds — only delete
    # IDs that existed BEFORE we touched the product).
    # CRITICAL: exclude media that's assigned to a variant (per-variant swatch
    # photos) — deleting those breaks the image-switch-on-variant-select.
    existing_before = []
    if replace:
        _all = list_existing_media(store, token, product_id)
        _variant_media = get_variant_media_ids(store, token, product_id)
        existing_before = [m for m in _all if m not in _variant_media]
        if _variant_media:
            print(f"    carousel: preserving {len(_variant_media)} variant-assigned photos (won't delete)")

    # 2. Stage + upload + attach each photo, renaming to SEO-friendly name
    resource_urls = []
    alts = []
    for ph, brief in photo_pairs:
        slot = brief.get("slot", "carousel-extra")
        seo = seo_filename(handle, slot, ph.suffix)
        ru = staged_upload(store, token, ph, upload_name=seo)
        if ru:
            resource_urls.append(ru)
            alts.append(seo.rsplit(".", 1)[0].replace("-", " "))
            print(f"    + {ph.name[:30]:30s} → {seo}")
        else:
            print(f"    SKIP carousel (upload fail): {ph.name}")
    if not resource_urls:
        print(f"    FAIL carousel: 0/{len(photos)} photos staged — leaving existing media untouched")
        return False
    new_ids = attach_media(store, token, product_id, resource_urls, alts)
    print(f"    carousel: attached {len(new_ids)}/{len(resource_urls)} new media")
    if not new_ids:
        return False

    # 3. Only NOW delete old media (and only what existed before we started)
    if replace and existing_before:
        n_del = delete_media(store, token, product_id, existing_before)
        print(f"    carousel: deleted {n_del}/{len(existing_before)} old media")
    return True


def process_inline(store: str, token: str, product_id: str,
                   inline_pairs: List[Tuple[Path, dict]], handle: str,
                   dry_run: bool) -> bool:
    """Upload inline photos to Shopify Files and swap their URLs into metafield JSONs.

    PREFERRED PATH (path-aware): if brief.slot is in SLOT_TARGETS, route the
    new URL directly to the known metafield JSON path (e.g. inline-hero →
    custom.hero.image_url). Solves URL-collision case where Designer dedupes
    the same source_url across multiple metafield image_url fields.

    FALLBACK PATH (global str.replace): for unknown slots, fall back to the
    old behaviour — find source_url anywhere in metafield JSON and replace.
    """
    if not inline_pairs:
        return True
    if dry_run:
        n_targeted = sum(1 for _, b in inline_pairs if b.get("slot") in SLOT_TARGETS)
        n_fallback = len(inline_pairs) - n_targeted
        print(f"    [dry-run inline] would upload {len(inline_pairs)} photos to Files "
              f"({n_targeted} path-aware swap + {n_fallback} global str.replace)")
        for ph, brief in inline_pairs:
            slot = brief.get('slot', '?')
            tgt = SLOT_TARGETS.get(slot)
            tgt_label = (f"→ custom.{tgt[0][0]}.{tgt[0][1]}" if tgt
                         else f"(fallback global swap, source_url={brief.get('source_url','')[:40]}...)")
            print(f"      {ph.name:40s} slot={slot:24s} {tgt_label}")
        return True

    # Phase 1: upload all photos in parallel-ish (sequential — Shopify rate-limits)
    targeted: List[Tuple[str, str, str]] = []  # (mf_key, json_path, new_url)
    fallback_swap: Dict[str, str] = {}         # old_url → new_url (legacy mode)

    for ph, brief in inline_pairs:
        slot = brief.get('slot', '')
        seo = seo_filename(handle, slot or "inline-extra", ph.suffix)
        new_url = upload_file_only(store, token, ph, upload_name=seo)
        if not new_url:
            print(f"    SKIP inline (upload to Files fail): {ph.name}")
            continue
        print(f"    inline uploaded: {ph.name} -> {seo} (...{new_url[-40:]})")

        if slot in SLOT_TARGETS:
            # Path-aware route
            for mf_key, json_path in SLOT_TARGETS[slot]:
                targeted.append((mf_key, json_path, new_url))
        else:
            # Fallback: global str.replace by source_url
            old_url = brief.get('source_url', '') or ''
            if old_url.startswith('http'):
                fallback_swap[old_url] = new_url
            else:
                print(f"    WARN: slot={slot!r} not in SLOT_TARGETS AND no source_url — "
                      f"photo uploaded to Files but no metafield will reference it")

    n_total_patched = 0
    if targeted:
        print(f"    inline: path-aware patching {len(targeted)} target(s)...")
        n_total_patched += swap_inline_targeted(store, token, product_id, targeted, dry_run=False)
    if fallback_swap:
        print(f"    inline: fallback global swap for {len(fallback_swap)} URL(s)...")
        n_total_patched += swap_metafield_urls(store, token, product_id, fallback_swap, dry_run=False)

    print(f"    inline: patched {n_total_patched} metafields total")
    return n_total_patched > 0 or not (targeted or fallback_swap)


def process_variant_photos(store: str, token: str, product_id: str,
                           variant_files: List[Path], handle: str,
                           dry_run: bool) -> bool:
    """Replace each variant's featured swatch with the operator-edited photo.

    variant_files: mtime-ordered edited images from photos/variants/.
    Mapped 1:1 by position to the product's variants (variant order). For
    each: upload edited image → poll READY → detach old swatch → append new
    as the variant's featured image.
    """
    if not variant_files:
        return True
    # Fetch variants in order + their current featured image
    r = shopify_gql(store, token,
                    'query($id:ID!){product(id:$id){variants(first:100){nodes{id title image{id} selectedOptions{value}}}}}',
                    {"id": product_id})
    variants = (((r.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes", [])
    if not variants:
        print("    [variants] product has no variants — skipping")
        return True
    n = min(len(variant_files), len(variants))
    print(f"    [variants] {len(variant_files)} edited photos ↔ {len(variants)} variants")
    if dry_run:
        for i in range(n):
            vname = " ".join(so.get("value", "") for so in (variants[i].get("selectedOptions") or [])) or variants[i]["title"]
            print(f"      {variant_files[i].name:40.40s} → variant '{vname}'")
        return True

    assigned = 0
    for i in range(n):
        v = variants[i]
        ph = variant_files[i]
        vname = " ".join(so.get("value", "") for so in (v.get("selectedOptions") or [])) or v["title"]
        seo = seo_filename(handle, f"variant-{vname}", ph.suffix)
        # Upload as product media (poll READY) — reuse upload_file_only flow but
        # we need a MediaImage id for the variant, so use staged + productCreateMedia
        ru = staged_upload(store, token, ph, upload_name=seo)
        if not ru:
            print(f"      SKIP variant '{vname}' (upload fail)")
            continue
        rc = shopify_gql(store, token,
                         "mutation($pid:ID!,$m:[CreateMediaInput!]!){productCreateMedia(productId:$pid,media:$m){"
                         "media{id status} mediaUserErrors{field message}}}",
                         {"pid": product_id, "m": [{"originalSource": ru,
                                                    "mediaContentType": "IMAGE", "alt": f"{vname} variant"}]})
        md = (((rc.get("data") or {}).get("productCreateMedia") or {}).get("media") or [])
        if not md:
            continue
        mid = md[0]["id"]
        # poll READY
        ready = False
        for _ in range(20):
            time.sleep(1.5)
            pr = shopify_gql(store, token, 'query($id:ID!){node(id:$id){... on MediaImage{status}}}', {"id": mid})
            st = ((pr.get("data") or {}).get("node") or {}).get("status")
            if st == "READY":
                ready = True
                break
            if st == "FAILED":
                break
        if not ready:
            continue
        # detach old swatch (so edited becomes the featured)
        old_img = (v.get("image") or {}).get("id")
        if old_img:
            shopify_gql(store, token,
                        "mutation($pid:ID!,$ids:[ID!]!){productVariantDetachMedia(productId:$pid,variantMedia:[{variantId:$vid,mediaIds:$ids}]){userErrors{message}}}".replace("$vid", '"%s"' % v["id"]),
                        {"pid": product_id, "ids": [old_img]})
        ra = shopify_gql(store, token,
                         "mutation($pid:ID!,$vm:[ProductVariantAppendMediaInput!]!){"
                         "productVariantAppendMedia(productId:$pid,variantMedia:$vm){userErrors{field message}}}",
                         {"pid": product_id, "vm": [{"variantId": v["id"], "mediaIds": [mid]}]})
        ae = (((ra.get("data") or {}).get("productVariantAppendMedia") or {}).get("userErrors") or [])
        if not any("already" not in (e.get("message") or "").lower() for e in ae):
            assigned += 1
            print(f"      + variant '{vname}' → {seo}")
        time.sleep(0.3)
    print(f"    [variants] assigned {assigned}/{n} edited swatches")
    return True


def process_product(store: str, token: str, product_id: str, photos: List[Path],
                    inner_manifest: Dict[str, dict],
                    replace: bool, dry_run: bool,
                    do_carousel: bool, do_inline: bool) -> bool:
    """Dispatch to process_carousel and/or process_inline based on slot
    classification (from inner manifest).

    Resolution order for filename → slot mapping:
      1. BUCKET layout: photos/carousel/ + photos/inline/ subfolders → per-scope mtime-position match
      2. AUTO-MATCH: flat photos/ with random names → cross-scope mtime-position match
      3. EXACT: filename already matches a manifest key → use brief as-is
    """
    # PRIORITY 1: explicit bucket subfolders (operator-friendly)
    # Need to re-get the product folder from one photo's path
    if photos:
        product_folder = photos[0].parent
        # If photos came from photos/<scope>/, the parent is the bucket dir
        # → walk up to actual product folder
        if product_folder.name in ("carousel", "inline"):
            product_folder = product_folder.parent.parent
        elif product_folder.name == "photos":
            product_folder = product_folder.parent
        buckets = detect_bucket_layout(product_folder)
        if buckets:
            print(f"    [bucket layout detected] scopes: {list(buckets.keys())}")
            # Pull variant-bucket files OUT — they map to variants, not carousel/inline
            variant_bucket = buckets.pop("variants", [])
            if variant_bucket:
                _vset = {p.resolve() for p in variant_bucket}
                photos = [p for p in photos if p.resolve() not in _vset]
            inner_manifest = remap_by_buckets(buckets, inner_manifest)
        else:
            variant_bucket = []
            # PRIORITY 2: flat photos/ → fallback auto-match by mtime
            inner_manifest = auto_match_by_position(photos, inner_manifest)
    else:
        variant_bucket = []
    carousel_list, inline_pairs = split_photos_by_slot(photos, inner_manifest)
    print(f"    split: {len(carousel_list)} carousel, {len(inline_pairs)} inline "
          f"({'no manifest' if not inner_manifest else 'manifest present'})")
    # Extract handle from product folder name (format: <PID>__<handle>) — used
    # to build SEO upload names like crest-3d-white-carousel-hero.jpg
    handle = "product"
    if photos:
        prod_folder_name = photos[0].parent.name
        if prod_folder_name in ("carousel", "inline"):
            prod_folder_name = photos[0].parent.parent.parent.name
        elif prod_folder_name == "photos":
            prod_folder_name = photos[0].parent.parent.name
        if "__" in prod_folder_name:
            handle = prod_folder_name.split("__", 1)[1]
        else:
            handle = prod_folder_name
    ok = True
    if do_carousel:
        ok = process_carousel(store, token, product_id, carousel_list, handle, replace, dry_run) and ok
    if do_inline:
        ok = process_inline(store, token, product_id, inline_pairs, handle, dry_run) and ok
    if variant_bucket:
        ok = process_variant_photos(store, token, product_id, variant_bucket, handle, dry_run) and ok
    return ok


# ── Folder/ZIP handling ─────────────────────────────────────────────────────
def resolve_folder(arg: Path) -> Tuple[Path, Optional[Path]]:
    """Returns (working_folder, tempdir_to_clean). Handles --folder being a ZIP."""
    if arg.is_dir():
        return arg, None
    if arg.is_file() and arg.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="upload_edited_"))
        with zipfile.ZipFile(arg) as z:
            z.extractall(tmp)
        # If ZIP wraps a single top-level dir, descend into it
        children = list(tmp.iterdir())
        if len(children) == 1 and children[0].is_dir() and not (tmp / "manifest.json").exists():
            return children[0], tmp
        return tmp, tmp
    raise FileNotFoundError(f"--folder must be a directory or .zip file: {arg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", required=True, type=Path,
                        help="directory (or .zip) with manifest.json + product subfolders")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true",
                      help="DEFAULT: delete existing carousel after new photos attach")
    mode.add_argument("--append", action="store_true",
                      help="keep existing carousel, append new photos at end (inline still swaps)")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--carousel-only", action="store_true",
                       help="skip inline metafield-URL swap, only update carousel")
    scope.add_argument("--inline-only", action="store_true",
                       help="skip carousel, only swap inline photos in metafields")
    parser.add_argument("--only", default=None,
                        help="comma-separated folder names to process (skip others)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show actions without touching Shopify")
    args = parser.parse_args()

    # default = replace (per user preference: full carousel swap)
    replace = not args.append
    do_carousel = not args.inline_only
    do_inline = not args.carousel_only

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)
    store, token = get_shopify_token()
    print(f"Shopify: {store} (token: {token[:6]}...{token[-4:]})")
    scope_label = ("CAROUSEL+INLINE" if do_carousel and do_inline else
                   "CAROUSEL-ONLY" if do_carousel else "INLINE-ONLY")
    print(f"Mode: {scope_label} | carousel={'REPLACE' if replace else 'APPEND'}"
          f"{' [DRY-RUN]' if args.dry_run else ''}")

    folder, cleanup = resolve_folder(args.folder)
    try:
        manifest = load_manifest(folder)
        folders = manifest.get("folders", {})
        if not folders:
            sys.exit(f"manifest.json contains no folders entry")
        only = {s.strip() for s in (args.only or "").split(",") if s.strip()} or None

        print(f"\nFound {len(folders)} products in manifest "
              f"(from {manifest.get('shopify_store','?')}). Processing...")
        ok = 0
        fail = 0
        for folder_name, meta in folders.items():
            if only and folder_name not in only:
                continue
            product_folder = folder / folder_name
            if not product_folder.is_dir():
                print(f"  [skip] {folder_name}: folder missing on disk")
                fail += 1
                continue
            photos = collect_photos(product_folder)
            if not photos:
                print(f"  [skip] {folder_name}: 0 images found")
                fail += 1
                continue
            inner_manifest = load_inner_manifest(product_folder)
            pid = meta["shopify_product_id"]
            print(f"  → {folder_name} ({pid.rsplit('/',1)[-1]}): {len(photos)} photos")
            try:
                if process_product(store, token, pid, photos, inner_manifest,
                                   replace, args.dry_run, do_carousel, do_inline):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"    EXCEPTION: {str(e)[:200]}")
                fail += 1

        print(f"\nDone: {ok} OK, {fail} failed")
        return 0 if fail == 0 else 1
    finally:
        if cleanup and cleanup.exists():
            shutil.rmtree(cleanup, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
