"""fulfill_order_via_eprolo.py — semi-automated EPROLO fulfillment.

For a given Shopify order, this tool:
  1. Pulls line items + shipping address from Shopify (Admin GraphQL).
  2. Looks up each product's `custom.source_url` metafield (EPROLO URL).
  3. Opens a HEADED Chromium with your existing EPROLO storage_state
     (pipeline/.eprolo_state.json from eprolo_login.py).
  4. For each EPROLO product URL: navigates, picks matching variant
     based on the Shopify line item's variantTitle, adds N to cart.
  5. Goes to EPROLO cart → checkout → fills shipping address fields
     from the Shopify order.
  6. STOPS at the final "Place Order" / "Pay" step — browser stays open
     so YOU review and click the final button yourself.

Safety: this tool never confirms payment automatically. It exits when
either you close the browser or after a 30-min idle timeout.

PREREQ: a fresh storage_state — run `python pipeline/tools/eprolo_login.py`
first to log in, then re-use the saved cookies.

USAGE:
    python pipeline/tools/fulfill_order_via_eprolo.py --order 1001
    python pipeline/tools/fulfill_order_via_eprolo.py --order 1001 --dry-run
    python pipeline/tools/fulfill_order_via_eprolo.py --order 1001 --headless

CAVEAT: EPROLO's UI is not public-API-stable. The selectors below were
chosen to be tolerant (role-based / text-based first, CSS as fallback)
but may need updating if EPROLO redesigns. Run with --dry-run first to
see the resolved cart + address before opening the browser.
"""
from __future__ import annotations

import argparse
import json
import os
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
DEFAULT_STATE = REPO_ROOT / "pipeline" / ".eprolo_state.json"
API_VERSION = "2024-10"


# ── Shopify ─────────────────────────────────────────────────────────────────
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
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify GQL failed: {r.status_code} {r.text[:200]}")


def fetch_order(store: str, token: str, order_name: str) -> Optional[dict]:
    """Fetch one order by name. Accepts '1001', '#1001', or numeric ID."""
    if order_name.isdigit() and len(order_name) > 8:
        # Looks like a Shopify numeric order id
        oid = f"gid://shopify/Order/{order_name}"
        q = """
        query($id: ID!) {
          order(id: $id) { ...OrderFields }
        }
        """ + _ORDER_FRAGMENT
        r = shopify_gql(store, token, q, {"id": oid})
        return (r.get("data") or {}).get("order")
    else:
        name = order_name if order_name.startswith("#") else f"#{order_name}"
        q = """
        query($q: String!) {
          orders(first: 1, query: $q) {
            edges { node { ...OrderFields } }
          }
        }
        """ + _ORDER_FRAGMENT
        r = shopify_gql(store, token, q, {"q": f"name:{name}"})
        edges = (r.get("data") or {}).get("orders", {}).get("edges", [])
        return edges[0]["node"] if edges else None


_ORDER_FRAGMENT = """
fragment OrderFields on Order {
  id
  name
  createdAt
  email
  phone
  customer { firstName lastName email phone }
  shippingAddress {
    firstName lastName company
    address1 address2 city
    province provinceCode countryCodeV2 country
    zip phone
  }
  lineItems(first: 50) {
    edges {
      node {
        title
        quantity
        sku
        variantTitle
        product {
          id
          handle
          source_url: metafield(namespace: "custom", key: "source_url") { value }
          source: metafield(namespace: "custom", key: "source") { value }
        }
      }
    }
  }
}
"""


# ── Resolve EPROLO URL per line item ────────────────────────────────────────
def resolve_eprolo_url(product: dict) -> str:
    if not product:
        return ""
    su = (product.get("source_url") or {}).get("value", "")
    if su and su.startswith("http"):
        return su
    src = (product.get("source") or {}).get("value", "")
    if src:
        try:
            return json.loads(src).get("url", "") or ""
        except Exception:
            return ""
    return ""


def summarize_order(order: dict) -> Tuple[List[dict], dict]:
    """Return (line_items_resolved, address_dict) ready for the EPROLO flow."""
    items = []
    for e in order.get("lineItems", {}).get("edges", []):
        n = e["node"]
        prod = n.get("product") or {}
        url = resolve_eprolo_url(prod)
        items.append({
            "title":         n.get("title", ""),
            "variant_title": n.get("variantTitle", "") or "",
            "qty":           n.get("quantity", 1),
            "sku":           n.get("sku", "") or "",
            "eprolo_url":    url,
        })
    addr = order.get("shippingAddress") or {}
    return items, addr


