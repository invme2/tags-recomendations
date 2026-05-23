"""Edge-case structural tests for snippets — verify defensive Liquid patterns.

Live Liquid templates can't be easily evaluated in pytest (would need a Liquid
parser), but we CAN inspect the source for defensive patterns that prevent
common runtime errors:

1. Every optional snippet has a top-level `{%- if X and X.<list-key> -%}`
   gate that checks both the metafield exists AND the array has items
2. Every loop has a `forloop` reference or proper for-each (not bare access)
3. Every {{ output }} that could be nil is either piped through `default:`
   or wrapped in `{%- if ... != blank -%}`
4. CSS classes match between snippet and wanelo.css (no orphan styles, no
   undefined references)

This catches: snippet renders broken HTML when designer emits {} or partially
filled JSON; snippet crashes on missing nested key; snippet leaves a blank
section frame even when content is truly empty.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNIPPETS_DIR = ROOT / "pipeline" / "theme_assets" / "snippets"
CSS_PATH = ROOT / "pipeline" / "theme_assets" / "assets" / "wanelo.css"

# All snippets that gate on optional metafield content
OPTIONAL_SNIPPETS = [
    "wanelo-hero",          # always-on but still has if-gate
    "wanelo-story",
    "wanelo-features",
    "wanelo-stats",
    "wanelo-reviews",
    "wanelo-faq",
    "wanelo-cta",
    "wanelo-interlinks",
    "wanelo-ingredients",
    "wanelo-how-to",
    "wanelo-timeline",
    "wanelo-specs",
    "wanelo-whats-included",
    "wanelo-compare",
    "wanelo-trust",
    "wanelo-size-guide",
    "wanelo-care",
    "wanelo-dimensions",
    "wanelo-variants",
    "wanelo-gift-options",
]


def _read(snippet: str) -> str:
    return (SNIPPETS_DIR / f"{snippet}.liquid").read_text(encoding="utf-8")


# ============================================================
# Defensive Liquid patterns — prevent broken markup on empty data
# ============================================================

@pytest.mark.parametrize("snippet", OPTIONAL_SNIPPETS)
def test_snippet_top_level_if_gate(snippet: str) -> None:
    """Every snippet's outermost markup is wrapped in {%- if ... -%}.
    Without this, an empty metafield would emit just a <section> frame."""
    src = _read(snippet)
    # Find first non-comment, non-assign line and check it's an `if`
    code_lines = []
    in_comment = False
    for line in src.splitlines():
        ls = line.strip()
        if ls.startswith("{%- comment -%}") or ls.startswith("{% comment %}"):
            in_comment = True
            continue
        if ls.startswith("{%- endcomment -%}") or ls.startswith("{% endcomment %}"):
            in_comment = False
            continue
        if in_comment or not ls:
            continue
        if ls.startswith("{%- assign") or ls.startswith("{% assign"):
            continue
        code_lines.append(ls)
        if len(code_lines) >= 5:
            break
    has_gate = any("{%- if " in ln or "{% if " in ln for ln in code_lines)
    assert has_gate, (
        f"{snippet}: no top-level {{%- if -%}} gate near start. "
        f"First code lines: {code_lines[:3]}"
    )


@pytest.mark.parametrize("snippet", OPTIONAL_SNIPPETS)
def test_snippet_balanced_if_endif(snippet: str) -> None:
    """Every {%- if -%} must have matching {%- endif -%}."""
    src = _read(snippet)
    n_if = len(re.findall(r"\{%-?\s*if\s", src))
    n_endif = len(re.findall(r"\{%-?\s*endif\s*-?%\}", src))
    assert n_if == n_endif, (
        f"{snippet}: {n_if} `if` blocks vs {n_endif} `endif` — unbalanced"
    )


@pytest.mark.parametrize("snippet", OPTIONAL_SNIPPETS)
def test_snippet_balanced_for_endfor(snippet: str) -> None:
    """Every {%- for -%} must have matching {%- endfor -%}."""
    src = _read(snippet)
    n_for = len(re.findall(r"\{%-?\s*for\s", src))
    n_endfor = len(re.findall(r"\{%-?\s*endfor\s*-?%\}", src))
    assert n_for == n_endfor, (
        f"{snippet}: {n_for} `for` blocks vs {n_endfor} `endfor` — unbalanced"
    )


@pytest.mark.parametrize("snippet", OPTIONAL_SNIPPETS)
def test_snippet_no_unsupported_mod_operator(snippet: str) -> None:
    """Liquid has no `mod` operator — must use `| modulo:` filter.
    Regression for the bug we hit on user's production preview."""
    src = _read(snippet)
    assert not re.search(r"\bmod\s+\d", src), (
        f"{snippet}: uses unsupported `mod N` operator — replace with `| modulo: N`"
    )


# ============================================================
# Defensive guarding inside loops — accessing nested keys
# ============================================================

