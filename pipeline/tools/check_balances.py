#!/usr/bin/env python3
"""check_balances.py — pre-flight balance + auth audit across every external
service the pipeline talks to. Run BEFORE a batch:

    python pipeline/tools/check_balances.py

Reports per service:
  • Auth status (token works / 401 / 403)
  • Balance / quota (where the API exposes it)
  • Soft warning if balance < pessimistic per-product cost × 10

Services covered:
  • Shopify Admin API   — OAuth token + GraphQL throttle budget
  • Anthropic            — 1-token ping (no balance API exists)
  • DataForSEO           — /appendix/user_data → $ balance
  • Higgsfield           — /v1/balance → credits
  • OpenAI (optional)    — /v1/models ping (no public balance endpoint)

Exit code: 0 = all green, 1 = at least one auth failed or balance below
warning threshold. The pipeline script run_pipeline_local.py wraps this
so an unattended cron run aborts early if a key is dead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

# Cost-per-product upper bound — used to warn if balance < N×this.
# These are pessimistic, not averages.
PER_PRODUCT_COST = {
    "dataforseo_usd": 0.10,        # keyword research + KD lookups
    "anthropic_usd": 0.50,         # Strategy(Opus) + Designer(Sonnet)
    "higgsfield_credits": 450,     # 6 videos × ~75cr (Marketing Studio)
}
WARN_PRODUCTS = 10                 # warn if balance < 10× per-product cost


# ─── env loader (no python-dotenv dep) ────────────────────────────
def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # Force-overwrite: bash sessions sometimes pre-set empty strings
        # for known names (ANTHROPIC_API_KEY etc) which would block setdefault.
        os.environ[k.strip()] = v.strip()


# ─── pretty output ────────────────────────────────────────────────
GREEN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"; DIM = "\033[2m"; END = "\033[0m"

def line(service: str, status: str, detail: str = "") -> None:
    icon = {"ok": f"{GREEN}OK{END}  ", "warn": f"{YEL}WARN{END}", "fail": f"{RED}FAIL{END}"}[status]
    print(f"  {icon}  {service:14s}  {detail}")


# ─── per-service checks ───────────────────────────────────────────
def check_shopify() -> bool:
    store = os.environ.get("SHOPIFY_STORE")
    cid = os.environ.get("SHOPIFY_CLIENT_ID")
    csec = os.environ.get("SHOPIFY_CLIENT_SECRET")
    if not (store and cid and csec):
        line("Shopify", "fail", "missing SHOPIFY_STORE / CLIENT_ID / CLIENT_SECRET")
        return False
    try:
        r = requests.post(
            f"https://{store}/admin/oauth/access_token",
            json={"client_id": cid, "client_secret": csec, "grant_type": "client_credentials"},
            timeout=15,
        )
        if r.status_code != 200:
            line("Shopify", "fail", f"OAuth {r.status_code}: {r.text[:120]}")
            return False
        token = r.json()["access_token"]
        # Probe throttle budget via a cheap query
        r2 = requests.post(
            f"https://{store}/admin/api/2024-10/graphql.json",
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            json={"query": "{shop{name}}"}, timeout=15,
        )
        ext = r2.json().get("extensions", {}).get("cost", {}).get("throttleStatus", {})
        avail = ext.get("currentlyAvailable")
        rate = ext.get("restoreRate")
        line("Shopify", "ok", f"token OK · throttle {avail}/{int(ext.get('maximumAvailable', 0))} (restore {rate}/s)")
        return True
    except Exception as e:
        line("Shopify", "fail", f"{type(e).__name__}: {str(e)[:100]}")
        return False


def check_anthropic() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        line("Anthropic", "fail", "missing ANTHROPIC_API_KEY")
        return False
    try:
        # Cheapest possible probe: 1-token Haiku call
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5",
                  "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=15,
        )
        if r.status_code == 200:
            line("Anthropic", "ok", "1-token Haiku probe succeeded · no public balance API (see console.anthropic.com)")
            return True
        if r.status_code == 401:
            line("Anthropic", "fail", "401 — key rejected, rotate ANTHROPIC_API_KEY")
            return False
        if r.status_code == 429:
            line("Anthropic", "warn", "429 — rate-limited; key OK")
            return True
        line("Anthropic", "fail", f"{r.status_code}: {r.text[:120]}")
        return False
    except Exception as e:
        line("Anthropic", "fail", f"{type(e).__name__}: {str(e)[:100]}")
        return False


def check_dataforseo() -> bool:
    login = os.environ.get("DATAFORSEO_LOGIN")
    pw = os.environ.get("DATAFORSEO_PASSWORD")
    if not (login and pw):
        line("DataForSEO", "fail", "missing DATAFORSEO_LOGIN / PASSWORD")
        return False
    try:
        r = requests.get(
            "https://api.dataforseo.com/v3/appendix/user_data",
            auth=(login, pw), timeout=15,
        )
        if r.status_code == 401:
            line("DataForSEO", "fail", "401 — invalid credentials")
            return False
        j = r.json()
        money = j.get("tasks", [{}])[0].get("result", [{}])[0].get("money", {})
        bal = money.get("balance", 0)
        threshold = WARN_PRODUCTS * PER_PRODUCT_COST["dataforseo_usd"]
        status = "ok" if bal >= threshold else "warn"
        line("DataForSEO", status, f"balance ${bal:.2f} (warn if <${threshold:.2f} = {WARN_PRODUCTS} products)")
        return bal >= threshold
    except Exception as e:
        line("DataForSEO", "fail", f"{type(e).__name__}: {str(e)[:100]}")
        return False


def check_higgsfield() -> bool:
    key = os.environ.get("HIGGSFIELD_API_KEY")
    if not key:
        line("Higgsfield", "warn", "no HIGGSFIELD_API_KEY (videos only via MCP chat-flow)")
        return True  # not a hard fail — MCP path doesn't need this
    try:
        r = requests.get(
            "https://platform.higgsfield.ai/v1/balance",
            headers={"Authorization": f"Bearer {key}"}, timeout=15,
        )
        if r.status_code == 401:
            line("Higgsfield", "fail", "401 — rotate HIGGSFIELD_API_KEY")
            return False
        if r.status_code != 200:
            line("Higgsfield", "fail", f"{r.status_code}: {r.text[:120]}")
            return False
        credits = r.json().get("credits", 0)
        threshold = WARN_PRODUCTS * PER_PRODUCT_COST["higgsfield_credits"]
        status = "ok" if credits >= threshold else "warn"
        line("Higgsfield", status, f"{credits} credits (warn if <{threshold} = {WARN_PRODUCTS} products)")
        return credits >= threshold
    except Exception as e:
        line("Higgsfield", "fail", f"{type(e).__name__}: {str(e)[:100]}")
        return False


def check_openai() -> bool:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        line("OpenAI", "warn", "no OPENAI_API_KEY (optional — image gen is currently off)")
        return True
    try:
        r = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"}, timeout=15,
        )
        if r.status_code == 401:
            line("OpenAI", "fail", "401 — rotate OPENAI_API_KEY")
            return False
        if r.status_code != 200:
            line("OpenAI", "fail", f"{r.status_code}: {r.text[:120]}")
            return False
        n = len(r.json().get("data", []))
        line("OpenAI", "ok", f"key OK · {n} models accessible · no public balance endpoint (platform.openai.com/usage)")
        return True
    except Exception as e:
        line("OpenAI", "fail", f"{type(e).__name__}: {str(e)[:100]}")
        return False


def check_eprolo_state() -> bool:
    """Not an API — verify the Playwright storage_state file exists and looks
    fresh (cookies have to be re-captured every few weeks via eprolo_login.py)."""
    sp = os.environ.get("EPROLO_STATE_FILE")
    if not sp:
        line("EPROLO state", "warn", "no EPROLO_STATE_FILE (will hit redirect-to-signup wall on every scrape)")
        return True
    p = Path(sp)
    if not p.exists():
        line("EPROLO state", "fail", f"{sp} not found — run pipeline/tools/eprolo_login.py")
        return False
    age_days = (Path(sp).stat().st_mtime)
    import time
    age = (time.time() - age_days) / 86400
    status = "ok" if age < 14 else "warn"
    line("EPROLO state", status, f"{sp} age {age:.1f}d (warn if >14d, expires unpredictably)")
    return True


def main() -> int:
    load_env()
    print(f"\n{DIM}Pipeline pre-flight balance / auth audit{END}\n")
    results = [
        check_shopify(),
        check_anthropic(),
        check_dataforseo(),
        check_higgsfield(),
        check_openai(),
        check_eprolo_state(),
    ]
    print()
    ok = all(results)
    if ok:
        print(f"  {GREEN}All services ready for batch.{END}")
    else:
        print(f"  {YEL}Some services failed or low — review above.{END}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
