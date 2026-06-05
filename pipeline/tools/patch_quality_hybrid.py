#!/usr/bin/env python3
"""patch_quality_hybrid.py — #1 + #2: max quality on the customer-facing strings
without raising the chain cost.

#2  Strategy (Opus 4.8, already running) now ALSO emits seo_title +
    seo_description + hero hook (senior-SEO rules). Assembly prefers these
    premium versions over DeepSeek's; hero merge keeps DeepSeek's image_url.
    Marginal cost ~+$0.005/product (a few hundred extra Opus output tokens).
#1  Free: photo-brief nudge for DeepSeek (art-director quality + light bg).

Net: the title / meta description / hero (highest-leverage, customer-facing)
run on frontier Opus; the bulk structured content + photos stay on cheap
DeepSeek. Total ~$0.05-0.055/product (was $0.16). nbformat path.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

# ── EDIT 1 (cell 10): add 3 fields to the Strategy output schema ──
SCHEMA_OLD = '{\n  "positioning": "Who buys this'
SCHEMA_NEW = (
    '{\n'
    '  "seo_title": "Storefront product title + <title> tag, 50-60 chars. See TITLE/META/HERO RULES below.",\n'
    '  "seo_description": "Google SERP meta description, 140-155 chars. See RULES below.",\n'
    '  "hero": {"kicker": "2-3 word product-specific tease", "h1": "the ONE promise = selling_idea, with <em>...</em> on 1-2 emotional words", "lead": "1-2 sentences echoing the transformation (before to after)"},\n'
    '  "positioning": "Who buys this'
)

# ── EDIT 2 (cell 10): senior-SEO rules for the new fields, before CRITICAL RULES ──
RULES_OLD = 'CRITICAL RULES:\n- Be HONEST.'
RULES_NEW = (
    "TITLE / META / HERO RULES (these become the customer-facing storefront title, the\n"
    "Google snippet, and the page hero — craft them like a senior marketplace SEO):\n"
    "- seo_title: <recognizable product-type noun> + <strongest benefit>. Primary keyword\n"
    "  in the first ~5 words (it is ALSO the <title> tag). Title Case, 50-60 chars, UNIQUE.\n"
    "  FORBIDDEN: ALL-CAPS, '2024/2025 New', 'Hot Sale', emoji, spec dumps, keyword stuffing.\n"
    "  Do NOT append the store/brand name (the storefront adds it).\n"
    "- seo_description: primary keyword + core benefit in the FIRST ~120 chars (mobile +\n"
    "  Google bolds query matches = higher CTR); active voice; one proof/curiosity hook;\n"
    "  soft pull ('See why...'); UNIQUE; no price, no shipping, no exclamation marks.\n"
    "- hero.h1: express selling_idea as ONE promise (the transformation/outcome, not a spec),\n"
    "  with <em>...</em> on 1-2 emotional words. hero.lead: 1-2 sentences, before to after.\n\n"
    "CRITICAL RULES:\n- Be HONEST."
)

# ── EDIT 3 (cell 4): #1 free photo-brief nudge for DeepSeek ──
NUDGE_OLD = (
    '    "product supports them. Do NOT be conservative — a richer page converts better.\\n"\n'
    ")"
)
NUDGE_NEW = (
    '    "product supports them. Do NOT be conservative — a richer page converts better.\\n"\n'
    '    "- PHOTO BRIEFS are high-stakes: write concept + edit_instructions like an e-commerce "\n'
    '    "art director; every brief names a LIGHT background explicitly; the 5 carousel slots "\n'
    '    "must each answer one buyer question.\\n"\n'
    ")"
)

# ── EDIT 4 (cell 14): assembly prefers premium Strategy strings ──
OVR_OLD = "            seo_m = meta.get('seo_meta', {})"
OVR_NEW = (
    "            seo_m = meta.get('seo_meta', {})\n"
    "            # ── #2 quality: prefer premium Strategy (Opus 4.8) for the highest-leverage\n"
    "            # customer-facing strings (title / meta description / hero); DeepSeek fills the rest. ──\n"
    "            if _strategy.get('seo_title'):       seo_m['title'] = _strategy['seo_title']\n"
    "            if _strategy.get('seo_description'): seo_m['description'] = _strategy['seo_description']\n"
    "            _strat_hero = _strategy.get('hero') or {}\n"
    "            if _strat_hero and isinstance(sections.get('hero'), dict):\n"
    "                for _hk in ('kicker', 'h1', 'lead'):\n"
    "                    if _strat_hero.get(_hk):\n"
    "                        sections['hero'][_hk] = _strat_hero[_hk]"
)

EDITS = [
    (10, SCHEMA_OLD, SCHEMA_NEW),
    (10, RULES_OLD, RULES_NEW),
    (4, NUDGE_OLD, NUDGE_NEW),
    (14, OVR_OLD, OVR_NEW),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    for idx, (ci, old, new) in enumerate(EDITS):
        cell = nb.cells[ci]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx} (cell {ci}): expected 1 match, found {n}")
            print(f"  old starts: {old[:60]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx} (cell {ci})")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("Hybrid quality (#1 + #2) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
