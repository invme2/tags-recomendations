#!/usr/bin/env python3
"""process_photo_intake.py — intake folder + SHA-256 BLACKLIST for edited photo
packs, with automatic product resolution and SEO-named upload.

Drop single-product photo-pack ZIPs into pipeline/runs/photo_intake/ and run.
Each ZIP (manifest.json with 'briefs'; edited photos in photos/carousel/ and
photos/inline/) is:
  1. mapped to its Shopify product by ZIP-name slug == product handle
     (fallback: EPROLO-origin title in custom.source);
  2. re-wrapped into the master layout upload_edited_photos.py expects;
  3. uploaded — carousel -> product media with SEO filenames (<handle>-<slot>.ext),
     inline -> Shopify Files + metafield URL swap;
  4. recorded by SHA-256 in _processed.json. Re-sending the SAME archive (even
     renamed) is SKIPPED. Re-editing a photo (content changes) -> processed anew.

USAGE
  python pipeline/tools/process_photo_intake.py            # process new
  python pipeline/tools/process_photo_intake.py --dry-run  # resolve only, no upload
  python pipeline/tools/process_photo_intake.py --list     # show blacklist
  python pipeline/tools/process_photo_intake.py --force    # reprocess all
  python pipeline/tools/process_photo_intake.py --mode append
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, zipfile
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
INTAKE = ROOT / "pipeline" / "runs" / "photo_intake"
BLACKLIST = INTAKE / "_processed.json"
UPLOADER = ROOT / "pipeline" / "tools" / "upload_edited_photos.py"
LINKS_OUT = INTAKE / "_updated_links.txt"
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def _gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                       "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=60).json()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_bl():
    if BLACKLIST.exists():
        try:
            return json.loads(BLACKLIST.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_bl(bl):
    BLACKLIST.write_text(json.dumps(bl, indent=2, ensure_ascii=False), encoding="utf-8")


def slug_of(z: Path) -> str:
    n = re.sub(r"^photo[-_]pack[-_]", "", z.stem)
    n = re.sub(r"[-_][0-9a-f]{8}$", "", n)
    return n.replace("_", "-")


def resolve_product(tok, z: Path):
    """Return product dict {id,title,handle} or None. Primary: slug==handle."""
    h = slug_of(z)
    r = _gql(tok, "query($q:String!){products(first:1,query:$q){nodes{id title handle}}}",
             {"q": f"handle:{h}"})
    n = (r.get("data", {}).get("products", {}).get("nodes") or [])
    if n:
        return n[0]
    # fallback: EPROLO-origin title in custom.source
    try:
        m = json.loads(zipfile.ZipFile(z).read("manifest.json"))
        pt = (m.get("product_title") or "").strip()
        if pt:
            r2 = _gql(tok,
                'query($q:String!){products(first:8,query:$q){nodes{id title handle '
                'source:metafield(namespace:"custom",key:"source"){value}}}}',
                {"q": " ".join(pt.split()[:5])})
            for nn in (r2.get("data", {}).get("products", {}).get("nodes") or []):
                src = (nn.get("source") or {}).get("value", "") or ""
                if pt[:28].lower() in src.lower():
                    return nn
    except Exception:
        pass
    return None


def build_master(z: Path, handle: str, pid: str) -> Path:
    """Re-wrap a single-product pack into the master layout (only the edited
    carousel/ + inline/ bucket photos + inner manifest)."""
    tmp = Path(tempfile.mkdtemp(prefix="pf_master_"))
    folder = tmp / handle
    (folder / "photos").mkdir(parents=True)
    with zipfile.ZipFile(z) as zf:
        try:
            (folder / "manifest.json").write_bytes(zf.read("manifest.json"))
        except KeyError:
            pass
        for name in zf.namelist():
            low = name.lower()
            if not low.endswith(IMG_EXT):
                continue
            if "/carousel/" in low:
                bucket = "carousel"
            elif "/inline/" in low:
                bucket = "inline"
            else:
                continue  # skip the flat reference photos/01-*.jpg (originals)
            dest = folder / "photos" / bucket / Path(name).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))
    (tmp / "manifest.json").write_text(
        json.dumps({"folders": {handle: {"shopify_product_id": pid, "handle": handle}}},
                   ensure_ascii=False), encoding="utf-8")
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="resolve products, no upload")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--mode", default="replace", choices=["replace", "append"])
    args = ap.parse_args()
    INTAKE.mkdir(parents=True, exist_ok=True)
    bl = load_bl()

    if args.list:
        print(f"Обработано архивов: {len(bl)}")
        for h, m in sorted(bl.items(), key=lambda kv: kv[1].get("processed_at", "")):
            print(f"  {m.get('filename','?'):<48} {m.get('processed_at','')}  "
                  f"→ {m.get('handle','?')}  sha={h[:12]}")
        return 0

    zips = sorted(set(list(INTAKE.glob("*.zip")) + list(INTAKE.glob("*.ZIP"))))
    if not zips:
        print(f"В интейке нет архивов: {INTAKE}")
        return 0

    tok = _token()
    print(f"Интейк: {INTAKE} | архивов: {len(zips)} | в блэклисте: {len(bl)}\n")
    done = skipped = failed = 0
    updated_links = []
    for z in zips:
        h = sha256(z)
        if h in bl and not args.force:
            skipped += 1
            print(f"  ⏭  ПРОПУСК (обработан): {z.name}")
            continue
        prod = resolve_product(tok, z)
        if not prod:
            failed += 1
            print(f"  ❓ {z.name}: товар НЕ найден (slug '{slug_of(z)}') — пропуск")
            continue
        link = f"https://wanelo.com/products/{prod['handle']}"
        if args.dry_run:
            print(f"  ▶  {z.name}\n       → {prod['title'][:45]} | {link}")
            continue
        master = build_master(z, prod["handle"], prod["id"])
        try:
            print(f"  ▶  {z.name} → {prod['handle']} …")
            r = subprocess.run([sys.executable, str(UPLOADER), "--folder", str(master),
                                f"--{args.mode}"], cwd=str(ROOT))
            if r.returncode == 0:
                bl[h] = {"filename": z.name, "handle": prod["handle"],
                         "product_id": prod["id"], "size_bytes": z.stat().st_size,
                         "processed_at": datetime.now().isoformat(timespec="seconds"),
                         "mode": args.mode}
                save_bl(bl)
                done += 1
                updated_links.append((prod["title"], link))
                print(f"  ✅ {prod['handle']} обновлён + в блэклист\n       {link}\n")
            else:
                failed += 1
                print(f"  ❌ {z.name}: ошибка аплоадера (НЕ в блэклист)\n")
        finally:
            shutil.rmtree(master, ignore_errors=True)

    # Carousel REPLACE deletes old gallery media that metafields (features/story)
    # may still reference -> repair those broken image_urls automatically.
    if done and not args.dry_run:
        print("\n— авто-репар битых image_url в метафилдах (замена карусели удаляет старые медиа) —")
        fixer = ROOT / "pipeline" / "tools" / "fix_broken_metafield_images.py"
        fix_args = [sys.executable, str(fixer), "--execute"]
        for _t, _u in updated_links:
            fix_args += ["--handle", _u.rsplit("/", 1)[-1]]
        subprocess.run(fix_args, cwd=str(ROOT))

        # Extra inline photos (more than the manifest's inline briefs) get
        # uploaded to Files but referenced nowhere -> place them into
        # lifestyle_gallery so nothing the operator made is wasted.
        print("— авто-размещение лишних inline-фото в lifestyle_gallery —")
        placer = ROOT / "pipeline" / "tools" / "place_orphan_photos.py"
        place_args = [sys.executable, str(placer), "--execute"]
        for _t, _u in updated_links:
            place_args += ["--handle", _u.rsplit("/", 1)[-1]]
        subprocess.run(place_args, cwd=str(ROOT))

    if updated_links:
        LINKS_OUT.write_text("\n".join(f"{t}\n  {u}" for t, u in updated_links), encoding="utf-8")
    if not args.dry_run:
        print(f"Итог: обновлено {done}, пропущено {skipped}, ошибок {failed}. "
              f"Блэклист: {len(bl)}.")
        if updated_links:
            print(f"Ссылки на обновлённые: {LINKS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
