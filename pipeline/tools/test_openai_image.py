#!/usr/bin/env python3
"""Diagnostic script for gpt-image-2 access.

Runs four checks in order, stopping at the first hard failure:

  1. OPENAI_API_KEY present
  2. API key works (list models — cheapest auth check)
  3. gpt-image-2 visible in the models list (org verified)
  4. images.generate (no source) — pure text prompt, low quality
  5. images.edit (with source) — uses the same source flow as the pipeline

Run from a shell where OPENAI_API_KEY is exported, or paste the key inline.
Generated images are saved to /tmp/openai_test_*.png so you can eyeball them.

Cost: ~$0.012 (one low-quality 1024x1024 generation + one edit).
"""
from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"{RED}✗{RESET} {msg}")
    if hint:
        print(f"  {YELLOW}→ {hint}{RESET}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"{DIM}  {msg}{RESET}")


# ============================================================
# Check 1 — API key present
# ============================================================
print("\n[1/5] Checking OPENAI_API_KEY env var…")
api_key = os.environ.get("OPENAI_API_KEY", "").strip()
if not api_key:
    fail(
        "OPENAI_API_KEY not set",
        "In Colab → Secrets (🔑) → Add new secret → Name=OPENAI_API_KEY → Value=sk-…\n  "
        "Locally → export OPENAI_API_KEY=sk-…",
    )
if not api_key.startswith("sk-"):
    fail(
        f"OPENAI_API_KEY doesn't start with 'sk-' (got: {api_key[:8]}…)",
        "Get a fresh key at https://platform.openai.com/api-keys",
    )
ok(f"OPENAI_API_KEY present ({len(api_key)} chars, prefix={api_key[:7]}…)")


# ============================================================
# Check 2 — SDK installed + key works
# ============================================================
print("\n[2/5] Verifying SDK + auth…")
try:
    from openai import OpenAI
except ImportError:
    fail("openai SDK not installed", "pip install openai")

client = OpenAI(api_key=api_key)
try:
    models_iter = client.models.list()
    model_ids = sorted({m.id for m in models_iter})
except Exception as e:
    msg = str(e)[:200]
    if "401" in msg or "invalid_api_key" in msg.lower():
        fail("API key rejected (401)", "Key revoked/typo — make a new one at platform.openai.com/api-keys")
    if "429" in msg:
        fail("Rate-limited (429)", "Wait a minute or check billing limits at platform.openai.com/settings/organization/limits")
    fail(f"models.list failed: {msg}")
ok(f"Auth OK ({len(model_ids)} models accessible)")


# ============================================================
# Check 3 — gpt-image-2 access (org verification)
# ============================================================
print("\n[3/5] Checking gpt-image-2 visibility…")
image_models = [m for m in model_ids if "image" in m.lower()]
info(f"Image-capable models on this account: {image_models or '(none)'}")
target = "gpt-image-2"
if target not in model_ids:
    # Acceptable fallbacks if gpt-image-2 hasn't propagated yet
    fallbacks = [m for m in image_models if m.startswith("gpt-image-")]
    if fallbacks:
        target = fallbacks[0]
        print(f"{YELLOW}⚠{RESET}  gpt-image-2 not visible. Will test with {target} instead.")
        info("If you specifically want gpt-image-2: complete API Org Verification at")
        info("https://platform.openai.com/settings/organization/general")
        info("(can take ~1 hour to propagate after approval)")
    else:
        fail(
            "No gpt-image-* models accessible to this org",
            "Complete API Organization Verification:\n  "
            "https://help.openai.com/en/articles/10910291-api-organization-verification",
        )
else:
    ok(f"{target} visible to this org")


# ============================================================
# Check 4 — images.generate (text-only prompt)
# ============================================================
print(f"\n[4/5] Generating sample image with {target} (low quality)…")
out_gen = Path("/tmp/openai_test_generate.png")
t0 = time.time()
try:
    result = client.images.generate(
        model=target,
        prompt="A small ceramic coffee mug on a wooden table, soft daylight, e-commerce product photo, clean white background.",
        size="1024x1024",
        quality="low",
        n=1,
    )
except Exception as e:
    msg = str(e)
    if "must be verified" in msg.lower() or "verified to use" in msg.lower():
        fail(
            "Org not verified for image generation",
            "Complete API Org Verification (~5 min KYC):\n  "
            "https://platform.openai.com/settings/organization/general",
        )
    if "moderation" in msg.lower() or "content policy" in msg.lower():
        fail("Prompt blocked by content moderation (unexpected for this neutral prompt)")
    if "billing" in msg.lower() or "insufficient" in msg.lower() or "quota" in msg.lower():
        fail(
            f"Billing issue: {msg[:200]}",
            "Add credit at https://platform.openai.com/settings/organization/billing/overview",
        )
    fail(f"images.generate failed: {msg[:300]}")

elapsed = time.time() - t0
b64 = result.data[0].b64_json
img_bytes = base64.b64decode(b64)
out_gen.write_bytes(img_bytes)
ok(f"images.generate OK in {elapsed:.1f}s — {len(img_bytes)/1024:.0f} KB → {out_gen}")


# ============================================================
# Check 5 — images.edit (matches pipeline flow)
# ============================================================
print(f"\n[5/5] Edit-mode test (sends prior result as source)…")
out_edit = Path("/tmp/openai_test_edit.png")
t0 = time.time()
import io
src = io.BytesIO(img_bytes)
src.name = "source.png"
try:
    result2 = client.images.edit(
        model=target,
        image=src,
        prompt="Same mug but on a marble surface with a sprig of mint next to it.",
        size="1024x1024",
        quality="low",
        n=1,
    )
except Exception as e:
    msg = str(e)
    if "must be verified" in msg.lower():
        fail("Edit endpoint also needs org verification (same fix as Check 4)")
    if "input_fidelity" in msg.lower():
        fail(
            "input_fidelity rejected — this means you're hitting gpt-image-2 which forbids it",
            "Pipeline already does NOT pass input_fidelity, so this should not happen. Report bug.",
        )
    fail(f"images.edit failed: {msg[:300]}")

elapsed = time.time() - t0
b64_2 = result2.data[0].b64_json
img_bytes_2 = base64.b64decode(b64_2)
out_edit.write_bytes(img_bytes_2)
ok(f"images.edit OK in {elapsed:.1f}s — {len(img_bytes_2)/1024:.0f} KB → {out_edit}")


# ============================================================
# Summary
# ============================================================
print(f"\n{GREEN}━━━ ALL CHECKS PASSED ━━━{RESET}")
print(f"Model: {target}")
print(f"Generated:  {out_gen}")
print(f"Edited:     {out_edit}")
print()
print("Pipeline should work — set USE_IMAGE_GEN = True in Cell 1 and rerun.")
print("If pipeline still skips image gen with 'OPENAI_API_KEY missing/invalid',")
print("the key isn't being passed into Colab — check the Secrets toggle 'Notebook access'.")
