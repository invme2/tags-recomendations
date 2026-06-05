"""prescrape_eprolo.py — sync Playwright pre-scraper to bypass the Windows
async-subprocess bug in ipykernel.

Background: on Windows ipykernel forces WindowsSelectorEventLoopPolicy
(so zmq works), but SelectorEventLoop does NOT support subprocess on
Windows. Playwright async_api uses asyncio.create_subprocess_exec → it
raises NotImplementedError inside the kernel. There's no clean fix that
keeps both zmq and async subprocess working.

Workaround: pre-scrape every product with status='pending' using
sync_playwright FROM A NORMAL PYTHON PROCESS (no kernel involved),
write the scrape_json + status='scraped' to the DB, then let the
notebook's `scrape_eprolo` short-circuit on cached data (see Cell 2
patch in PATCHES.md).

USAGE:
    python pipeline/tools/prescrape_eprolo.py --db <path>
                                              [--limit N] [--state <path>]

The notebook then resumes from status='scraped' and runs the
Strategy/Designer/Shopify-push portion of Cell 6 without ever opening
Playwright itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Force UTF-8 stdout so print(emoji) doesn't crash on cp1251 Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_STATE = REPO_ROOT / "pipeline" / ".eprolo_state.json"

MARKETING_TITLE_SIGNATURES = (
    "EPROLO -", "Sign Up", "Sign In", "Log In", "Login",
    "Dropshipping Supply", "All-in-One Dropshipping",
)


def looks_like_marketing(title: str) -> bool:
    t = (title or "").lower()
    return any(sig.lower() in t for sig in MARKETING_TITLE_SIGNATURES)


def scrape_one(page, url: str) -> dict:
    """Open the URL, extract a minimal product dict matching the shape
    that scrape_eprolo returns in Cell 2 (so the cache short-circuit
    works as a drop-in replacement)."""
    result = {
        "title": "", "description": "", "top_image_urls": [],
        "desc_image_urls": [], "cost_price": 0, "variants": [],
        "specs": {}, "video_urls": [], "shipping_time": "",
        "weight_g": 0, "size_chart": [],
    }
    try:
        page.goto(url, wait_until="networkidle", timeout=60_000)
    except Exception as e:
        result["_scrape_error"] = f"goto failed: {e}"
        return result

    final_url = page.url or ""
    result["_final_url"] = final_url
    if "/app/product/" not in final_url:
        result["_redirect_target"] = final_url
        return result

    # Title — h1 first, then <title>
    try:
        h1 = page.query_selector("h1")
        if h1:
            result["title"] = (h1.inner_text() or "").strip()
    except Exception:
        pass
    if not result["title"]:
        try:
            result["title"] = (page.title() or "").strip()
        except Exception:
            pass

    # Image extraction.
    # EPROLO/Aliyun OSS thumbs have a ?x-oss-process=image/resize,m_pad...
    # query string that ships a TINY ~120px JPG (looks blurry in Shopify
    # gallery as the hero photo). Stripping the query yields the full-res
    # source. Same trick works on `cbu01.alicdn.com` thumbnails.
    def _full_res(src: str) -> str:
        if not src or not src.startswith("http"):
            return ""
        # Drop OSS resize query
        if "?" in src:
            src = src.split("?", 1)[0]
        # Drop Alibaba size suffix like _120x120.jpg, _.webp, _220x_q90.jpg
        import re
        src = re.sub(r"_\d+x\d*(_q\d+)?\.(jpg|jpeg|png|webp)$",
                     lambda m: "." + m.group(2), src, flags=re.IGNORECASE)
        return src

    # Image extraction with size filter.
    # EPROLO renders ~20-50 <img> in DOM — most are UI icons/badges (checkmark,
    # logos, sprite assets). Real product photos are 500-2000px square.
    # Filter by naturalWidth — only keep images >= 300px on the long side.
    MIN_DIM = 300
    EXCLUDE_ALT_KW = ("icon", "logo", "badge", "checkmark", "sprite", "arrow",
                      "star", "flag", "spinner", "loader", "avatar")

    def _harvest(selector: str, store: list, seen: set, max_take: int = 50,
                 apply_size_filter: bool = True):
        try:
            els = page.query_selector_all(selector)
        except Exception:
            return
        for el in els[:max_take]:
            try:
                src = el.get_attribute("src") or el.get_attribute("data-src") or ""
                full = _full_res(src)
                if not full or full in seen:
                    continue
                alt = (el.get_attribute("alt") or "").lower()
                if any(kw in alt for kw in EXCLUDE_ALT_KW):
                    continue
                if apply_size_filter:
                    # Drop tiny icons. naturalWidth is 0 if not loaded; treat as 0.
                    dims = el.evaluate(
                        "img => ({w: img.naturalWidth, h: img.naturalHeight})"
                    )
                    w, h = dims.get("w", 0), dims.get("h", 0)
                    if w and h and max(w, h) < MIN_DIM:
                        continue
                seen.add(full)
                store.append(full)
            except Exception:
                continue

    seen_all = set()
    # SCOPED to .product-image-container — EPROLO's main product gallery
    # block (contains exactly the 7 swiper-slide imgs the buyer sees).
    # Without this scope my selector picked up `F33319EB...jpg` (a global
    # store banner) as the first image for EVERY product. Verified via
    # DOM inspection: chain is img < .swiper-slide < .swiper-ul <
    # .swiper-wrapper < .slide-template2 < .swiper-box < .con-top-left <
    # .product-image-container.
    # Scoped to product gallery — skip size filter because EPROLO renders
    # 100x100 thumbnails in DOM (full-size resolved via query-stripped URL).
    # The container scope alone guarantees these are real product photos.
    _harvest(
        '.product-image-container .swiper-slide img',
        result["top_image_urls"], seen_all, max_take=40,
        apply_size_filter=False,
    )
    # Fallback: some EPROLO products use a legacy DOM layout WITHOUT
    # `.product-image-container` (e.g. Crest 3D in beauty-final-good
    # returned 0 imgs from the scoped selector). Try broader selectors
    # WITH the size filter back on — that filter still drops UI icons
    # but accepts the real gallery photos which are 800-1600px natural.
    if not result["top_image_urls"]:
        _harvest(
            '.swiper-slide img, [class*="big-img"] img, [class*="main-img"] img, '
            '[class*="product-img"] img',
            result["top_image_urls"], seen_all, max_take=20,
            apply_size_filter=True,
        )
    # Description block lives lower on the page; broader selector OK
    # because we already captured the gallery images first.
    _harvest(
        '[class*="product-desc"] img, [class*="product-detail"] img, '
        '[class*="description"] img',
        result["desc_image_urls"], seen_all, max_take=60,
    )

    # Cost price — EPROLO-specific: `.cost-text` cells contain "USD X.XX"
    # for EPROLO Price + Shipping Cost (alternating). The page-wide regex
    # fallback I used before picked $16.23 from some store-wide JSON, NOT
    # the real per-product price. Now scoped to `.product-info .cost-text`
    # and we grab the MINIMUM USD value (excludes shipping which is higher).
    import re
    variant_prices = []
    try:
        cost_cells = page.query_selector_all('.product-info .cost-text')
        for el in cost_cells[:20]:
            try:
                txt = (el.inner_text() or "").strip()
            except Exception:
                continue
            # Match "USD 4.96" or "$ 4.96"
            m = re.search(r"(?:USD|\$)\s*(\d+(?:\.\d+)?)", txt)
            if m:
                try:
                    v = float(m.group(1))
                    if 0.5 <= v <= 5000:
                        variant_prices.append(v)
                except ValueError:
                    pass
    except Exception:
        pass
    if variant_prices:
        # Filter sub-$1 values (usually wholesale shipping / promo deltas).
        # Take MIN as the customer-facing "starting from" base price — the
        # cheapest variant the user lists is what drives the visible
        # storefront price (Shopify shows "from $X" automatically for
        # multi-variant products). Previous MAX logic captured EPROLO's
        # tier-pricing top tier (e.g. $66.96 for 1pc retail) which
        # multiplied by RETAIL_MARKUP=5 produced absurd $329.90 prices.
        real_prices = [p for p in variant_prices if p >= 1.50]
        result["cost_price"] = min(real_prices) if real_prices else min(variant_prices)
        result["_variant_prices"] = variant_prices

    # ── v10: Element-UI variant table extraction ──
    # EPROLO uses .el-form-item > .el-table to expose option axes (color /
    # size / NET WT / etc). Each .el-table__row = one variant value with
    # cells [name, price, stock, shipping, weight].
    # Skip "default" single-row tables (= product has no real variants).
    variants_raw = []
    try:
        form_items = page.query_selector_all('.el-form-item')
        for fi in form_items:
            try:
                lbl_el = fi.query_selector('.el-form-item__label')
                if not lbl_el:
                    continue
                label_text = (lbl_el.inner_text() or "").strip().rstrip(':')
                if not label_text:
                    continue
                rows = fi.query_selector_all('.el-table__row')
                if not rows:
                    continue
                values = []
                value_prices = {}
                value_photos = {}  # {value_name: featured photo URL}
                for row in rows:
                    cells = row.query_selector_all('td')
                    if not cells:
                        continue
                    name = (cells[0].inner_text() or "").strip()
                    if not name or len(name) > 60:
                        continue
                    if name in values:
                        continue
                    values.append(name)
                    if len(cells) > 1:
                        ptxt = (cells[1].inner_text() or "").strip()
                        pm = re.search(r"(?:USD|\$)\s*(\d+(?:\.\d+)?)", ptxt)
                        if pm:
                            try:
                                pv = float(pm.group(1))
                                if 0.5 <= pv <= 5000:
                                    value_prices[name] = pv
                            except ValueError:
                                pass
                    # Capture per-variant featured photo: click row → read the
                    # first /attached/pingtai/ image in the rendered gallery.
                    try:
                        row.scroll_into_view_if_needed(timeout=3000)
                        row.click(timeout=4000)
                        page.wait_for_timeout(900)
                        srcs = page.evaluate(
                            '() => [...document.querySelectorAll("img")]'
                            '.map(i => i.currentSrc || i.src).filter(Boolean)'
                        )
                        for s in srcs or []:
                            if "/attached/pingtai/" in s and "x-oss-process" not in s:
                                value_photos[name] = s.split("?")[0]
                                break
                    except Exception:
                        pass
                # Skip ANY single-value axis — Shopify shouldn't have option
                # picker with only 1 choice (no actual variant for customer).
                if len(values) <= 1:
                    continue
                if values:
                    entry = {"option_name": label_text, "values": values}
                    if value_prices:
                        entry["_value_prices"] = value_prices
                    if value_photos:
                        entry["_value_photos"] = value_photos
                    variants_raw.append(entry)
            except Exception:
                continue
    except Exception:
        pass
    if variants_raw:
        result["variants"] = variants_raw[:3]  # Shopify max 3 option axes

    # Specs — table rows
    try:
        spec_rows = page.query_selector_all(
            '[class*="spec"] tr, [class*="detail"] tr, [class*="param"] tr, '
            '[class*="attribute"] tr, [class*="info-item"], [class*="product-prop"]'
        )
        specs = {}
        for row in spec_rows[:40]:
            try:
                txt = (row.inner_text() or "").strip()
                if ":" in txt:
                    k, _, v = txt.partition(":")
                    if k and v and len(k) < 80:
                        specs[k.strip()] = v.strip()
            except Exception:
                pass
        if specs:
            result["specs"] = specs
    except Exception:
        pass

    # ── Product video(s) — EPROLO carousel <video> ──
    # Pattern: shopifyfile.*aliyuncs.com/attached/video/product/<id>.mp4
    # Strip ?x-oss-process (that's the poster-snapshot variant).
    try:
        import re as _re_v
        videos = []
        for v in page.query_selector_all('video[src], video source'):
            src = v.get_attribute('src') or ''
            if src and '.mp4' in src.lower():
                clean = src.split('?')[0]
                if clean not in videos:
                    videos.append(clean)
        # Regex fallback over page HTML for /attached/video/*.mp4
        try:
            page_html = page.content()
        except Exception:
            page_html = ""
        for m in _re_v.finditer(r'https?://[^\s"\'<>\)]+/attached/video/[^\s"\'<>\)]+\.mp4', page_html):
            clean = m.group(0).split('?')[0]
            if clean not in videos:
                videos.append(clean)
        if videos:
            result["video_urls"] = videos[:3]
    except Exception:
        pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path,
                        help="path to pipeline.db")
    parser.add_argument("--state", type=Path, default=None,
                        help="path to eprolo_state.json (default: from EPROLO_STATE_FILE env or pipeline/.eprolo_state.json)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only scrape first N pending products")
    parser.add_argument("--rescrape-errors", action="store_true",
                        help="also rescrape products in status='error' (default: only pending)")
    args = parser.parse_args()

    load_dotenv(ENV_FILE, override=True)

    state_path = args.state or Path(os.environ.get("EPROLO_STATE_FILE", str(DEFAULT_STATE)))
    if not state_path.exists():
        sys.exit(f"storage_state not found at {state_path}. Run eprolo_login.py first.")

    if not args.db.exists():
        sys.exit(f"DB not found: {args.db}")

    db = sqlite3.connect(str(args.db))
    db.row_factory = sqlite3.Row
    statuses = ("pending", "error") if args.rescrape_errors else ("pending",)
    placeholders = ",".join("?" * len(statuses))
    rows = db.execute(
        f"SELECT id, name, eprolo_url FROM products "
        f"WHERE status IN ({placeholders}) ORDER BY id",
        statuses,
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(f"no products with status in {statuses} in {args.db} — nothing to do.")
        return 0

    print(f"prescrape: {len(rows)} products against {args.db}")
    print(f"storage_state: {state_path}")
    print()

    n_ok = 0
    n_redirect = 0
    n_err = 0
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=str(state_path),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        for i, row in enumerate(rows, 1):
            pid = row["id"]
            name = (row["name"] or "")[:60]
            url = row["eprolo_url"]
            print(f"[{i}/{len(rows)}] id={pid} {name}")
            print(f"   {url}")
            page = ctx.new_page()
            try:
                data = scrape_one(page, url)
            finally:
                try:
                    page.close()
                except Exception:
                    pass

            title = data.get("title", "")
            redirect = data.get("_redirect_target")
            if "_scrape_error" in data:
                status = "error"
                err = data["_scrape_error"]
                n_err += 1
                marker = "ERR"
            elif redirect:
                status = "error"
                err = f"EPROLO redirect to {redirect[:120]}"
                n_redirect += 1
                marker = "REDIR"
            elif not title or looks_like_marketing(title):
                status = "error"
                err = f"marketing/empty title: {title[:80]!r}"
                n_redirect += 1
                marker = "MKT"
            else:
                status = "scraped"
                err = None
                n_ok += 1
                marker = "OK"

            db.execute(
                "UPDATE products SET scrape_json=?, status=?, error_msg=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), status, err, pid),
            )
            db.commit()
            print(f"   -> {marker}: title={title[:80]!r}, "
                  f"images={len(data.get('top_image_urls',[]))}/"
                  f"{len(data.get('desc_image_urls',[]))}, "
                  f"price={data.get('cost_price', 0)}")
            print()

        browser.close()

    elapsed = time.time() - t0
    print(f"prescrape done in {elapsed:.1f}s — ok={n_ok}, redirect/mkt={n_redirect}, err={n_err}")

    # Post-scrape dedup: if multiple EPROLO URLs returned the same product
    # (alias / SEO-slug duplicate listings — happens on EPROLO), mark all
    # but the first as 'error' so they don't get duplicated into Shopify.
    # Match by normalized scraped title.
    print()
    print("--- dedup pass ---")
    rows_after = db.execute(
        "SELECT id, name, eprolo_url, scrape_json FROM products "
        "WHERE status='scraped' AND scrape_json IS NOT NULL ORDER BY id"
    ).fetchall()
    seen_titles = {}  # normalized_title -> first product id
    n_dup = 0
    for r in rows_after:
        try:
            data = json.loads(r["scrape_json"])
        except Exception:
            continue
        title = (data.get("title") or "").strip().lower()
        # Normalize — strip punctuation + collapse whitespace
        import re as _re
        norm = _re.sub(r"[^a-z0-9]+", " ", title).strip()
        if not norm:
            continue
        if norm in seen_titles:
            first_pid = seen_titles[norm]
            err = (f"Duplicate EPROLO product: scrape title matches "
                   f"product #{first_pid}. EPROLO returned same product "
                   f"for two CSV URLs (alias / SEO-slug duplicate).")
            db.execute("UPDATE products SET status=?, error_msg=? WHERE id=?",
                       ("error", err, r["id"]))
            print(f"  DUP [{r['id']:2d}] -> error (matches #{first_pid}): {title[:60]}")
            n_dup += 1
        else:
            seen_titles[norm] = r["id"]
    db.commit()
    if n_dup:
        print(f"flagged {n_dup} duplicates")
    else:
        print("no duplicates detected")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
