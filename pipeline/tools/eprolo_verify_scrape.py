"""
Quick verification that pipeline/.eprolo_state.json gives us a logged-in
EPROLO session. Loads the state, opens a product URL, prints the <h1>
title + final URL after redirects.

USAGE:
    python pipeline/tools/eprolo_verify_scrape.py <eprolo-product-url>

A "real" success looks like:
    title: Some Real Product Name 2-Pack Whatever
    final URL: https://www.eprolo.com/<original-handle>...

A failure (Bug A repro) looks like:
    title: 'Sign Up -EPROLO' or 'EPROLO - All-in-One ...'
    final URL: https://www.eprolo.com/sign-up  (redirect)
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = REPO_ROOT / "pipeline" / ".eprolo_state.json"

MARKETING_TITLE_SIGNATURES = (
    "EPROLO -",
    "Sign Up",
    "Sign In",
    "Log In",
    "Login",
    "Dropshipping Supply",
    "All-in-One Dropshipping",
)


def main(url: str) -> int:
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found. Run eprolo_login.py first.")
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=str(STATE_FILE),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60_000)
        except Exception as e:
            print(f"goto failed: {e}")
            browser.close()
            return 3

        final_url = page.url
        h1_elem = page.query_selector("h1")
        h1_text = h1_elem.inner_text() if h1_elem else ""
        page_title = page.title()

        print(f"requested URL: {url}")
        print(f"final URL:     {final_url}")
        print(f"<h1>:          {h1_text[:160]}")
        print(f"<title>:       {page_title[:160]}")

        looks_like_marketing = any(
            sig.lower() in (h1_text + page_title).lower()
            for sig in MARKETING_TITLE_SIGNATURES
        )
        redirected = "/sign" in final_url.lower() or "/login" in final_url.lower()

        print()
        if looks_like_marketing or redirected:
            print("RESULT: Bug A still active — looks like marketing/signup page.")
            print("        Re-run eprolo_login.py and confirm you log in fully.")
            browser.close()
            return 1
        print("RESULT: Real product page reached — Bug A unblocked for this URL.")
        browser.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