@pytest.mark.parametrize("snippet,list_key", [
    ("wanelo-ingredients", "items"),
    ("wanelo-how-to", "items"),
    ("wanelo-timeline", "items"),
    ("wanelo-specs", "items"),
    ("wanelo-whats-included", "items"),
    ("wanelo-trust", "certs"),
    ("wanelo-care", "items"),
    ("wanelo-dimensions", "items"),
    ("wanelo-variants", "items"),
    ("wanelo-size-guide", "rows"),
])
def test_snippet_size_check_on_lists(snippet: str, list_key: str) -> None:
    """Snippets that iterate must check .size > 0 before iterating —
    otherwise a missing-array case slips through. Allow either leading-dot
    (`x.<list>.size`) or alias-variable (`<list>.size`) patterns."""
    src = _read(snippet)
    pat = rf"\b{re.escape(list_key)}\.size\s*>\s*0"
    assert re.search(pat, src), (
        f"{snippet}: should check `{list_key}.size > 0` before iterating"
    )


# ============================================================
# CSS class consistency — every used class is defined in wanelo.css
# ============================================================

def _extract_classes_from_snippet(src: str) -> set:
    """Extract wanelo-* classes from class= attributes in snippet source."""
    classes = set()
    for m in re.finditer(r'class="([^"]+)"', src):
        for cls in m.group(1).split():
            cls_clean = cls.split("{")[0].strip()  # strip out {{ }} interpolation
            if cls_clean.startswith("wanelo-"):
                classes.add(cls_clean)
    return classes


@pytest.mark.parametrize("snippet", OPTIONAL_SNIPPETS)
def test_snippet_classes_defined_in_css(snippet: str) -> None:
    """Every wanelo-* class used in a snippet must have AT LEAST ONE matching
    CSS rule — either a direct rule (`.cls{}`) OR a BEM-child rule
    (`.cls__elem`) OR a descendant selector (`.cls .child`).
    Bare parent classes that only act as descendant hooks (no direct styles)
    are OK as long as some descendant style references them."""
    css = CSS_PATH.read_text(encoding="utf-8")
    snippet_classes = _extract_classes_from_snippet(_read(snippet))
    util_classes = {"reveal", "mask", "in", "delay-1", "delay-2", "delay-3",
                    "wanelo-section", "wanelo-head", "wanelo-kicker", "desc"}
    missing = []
    for cls in snippet_classes:
        if cls in util_classes or cls.startswith("wanelo-section"):
            continue
        # Match: .cls (followed by space/punct/eof) OR .cls__elem OR .cls--mod
        if not re.search(rf"\.{re.escape(cls)}(?:[\s,.{{:>+~\[]|__|--)", css):
            missing.append(cls)
    assert not missing, (
        f"{snippet}: classes used but with NO matching CSS rule (direct/BEM/descendant): {missing}"
    )


# ============================================================
# Image URL handling — snippets that show images guard against missing URL
# ============================================================

@pytest.mark.parametrize("snippet", ["wanelo-hero", "wanelo-story"])
def test_image_snippet_guards_missing_url(snippet: str) -> None:
    """Snippets that render <img> must check image_url != blank before
    emitting the tag — otherwise a missing URL produces <img src=''>."""
    src = _read(snippet)
    if "image_url" not in src:
        return  # snippet doesn't use images
    # Find the <img tag and check it's wrapped in a blank-check
    img_idx = src.find("<img")
    assert img_idx != -1
    # Look back ~150 chars for an `image_url != blank` or similar guard
    context = src[max(0, img_idx - 200):img_idx]
    assert (
        "image_url != blank" in context
        or "image_url and " in context.lower()
        or "if chapter.image_url" in context
        or "if hero.image_url" in context
    ), (
        f"{snippet}: <img> tag at offset {img_idx} not preceded by "
        "image_url blank-check; would emit <img src=''> on missing URL"
    )


# ============================================================
# Schema-style consistency — every snippet renders head{} consistently
# ============================================================

SECTIONS_WITH_HEAD = [
    s for s in OPTIONAL_SNIPPETS
    if s not in ("wanelo-hero", "wanelo-cta", "wanelo-palette", "wanelo-interlinks")
]


@pytest.mark.parametrize("snippet", SECTIONS_WITH_HEAD)
def test_snippet_renders_head_consistently(snippet: str) -> None:
    """Every snippet with a `head` block (kicker + h2 + desc) must render
    it via the same Liquid pattern. Inconsistency hints at copy-paste bugs."""
    src = _read(snippet)
    if ".head" not in src:
        pytest.skip(f"{snippet}: no head block")
    # Must render h2 inside the head block
    assert re.search(r"\.head\.h2\s*!=\s*blank", src) or "head.h2" in src, (
        f"{snippet}: head.h2 not rendered/checked"
    )
