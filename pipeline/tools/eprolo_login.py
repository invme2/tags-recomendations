"""
EPROLO login flow — capture Playwright storage_state.json for use by the
Shopify pipeline's get_shared_browser_ctx().

USAGE:
    python pipeline/tools/eprolo_login.py

How it works:
  1. Opens a visible Chromium window pointed at https://www.eprolo.com.
  2. You log in to EPROLO in that window (manual — your credentials).
  3. While the browser is open, this script saves storage_state every
     few seconds, so progress is preserved even if you kill it.
  4. When you CLOSE the browser window, the script saves a final
     snapshot and exits.

Result: `pipeline/.eprolo_state.json` (gitignored) containing cookies +
localStorage. Verify with:
    python pipeline/tools/eprolo_verify_scrape.py <eprolo-product-url>

The pipeline notebook will be patched separately to load this state via
get_shared_browser_ctx(storage_state=...).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = REPO_ROOT / "pipeline" / ".eprolo_state.json"
EPROLO_URL = "https://www.eprolo.com/"
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 30 * 60  # 30-minute safety ceiling


def _safe_save(ctx, path: Path) -> int | None:
    """Save storage_state. Returns the number of eprolo-domain cookies
    captured, or None on failure."""
    try:
        ctx.storage_state(path=str(path))
        return sum(
            1 for c in ctx.cookies() if "eprolo" in c.get("domain", "")
        )
    except Exception as e:
        print(f"  (save skipped: {e})", flush=True)
        return None


def main() -> int:
    print(f"Saving session to: {STATE_FILE}", flush=True)
    print("Launching headed Chromium...", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        try:
            page.goto(EPROLO_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"Initial navigation failed (you can still log in): {e}", flush=True)

        print()
        print("=" * 60, flush=True)
        print("ACTION REQUIRED:", flush=True)
        print(f"  1. Log in to EPROLO in the browser window.", flush=True)
        print(f"  2. CLOSE the browser window when done.", flush=True)
        print("=" * 60, flush=True)
        print(flush=True)

        deadline = time.time() + MAX_WAIT_SECONDS
        last_eprolo_cookies = 0

        # Hook: when context closes, we lose it — capture state on
        # browser disconnect using polling instead.
        while time.time() < deadline:
            # Browser still alive?
            if not browser.is_connected():
                print("Browser was closed by user.", flush=True)
                break

            # Periodic save (best-effort)
            n = _safe_save(ctx, STATE_FILE)
            if n is not None and n != last_eprolo_cookies:
                print(
                    f"  [{time.strftime('%H:%M:%S')}] saved — "
                    f"eprolo cookies: {n}",
                    flush=True,
                )
                last_eprolo_cookies = n

            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            print(
                f"Hit {MAX_WAIT_SECONDS // 60}-minute safety ceiling — "
                "saving final state and exiting.",
                flush=True,
            )

        # Final save attempt (may already be impossible if browser fully
        # gone, but try)
        _safe_save(ctx, STATE_FILE)

        try:
            browser.close()
        except Exception:
            pass

    # Report final state
    if STATE_FILE.exists():
        import json
        with STATE_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        all_cookies = data.get("cookies", [])
        eprolo_cookies = [c for c in all_cookies if "eprolo" in c.get("domain", "")]
        print(flush=True)
        print(f"Final state: {STATE_FILE}", flush=True)
        print(f"  total cookies: {len(all_cookies)}", flush=True)
        print(f"  eprolo cookies: {len(eprolo_cookies)}", flush=True)
        if eprolo_cookies:
            names = sorted(c["name"] for c in eprolo_cookies)
            print(f"  cookie names: {names[:12]}{'...' if len(names) > 12 else ''}", flush=True)
            print(flush=True)
            print("Next step:", flush=True)
            print("  python pipeline/tools/eprolo_verify_scrape.py <product-url>", flush=True)
            return 0
        print("WARNING: zero eprolo.com cookies — login likely did not complete.", flush=True)
        return 1
    print("ERROR: state file was not written.", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
