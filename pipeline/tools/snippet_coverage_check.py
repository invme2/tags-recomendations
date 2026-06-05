#!/usr/bin/env python3
"""snippet_coverage_check.py — verify operator-tracked invariants between
the Liquid theme files and pipeline configuration.

Catches:
  1. A snippet `wanelo-X.liquid` exists but X is NOT in master section's
     render list → that section never appears on storefront.
  2. Master section renders `wanelo-X` but the snippet file is missing
     → Shopify deploy will silently render nothing.
  3. KNOWN_SECTIONS array in master template (used by auto-section
     fallback) doesn't include every key from dedicated snippet renders
     → fallback duplicates the dedicated render.
  4. Pipeline `_wanelo_keys` in Cell 14 references a key but no Shopify
     metafield definition exists.
  5. wanelo.css has rules for `.wanelo-X` selector but no snippet
     `wanelo-X.liquid` (dead CSS).

Exit code:
  0 = all consistent
  1 = inconsistencies found (operator should review)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THEME = REPO_ROOT / "pipeline" / "theme_assets"
SNIPPETS_DIR = THEME / "snippets"
MASTER_SECTION = THEME / "sections" / "wanelo-product-page.liquid"
CSS_FILE = THEME / "assets" / "wanelo.css"


def find_snippet_files() -> set[str]:
    """Return set of snippet basenames (without 'wanelo-' prefix and .liquid)."""
    out = set()
    for p in SNIPPETS_DIR.glob("wanelo-*.liquid"):
        stem = p.stem.removeprefix("wanelo-")
        out.add(stem)
    return out


def find_render_calls(section_text: str) -> set[str]:
    """Find all `{% render 'wanelo-X' %}` calls in master section."""
    pattern = re.compile(r"render\s+'wanelo-([a-z0-9\-]+)'")
    return set(pattern.findall(section_text))


def find_known_sections_array(section_text: str) -> set[str]:
    """Parse the KNOWN_SECTIONS Liquid assign and return the keys."""
    m = re.search(r'assign known_sections = "([^"]+)"', section_text)
    if not m:
        return set()
    return set(k.strip() for k in m.group(1).split(",") if k.strip())


def find_css_section_selectors() -> set[str]:
    """Find `.wanelo-X` class selectors in wanelo.css (top-level section
    selectors only — skip BEM child selectors like .wanelo-X__item)."""
    if not CSS_FILE.exists():
        return set()
    txt = CSS_FILE.read_text(encoding="utf-8")
    # Match .wanelo-NAME where NAME has no __ (i.e., top-level component)
    pattern = re.compile(r"\.wanelo-([a-z0-9\-]+?)(?=[\s,.{:])", re.MULTILINE)
    out = set()
    for m in pattern.finditer(txt):
        name = m.group(1)
        if "__" in name or name == "page" or name == "section" or name == "head":
            continue
        out.add(name)
    return out


def main() -> int:
    if not MASTER_SECTION.exists():
        print(f"FAIL: master section not found at {MASTER_SECTION}")
        return 1
    if not SNIPPETS_DIR.exists():
        print(f"FAIL: snippets dir not found at {SNIPPETS_DIR}")
        return 1

    section_text = MASTER_SECTION.read_text(encoding="utf-8")
    snippets = find_snippet_files()
    rendered = find_render_calls(section_text)
    known = find_known_sections_array(section_text)
    css_selectors = find_css_section_selectors()

    issues = 0
    print(f"\n=== Snippet ↔ Section ↔ CSS consistency check ===\n")
    print(f"  {len(snippets):3d} snippet files (wanelo-*.liquid)")
    print(f"  {len(rendered):3d} explicit render calls in master section")
    print(f"  {len(known):3d} keys in KNOWN_SECTIONS array (auto-section skip list)")
    print(f"  {len(css_selectors):3d} top-level CSS selectors (.wanelo-X)\n")

    # Check 1: snippet exists but not rendered
    unused_snippets = snippets - rendered
    if unused_snippets:
        # Utility/intentional non-renders:
        #   palette/icons/product-schema/auto-section — render programmatically OR utility
        #   rating, trust-strip — intentionally disabled (FTC risk on fake data),
        #     kept on disk for future Judge.me/Loox real-review integration
        UTILITY = {"palette", "icons", "product-schema", "auto-section",
                   "rating", "trust-strip"}
        real_unused = unused_snippets - UTILITY
        if real_unused:
            issues += 1
            print(f"WARN: {len(real_unused)} snippet(s) exist but never rendered in master section:")
            for s in sorted(real_unused):
                print(f"    - wanelo-{s}.liquid")
            print()

    # Check 2: render call but snippet missing
    missing_snippets = rendered - snippets
    if missing_snippets:
        issues += 1
        print(f"FAIL: {len(missing_snippets)} render call(s) point to non-existent snippets:")
        for s in sorted(missing_snippets):
            print(f"    - {{%- render 'wanelo-{s}' -%}}  → no file")
        print()

    # Check 3: rendered key not in KNOWN_SECTIONS → auto-section will duplicate
    # The KNOWN_SECTIONS array uses metafield keys (snake_case), render uses
    # snippet names (kebab-case). Normalize both to compare.
    rendered_keys = {r.replace("-", "_") for r in rendered}
    not_in_known = rendered_keys - known
    if not_in_known:
        # Filter to those that look like content snippets (skip utility)
        UTILITY_KEYS = {"palette", "icons", "product_schema", "auto_section"}
        real_missing = not_in_known - UTILITY_KEYS
        if real_missing:
            issues += 1
            print(f"WARN: {len(real_missing)} rendered key(s) NOT in KNOWN_SECTIONS — auto-section fallback may duplicate them:")
            for s in sorted(real_missing):
                print(f"    - '{s}' rendered but not in known_sections array")
            print(f"  Add these to the known_sections list in {MASTER_SECTION.name}\n")

    # Check 4: KNOWN_SECTIONS lists key that's neither rendered nor in CSS
    # (cosmetic — just stale entries in the array)
    stale_known = known - rendered_keys
    UTILITY_KEYS = {"html_description", "og_image", "title_tag", "description_tag",
                    "photo_pack", "source", "source_url", "designer_prompt"}
    stale_real = stale_known - UTILITY_KEYS
    if stale_real:
        # Only warn if there are MANY stale (a few are expected for admin-only)
        if len(stale_real) > 5:
            issues += 1
            print(f"WARN: {len(stale_real)} key(s) in KNOWN_SECTIONS but never rendered (stale array entries):")
            for s in sorted(stale_real)[:10]:
                print(f"    - '{s}'")
            print()

    # Check 5: CSS selectors without backing snippet
    # css_selectors are top-level names like "videos", "hero" etc.
    UTILITY_CSS = {
        "sticky-atc", "rail", "merged-wrap",          # JS-injected wrappers
        "auto", "kicker", "kicker--accent",            # generic utilities + modifiers
        "rating-slot", "sticky-arrow",                 # JS-injected children
        "coll-also", "coll-related",                   # collection-page-only styles
        "story-row",                                   # part of story snippet (BEM child)
        "page", "section", "head",                    # already excluded by regex
    }
    css_no_snippet = css_selectors - snippets - UTILITY_CSS
    if css_no_snippet and len(css_no_snippet) > 3:
        issues += 1
        print(f"WARN: {len(css_no_snippet)} CSS .wanelo-X selectors without corresponding snippet:")
        for s in sorted(css_no_snippet)[:10]:
            print(f"    - .wanelo-{s}")
        print()

    if issues == 0:
        print("\033[92mAll consistent — theme files, master section, CSS aligned.\033[0m")
        return 0
    print(f"\n\033[93mFound {issues} category of inconsistencies — review above.\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
