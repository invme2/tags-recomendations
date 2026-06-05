#!/usr/bin/env python3
"""patch_strategy_seo.py — two Designer-prompt upgrades:

A) GROUND-IN-STRATEGY block: forces the Designer (Sonnet) to actually USE the
   expensive Strategy (Opus) brief — map selling_idea -> hero, transformation
   -> story arc, key_objections -> faq, buying_trigger -> cta, etc. Without
   this the Opus output was only loosely referenced (voice/kickers).

B) Senior-SEO upgrade of the meta title + meta description guidance:
   - title doubles as the <title> tag -> keyword in first ~5 words, unique,
     no brand append (storefront adds it).
   - meta description -> keyword+benefit in first ~120 chars (mobile/CTR),
     unique, secondary keyword, no double-quotes.

All anchors are reconstructed with the SAME lit() helper that produced the
existing source literals, guaranteeing an exact match. nbformat path.
After: python pipeline/tools/notebook_smoke.py && pytest pipeline/tests/
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 14


def lit(t: str) -> str:
    """Reproduce a 16-space-indented source string literal ending in \\n."""
    return "                " + json.dumps(t + "\n")


# ── Block A: ground every section in the Strategy brief ──
A_LINES = [
    "GROUND EVERY SECTION IN THE STRATEGY — the STRATEGY JSON in the user message is a senior strategist's brief. USE it; do not treat it as background:",
    "- hero.h1 + hero.lead: express strategy.selling_idea in the product's own words. The H1 is the ONE promise — make it the transformation/outcome, not a spec.",
    "- story chapters: follow strategy.transformation — chapter 1 = the 'before' pain (strategy.pain_point / current_solutions), middle = the product as the turning point, final = the 'after' state.",
    "- features + stats: each should reinforce strategy.differentiator and pre-empt one of strategy.key_objections.",
    "- faq: answer strategy.key_objections head-on (price, longevity, side-effects, comparisons).",
    "- cta: fire on strategy.buying_trigger. The emotional register of ALL copy = strategy.key_emotion; the tone = strategy.voice.",
    "- Never contradict the strategy's positioning or persona. If a section cannot serve the strategy, SKIP it.",
]

# ── Block B1: extra title SEO line (inserted after the keyword line) ──
KEYWORD_LINE = lit("- Include the primary search keyword naturally (helps Google Shopping + on-site search), but a HUMAN must want to click it.")
TITLE_SEO_LINE = lit("- SEO (this string is ALSO the <title> tag): put the PRIMARY KEYWORD in the first ~5 words (front-loaded ranking weight), keep every title UNIQUE across the catalog, and do NOT append the store/brand name — the storefront adds it automatically.")

# ── Block B2: replace meta description with senior-SEO version ──
OLD_MD = lit("META DESCRIPTION (meta.seo_meta.description) — the Google result snippet that wins or loses the click. 140-155 chars: open with the core benefit + primary keyword, add ONE curiosity or proof hook, close with a soft pull ('See why...', 'Made for...'). Do NOT restate the title. No price, no shipping, no exclamation marks.")
NEW_MD = lit("META DESCRIPTION (meta.seo_meta.description) — the Google SERP snippet that wins or loses the click. Senior-SEO rules: 140-155 chars; put the PRIMARY KEYWORD + core benefit in the FIRST ~120 chars (mobile truncates ~120; Google bolds matched query terms = higher CTR); active voice; add one secondary keyword or proof hook; close with a soft pull ('See why...', 'Made for...'); UNIQUE per product; never restate the title verbatim; no price, no shipping, no double-quotes, no exclamation marks.")

COPY_ANCHOR = lit("COPY QUALITY:")


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    src = cell.source

    # op 1: insert Block A before COPY QUALITY
    if src.count(COPY_ANCHOR) != 1:
        print(f"FAIL: COPY QUALITY anchor count={src.count(COPY_ANCHOR)}"); return 1
    block_a = "".join(l + "\n" for l in A_LINES_LITS()) + lit("") + "\n" + COPY_ANCHOR
    src = src.replace(COPY_ANCHOR, block_a)

    # op 2: insert title SEO line after keyword line
    if src.count(KEYWORD_LINE) != 1:
        print(f"FAIL: keyword line count={src.count(KEYWORD_LINE)}"); return 1
    src = src.replace(KEYWORD_LINE, KEYWORD_LINE + "\n" + TITLE_SEO_LINE)

    # op 3: replace meta description
    if src.count(OLD_MD) != 1:
        print(f"FAIL: meta-desc anchor count={src.count(OLD_MD)}"); return 1
    src = src.replace(OLD_MD, NEW_MD)

    cell.source = src
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("OK: Block A (ground-in-strategy, 7 lines) + title SEO line + senior-SEO meta description applied.")
    return 0


def A_LINES_LITS():
    return [lit(t) for t in A_LINES]


if __name__ == "__main__":
    sys.exit(main())