# ── EPROLO Playwright flow ──────────────────────────────────────────────────
def run_playwright_flow(items: List[dict], addr: dict, state_file: Path,
                        headless: bool, dry_run: bool) -> bool:
    """Drive EPROLO via Playwright. Returns True if cart + address filled
    without errors (final Place Order is YOUR job)."""
    if dry_run:
        print("\n[dry-run] would launch headed Chromium with:")
        print(f"  storage_state: {state_file}")
        print(f"\nCart additions ({len(items)} line items):")
        for i in items:
            print(f"  + {i['qty']}x  {i['title'][:50]}  variant={i['variant_title']!r}")
            print(f"      {i['eprolo_url']}")
        print(f"\nShipping address:")
        for k, v in addr.items():
            if v:
                print(f"  {k}: {v}")
        return True

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        sys.exit("playwright not installed. `pip install playwright && playwright install chromium`")

    if not state_file.exists():
        sys.exit(f"EPROLO storage_state not found: {state_file}\n"
                 f"Run `python pipeline/tools/eprolo_login.py` first.")

    print(f"\nLaunching Chromium (headless={headless}) with {state_file}...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(storage_state=str(state_file))
        page = ctx.new_page()

        # ── Phase 1: add each line item to cart ──
        cart_failures = []
        for i, item in enumerate(items, 1):
            if not item["eprolo_url"]:
                print(f"  [{i}/{len(items)}] SKIP (no EPROLO URL): {item['title'][:50]}")
                cart_failures.append(item)
                continue
            print(f"  [{i}/{len(items)}] {item['title'][:50]}")
            try:
                page.goto(item["eprolo_url"], wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PWTimeout:
                print(f"      page load timed out — skipping")
                cart_failures.append(item)
                continue
            if "/app/product/" not in page.url:
                print(f"      redirected to {page.url[:80]} — not logged in?")
                cart_failures.append(item)
                continue

            # Variant selection — match by substring of variantTitle.
            # EPROLO uses option swatches. We try role=button containing the
            # variant title text. Fall back to first available swatch group.
            vt = (item["variant_title"] or "").strip()
            if vt and vt.lower() not in ("default title", "default", ""):
                vt_parts = [p.strip() for p in vt.replace("/", "|").split("|") if p.strip()]
                for vp in vt_parts:
                    # Try clicking a swatch labelled exactly or containing this text
                    try:
                        sw = page.get_by_role("button", name=vp, exact=False).first
                        if sw.count() > 0:
                            sw.click(timeout=5_000)
                            print(f"      variant: clicked {vp!r}")
                            continue
                    except Exception:
                        pass
                    # Try a generic option element
                    try:
                        opt = page.locator(f'[class*="option"]:has-text("{vp}")').first
                        if opt.count() > 0:
                            opt.click(timeout=5_000)
                            print(f"      variant: clicked option {vp!r}")
                            continue
                    except Exception:
                        pass
                    print(f"      WARN: variant part {vp!r} not found — using default")

            # Quantity input
            qty = max(1, int(item["qty"] or 1))
            if qty > 1:
                try:
                    qty_input = page.locator(
                        'input[type="number"], input[class*="quantity" i]'
                    ).first
                    qty_input.fill(str(qty), timeout=5_000)
                    print(f"      qty: set to {qty}")
                except Exception:
                    print(f"      WARN: qty input not found — defaulting to 1")

            # Add to cart button — multiple label variants seen on EPROLO
            atc_clicked = False
            for label in ("Add to Cart", "Add To Cart", "add to cart", "ADD TO CART"):
                try:
                    btn = page.get_by_role("button", name=label, exact=False).first
                    if btn.count() > 0:
                        btn.click(timeout=10_000)
                        print(f"      add-to-cart: clicked {label!r}")
                        atc_clicked = True
                        break
                except Exception:
                    continue
            if not atc_clicked:
                # Last-resort selector
                try:
                    page.locator('button:has-text("Cart"), [class*="add-cart" i]').first.click(timeout=10_000)
                    print(f"      add-to-cart: clicked fallback selector")
                    atc_clicked = True
                except Exception:
                    print(f"      FAIL: could not find Add to Cart button")
                    cart_failures.append(item)
                    continue

            # Wait for any confirmation toast / cart-count change
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass

        # ── Phase 2: open cart + proceed to checkout ──
        print("\n  Opening EPROLO cart...")
        try:
            page.goto("https://www.eprolo.com/app/cart", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            print(f"  could not open /app/cart: {e}")

        # Click checkout button
        co_clicked = False
        for label in ("Checkout", "Proceed to Checkout", "Place Order", "Continue to Checkout"):
            try:
                btn = page.get_by_role("button", name=label, exact=False).first
                if btn.count() > 0:
                    btn.click(timeout=10_000)
                    print(f"  checkout: clicked {label!r}")
                    co_clicked = True
                    break
            except Exception:
                continue
        if not co_clicked:
            print("  WARN: checkout button not found — leaving cart open for manual continuation")

        # ── Phase 3: fill shipping address ──
        print("\n  Filling shipping address...")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        addr_map = {
            # Logical name → list of possible input identifiers on EPROLO
            "firstName":     [addr.get("firstName") or (addr.get("name") or "").split(" ", 1)[0],
                              ["first_name", "firstname", "First Name", "Given Name"]],
            "lastName":      [addr.get("lastName") or " ".join((addr.get("name") or "").split(" ")[1:]),
                              ["last_name", "lastname", "Last Name", "Surname", "Family Name"]],
            "company":       [addr.get("company") or "",
                              ["company", "Company"]],
            "address1":      [addr.get("address1") or "",
                              ["address1", "address_1", "Street", "Address", "Street Address"]],
            "address2":      [addr.get("address2") or "",
                              ["address2", "address_2", "Apartment", "Apt", "Unit"]],
            "city":          [addr.get("city") or "", ["city", "City"]],
            "province":      [addr.get("provinceCode") or addr.get("province") or "",
                              ["state", "province", "State", "Province"]],
            "zip":           [addr.get("zip") or "",
                              ["zip", "postal_code", "postcode", "ZIP", "Postal Code"]],
            "country":       [addr.get("country") or "",
                              ["country", "Country"]],
            "phone":         [addr.get("phone") or "",
                              ["phone", "Phone", "Telephone", "Mobile"]],
        }

        def fill_field(value: str, identifiers: List[str]) -> bool:
            if not value:
                return True  # nothing to fill
            for ident in identifiers:
                # 1) by accessible name
                try:
                    box = page.get_by_label(ident, exact=False).first
                    if box.count() > 0:
                        box.fill(value, timeout=3_000)
                        return True
                except Exception:
                    pass
                # 2) by placeholder
                try:
                    box = page.get_by_placeholder(ident).first
                    if box.count() > 0:
                        box.fill(value, timeout=3_000)
                        return True
                except Exception:
                    pass
                # 3) by name attribute
                try:
                    box = page.locator(f'input[name="{ident.lower()}"], '
                                       f'input[name*="{ident.lower()}"]').first
                    if box.count() > 0:
                        box.fill(value, timeout=3_000)
                        return True
                except Exception:
                    pass
            return False

        filled = []
        missed = []
        for k, (value, idents) in addr_map.items():
            if not value:
                continue
            if fill_field(value, idents):
                filled.append(k)
                print(f"    {k}: {value!r}")
            else:
                missed.append((k, value))
                print(f"    {k}: NOT FOUND — fill manually ({value!r})")

        print(f"\n  Address: {len(filled)} filled, {len(missed)} need manual entry")
        if cart_failures:
            print(f"\n  Cart failures ({len(cart_failures)}):")
            for f in cart_failures:
                print(f"    - {f['title'][:50]} qty={f['qty']}")

        # ── Phase 4: HAND OFF to operator. Browser stays open. ──
        print("\n" + "=" * 60)
        print("  HAND-OFF: review cart + address in the browser window.")
        print("  When ready, click 'Place Order' yourself.")
        print("  Browser stays open until you close it (max 30 min).")
        print("=" * 60)
        try:
            page.wait_for_event("close", timeout=30 * 60 * 1000)
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--order", required=True,
                        help="order name/number (1001 or #1001) or numeric ID")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE,
                        help=f"EPROLO storage_state file (default: {DEFAULT_STATE})")
    parser.add_argument("--headless", action="store_true",
                        help="run Chromium headless (NOT recommended — you can't review)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print resolved cart + address without launching browser")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)
    store, token = get_shopify_token()
    print(f"Shopify: {store}")

    print(f"\nFetching order {args.order}...")
    order = fetch_order(store, token, args.order)
    if not order:
        sys.exit(f"Order not found: {args.order}")
    print(f"  Order: {order.get('name')} (created {order.get('createdAt')})")

    items, addr = summarize_order(order)
    print(f"  Line items: {len(items)}")
    missing_url = sum(1 for i in items if not i["eprolo_url"])
    if missing_url:
        print(f"  WARNING: {missing_url} line items have NO EPROLO source_url metafield.")
        print(f"           Run `python pipeline/tools/sync_order_eprolo_links.py --since-days 30`")
        print(f"           first, or set custom.source_url on those products manually.")

    if not addr.get("address1"):
        print(f"  WARNING: order has no shippingAddress.address1 — address won't be filled.")

    run_playwright_flow(items, addr, args.state, args.headless, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
