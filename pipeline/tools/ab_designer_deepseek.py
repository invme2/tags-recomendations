#!/usr/bin/env python3
"""ab_designer_deepseek.py — A/B the Designer step: Sonnet 4.6 vs DeepSeek V4 Pro.

Standalone — does NOT touch the production notebook. It:
  1. Extracts the REAL Designer system prompt from Shopify_Pipeline.ipynb.
  2. Pulls N real products (with vision + strategy) from a run DB and rebuilds a
     faithful Designer user prompt (product context + strategy + instructions).
  3. Sends the SAME system+user to Sonnet 4.6 (Anthropic) and DeepSeek V4 Pro
     (OpenAI-compatible endpoint).
  4. Compares: valid JSON?, top-level section count, output tokens, $ cost,
     latency, and a hero/copy sample — so we can judge quality before any swap.

Pricing (Jun 2026):
  Sonnet 4.6:     $3.00 in / $15.00 out  per Mtok
  DeepSeek V4 Pro:$0.435 in / $0.87  out per Mtok

Requires in .env: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY.
  DEEPSEEK_MODEL  default 'deepseek-chat' (set to the exact V4-Pro id if different)

USAGE:
  python pipeline/tools/ab_designer_deepseek.py \
      --db "runs/health-care-chunk1-2026-05-28/pipeline.db" --n 3
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sqlite3
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
NB = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
load_dotenv(ROOT / ".env", override=True)

SONNET_IN, SONNET_OUT = 3.0, 15.0           # $/Mtok
DEEPSEEK_IN, DEEPSEEK_OUT = 0.435, 0.87     # $/Mtok


def _string_literals_in(node) -> list[str]:
    """Collect all str constants under an AST node (handles implicit/`+` concat)."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def extract_designer_system() -> str:
    """Rebuild the Designer system prompt text from the notebook (verbatim)."""
    nb = json.loads(NB.read_text(encoding="utf-8"))
    cell14 = "".join(nb["cells"][14]["source"])
    tree = ast.parse(cell14)
    sys_parts, html_rules = None, ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            tgt = node.targets[0]
            name = getattr(tgt, "id", None)
            if name == "_designer_system":
                sys_parts = "".join(_string_literals_in(node.value))
            elif name == "HTML_CLEAN_OUTPUT_RULES":
                html_rules = "".join(_string_literals_in(node.value))
    if sys_parts is None:
        raise SystemExit("could not extract _designer_system from notebook")
    return sys_parts + html_rules


def build_user_prompt(scrape: dict, stage1: dict, strategy: dict) -> str:
    """Faithful-enough rebuild of the Designer user content."""
    title = (scrape.get("title") or "")[:120]
    desc = (scrape.get("description") or "")[:800]
    vision_ctx = json.dumps({k: stage1.get(k) for k in (
        "category", "product_type", "product_summary", "packaging_text",
        "sensory", "physical", "conversion") if k in stage1}, ensure_ascii=False, indent=2)
    ctx = (f"Generate a product description page for this product:\n\n"
           f"PRODUCT: {title}\nCATEGORY: {stage1.get('category','')}\n"
           f"TYPE: {stage1.get('product_type','simple')}\n"
           f"SUMMARY: {stage1.get('product_summary','')}\n"
           f"DESCRIPTION: {desc}\n\nVISION ANALYSIS:\n{vision_ctx}\n")
    instr = (
        "\n\n=== MARKETING STRATEGY (frames ALL copy) ===\n"
        + json.dumps(strategy, ensure_ascii=False, indent=2)
        + "\n\nINSTRUCTIONS:\n"
        "- hero.h1 = strategy.selling_idea. hero.lead echoes the transformation.\n"
        "- story.chapters: each chapter is one beat from strategy.narrative_arc.\n"
        "- features.items: 3 features that prove strategy.differentiator.\n"
        "- stats.items: 4 measurable proof points addressing strategy.key_objections.\n"
        "- faq.items: 4-7 questions addressing strategy.key_objections.\n"
        "- Voice in ALL copy = strategy.voice.\n")
    return ctx + instr


