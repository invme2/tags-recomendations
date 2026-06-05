# -*- coding: utf-8 -*-
"""patch_inline_noclone.py — stop inline photos cloning carousel photos.

Audit found inline briefs reuse the SAME source_index as carousel briefs (e.g.
inline-hero shares source_index 1 with carousel-hero) AND use near-identical
concepts ("matching page hero") -> the operator's generated inline photos come
out looking like clones of the carousel shots.

Fix: strengthen two Designer rules:
  1. inline briefs MUST prefer a different source_index than any carousel brief;
     reuse only with a DRAMATICALLY different concept (scene/crop/people/context).
  2. inline-hero MUST be a lifestyle / in-context scene, never a clean product
     shot and never the same look/source as carousel-hero.
nbformat path. After: notebook_smoke + pytest.
"""
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

EDITS = [
    (
        "- Reuse same source_index ONLY if you give DIFFERENT edit_instructions "
        "(e.g. same product photo edited twice — once white-bg hero, once warm-light lifestyle).",
        "- NO CLONES: inline briefs MUST use a DIFFERENT source_index than EVERY carousel brief whenever the "
        "EPROLO list allows. Reuse a source_index across carousel and inline ONLY with a DRAMATICALLY different "
        "concept AND edit_instructions (different scene, crop, people, angle, context) — same source_index + "
        "similar concept = duplicate-looking photos, FORBIDDEN. Carousel = clean studio-style product shots; "
        "inline = lifestyle / narrative / in-use scenes. They must look clearly different.",
    ),
    (
        "  - inline-hero       → goes into hero block bg/photo (page top after carousel). "
        "Reinforces the H1 message; do NOT duplicate carousel-hero.",
        "  - inline-hero       → goes into the hero CONTENT block. It MUST be a LIFESTYLE / in-context / "
        "emotional scene that reinforces the H1 — NEVER a clean product-on-background shot, NEVER the same "
        "source_index or look as carousel-hero. If carousel-hero is the clean product, inline-hero shows the "
        "product BEING USED in a real setting.",
    ),
]


def main():
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[14]
    for idx, (old, new) in enumerate(EDITS):
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx}: found {n}")
            print(f"  old: {old[:60]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx}")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("inline no-clone rules applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
