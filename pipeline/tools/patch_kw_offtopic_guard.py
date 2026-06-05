# -*- coding: utf-8 -*-
"""patch_kw_offtopic_guard.py — make Claude's collection-copy generation
explicitly reject off-topic / wrong-category / brand keywords.

WHY: the per-collection `top_keywords` list is volume-ranked from DataForSEO and
FAISS-validated, but NOT intent-curated — generic single-word seeds ("oil",
"brush", "knee") pull huge-volume but off-topic terms (e.g. "coconut oil" into
"Oil Absorbing Tools", "hoover carpet cleaner" into "Makeup Brushes"). Empirically
Claude already filters most of this when writing titles/metas/descriptions (the
live Tools&Accessories output is clean), but the instruction was permissive
("weave in naturally"). This hardens the prompt so the filtering is explicit and
robust to edge cases — WITHOUT a brittle deterministic keyword filter that could
drop genuinely-relevant no-overlap terms (e.g. "red light therapy" for eye
massagers).

Two edits, both prompt-only (no logic change):
  cell 4 — generate_collection_html kw_instruction
  cell 6 — batch SEO title/meta prompt

After: notebook_smoke + pytest.
"""
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

CELL4_OLD = (
    '            kw_instruction = f"\\nTop SEO keywords to weave in naturally '
    '(sorted by search volume): {top_keywords}\\n"'
)
CELL4_NEW = (
    '            kw_instruction = f"\\nCandidate SEO keywords (volume-ranked, NOT curated '
    '— may include off-topic or brand terms). Weave in ONLY those that genuinely match the '
    'product type of THIS collection; IGNORE off-topic, wrong-category, or brand keywords: '
    '{top_keywords}\\n"'
)

CELL6_OLD = (
    "            '4. md: Meta description (140-155 chars) with call to action\\n'\n"
    "            'DATA:\\n' + batch_data + '\\n'"
)
CELL6_NEW = (
    "            '4. md: Meta description (140-155 chars) with call to action\\n'\n"
    "            'CRITICAL: keyword lists are volume-ranked, NOT curated — they may include "
    "off-topic, wrong-category, or brand keywords. Use ONLY keywords that genuinely match the "
    "product type of each collection; IGNORE the rest. Never put a brand name or unrelated "
    "product category in the title or meta.\\n'\n"
    "            'DATA:\\n' + batch_data + '\\n'"
)

EDITS = [
    (4, CELL4_OLD, CELL4_NEW),
    (6, CELL6_OLD, CELL6_NEW),
]


def main():
    nb = nbformat.read(NB, as_version=4)
    for idx, (cell_i, old, new) in enumerate(EDITS):
        cell = nb.cells[cell_i]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx} (cell {cell_i}): found {n} (need 1)")
            print(f"  anchor: {old[:80]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx} (cell {cell_i})")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("off-topic/brand keyword guard added to collection title + description prompts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