def call_sonnet(system: str, user: str) -> dict:
    import anthropic
    cli = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
    t = time.time()
    r = cli.messages.create(
        model="claude-sonnet-4-6", max_tokens=16000, timeout=600.0,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": user}])
    txt = r.content[0].text
    return {"text": txt, "in": r.usage.input_tokens, "out": r.usage.output_tokens,
            "secs": time.time() - t,
            "cost": r.usage.input_tokens * SONNET_IN / 1e6 + r.usage.output_tokens * SONNET_OUT / 1e6}


def call_deepseek(system: str, user: str) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY missing in .env — add it to run the A/B")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    t = time.time()
    r = requests.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}],
                            "max_tokens": 8192, "temperature": 0.7,
                            "response_format": {"type": "json_object"}},
                      timeout=600)
    j = r.json()
    if "choices" not in j:
        raise SystemExit(f"DeepSeek error: {json.dumps(j)[:300]}")
    txt = j["choices"][0]["message"]["content"]
    u = j.get("usage", {})
    pin, pout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    return {"text": txt, "in": pin, "out": pout, "secs": time.time() - t,
            "cost": pin * DEEPSEEK_IN / 1e6 + pout * DEEPSEEK_OUT / 1e6,
            "model": model}


def analyse(label: str, res: dict) -> dict:
    raw = res["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    valid, keys, hero = False, 0, ""
    try:
        obj = json.loads(raw)
        valid = True
        keys = len(obj)
        hero = ((obj.get("hero") or {}).get("h1") or "")[:80]
    except Exception as e:
        hero = f"[JSON parse FAIL: {str(e)[:60]}]"
    print(f"  {label:<14} valid_json={valid}  sections={keys:>2}  "
          f"out_tok={res['out']:>5}  ${res['cost']:.4f}  {res['secs']:.0f}s")
    print(f"  {'':14} hero.h1: {hero}")
    return {"valid": valid, "keys": keys, "cost": res["cost"], "out": res["out"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="runs/health-care-chunk1-2026-05-28/pipeline.db")
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args()

    system = extract_designer_system()
    print(f"Designer system prompt: {len(system)} chars (~{len(system)//4} tok)\n")

    con = sqlite3.connect(ROOT / args.db)
    rows = con.execute(
        "SELECT name, scrape_json, stage1_json, strategy_json FROM products "
        "WHERE stage1_json IS NOT NULL AND strategy_json IS NOT NULL "
        "AND length(strategy_json) > 50 ORDER BY id LIMIT ?", (args.n,)).fetchall()
    con.close()
    if not rows:
        raise SystemExit("no products with vision+strategy found in DB")

    agg = {"sonnet": [], "deepseek": []}
    for name, sj, s1, st in rows:
        scrape = json.loads(sj) if sj else {}
        stage1 = json.loads(s1) if s1 else {}
        strategy = json.loads(st) if st else {}
        user = build_user_prompt(scrape, stage1, strategy)
        print(f"━━━ {name[:60]} ━━━  (user ~{len(user)//4} tok)")
        try:
            agg["sonnet"].append(analyse("Sonnet 4.6", call_sonnet(system, user)))
        except Exception as e:
            print("  Sonnet FAIL:", str(e)[:120])
        try:
            agg["deepseek"].append(analyse("DeepSeek V4Pro", call_deepseek(system, user)))
        except Exception as e:
            print("  DeepSeek FAIL:", str(e)[:120])
        print()

    print("════════ SUMMARY ════════")
    for k, rs in agg.items():
        if not rs:
            continue
        n = len(rs)
        valid = sum(r["valid"] for r in rs)
        avg_cost = sum(r["cost"] for r in rs) / n
        avg_keys = sum(r["keys"] for r in rs) / n
        print(f"  {k:<10} valid {valid}/{n} | avg sections {avg_keys:.1f} | avg ${avg_cost:.4f}/product")
    if agg["sonnet"] and agg["deepseek"]:
        cs = sum(r["cost"] for r in agg["sonnet"]) / len(agg["sonnet"])
        cd = sum(r["cost"] for r in agg["deepseek"]) / len(agg["deepseek"])
        if cd:
            print(f"\n  DeepSeek is {cs/cd:.1f}x cheaper on Designer "
                  f"(${cs:.4f} -> ${cd:.4f}/product). Decide on JSON validity + copy quality above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
