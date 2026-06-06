#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_vibe_phase1.py — Wanelo Vibe redesign, Phase 1 (tokens + theme settings).
Uploads snippets/wanelo-vibe-tokens.liquid, adds a "Wanelo Vibe — Design" section
to config/settings_schema.json (colors + font toggle, editable in the customizer),
and injects the snippet before </head> in layout/theme.liquid. Snapshots first.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_edit as T

ROOT = Path(__file__).resolve().parents[2]
SNIPPET_SRC = ROOT / "pipeline" / "theme_assets" / "snippets" / "wanelo-vibe-tokens.liquid"
TS = "20260606-vibe1"

VIBE_SECTION = {
    "name": "Wanelo Vibe — Design",
    "settings": [
        {"type": "header", "content": "Typography (Vibe)"},
        {"type": "checkbox", "id": "vibe_fonts_on", "label": "Use Vibe fonts (Onest body + Space Grotesk headings)", "default": True},
        {"type": "font_picker", "id": "vibe_body_font", "label": "Body font (used when Vibe fonts is off)", "default": "assistant_n4"},
        {"type": "font_picker", "id": "vibe_heading_font", "label": "Heading font (used when Vibe fonts is off)", "default": "assistant_n4"},
        {"type": "header", "content": "Brand colors (Vibe)"},
        {"type": "color", "id": "vibe_brand", "label": "Brand (primary)", "default": "#7c5cfc"},
        {"type": "color", "id": "vibe_brand_ink", "label": "Brand ink (dark)", "default": "#6442e8"},
        {"type": "color", "id": "vibe_accent", "label": "Accent", "default": "#1763ff"},
        {"type": "color", "id": "vibe_lime", "label": "Lime / acid", "default": "#e6fb55"},
        {"type": "color", "id": "vibe_pink", "label": "Pink / hot", "default": "#ff3dbd"},
        {"type": "color", "id": "vibe_teal", "label": "Teal", "default": "#1fc9c9"},
        {"type": "color", "id": "vibe_ink", "label": "Text", "default": "#10151c"},
        {"type": "color", "id": "vibe_bg", "label": "Page background", "default": "#f3f4f8"},
        {"type": "checkbox", "id": "vibe_apply_colors", "label": "Apply Vibe brand color to links & Wanelo sections", "default": True},
    ],
}


def main():
    tok = T.token(); tid = T.main_theme_id(tok)

    # 1) snippet
    snip = SNIPPET_SRC.read_text(encoding="utf-8")
    sc, _ = T.upload(tok, tid, "snippets/wanelo-vibe-tokens.liquid", snip)
    print("snippet upload:", sc)

    # 2) settings_schema.json — add Vibe section (idempotent)
    ss = T.fetch(tok, tid, "config/settings_schema.json")
    T.snapshot("config/settings_schema.json", ss, TS)
    data = json.loads(ss)
    if any(isinstance(s, dict) and s.get("name") == VIBE_SECTION["name"] for s in data):
        print("settings: Vibe section already present")
    else:
        data.append(VIBE_SECTION)
        sc, r = T.upload(tok, tid, "config/settings_schema.json", json.dumps(data, ensure_ascii=False, indent=2))
        print("settings_schema upload:", sc, (r.get("errors") if isinstance(r, dict) else ""))

    # 3) inject snippet render before </head> in theme.liquid (idempotent)
    th = T.fetch(tok, tid, "layout/theme.liquid")
    T.snapshot("layout/theme.liquid", th, TS)
    if "wanelo-vibe-tokens" in th:
        print("theme.liquid: render already present")
    else:
        marker = "</head>"
        th2 = th.replace(marker, "  {% render 'wanelo-vibe-tokens' %}\n" + marker, 1)
        if th2 == th:
            print("! </head> not found — render NOT injected")
        else:
            sc, _ = T.upload(tok, tid, "layout/theme.liquid", th2)
            print("theme.liquid upload:", sc)
    print("\nDone. Theme settings → 'Wanelo Vibe — Design'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
