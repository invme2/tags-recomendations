#!/usr/bin/env python3
"""patch_opus48.py — Strategy model Opus 4.7 -> 4.8 + correct cost formula.

Opus standard pricing has been $5/Mtok in, $25/Mtok out since 4.5 (verified
Jun 2026). The notebook recorded Strategy at $15/$75 (3x too high). This:
  - bumps MODEL_STRATEGY and the Opus connectivity probe to claude-opus-4-8
  - corrects the Strategy cost formula to the real $5 / $25

Either it cuts the real Strategy bill 3x (if 4.7 truly charged $15/$75) or it
just fixes inflated accounting — never worse. nbformat path.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

EDITS = [
    (2, 'MODEL_STRATEGY        = "claude-opus-4-7"',
        'MODEL_STRATEGY        = "claude-opus-4-8"'),
    (4, 'MODEL = "claude-opus-4-7"',
        'MODEL = "claude-opus-4-8"'),
    (14,
     '                _cost_strat = _r_strat.usage.input_tokens * 15/1e6 + _r_strat.usage.output_tokens * 75/1e6',
     '                _cost_strat = _r_strat.usage.input_tokens * 5/1e6 + _r_strat.usage.output_tokens * 25/1e6'),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    for ci, old, new in EDITS:
        cell = nb.cells[ci]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL c{ci}: expected 1 match, found {n}: {old[:50]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK c{ci}: {old[:45]!r} -> updated")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("Opus 4.8 + $5/$25 formula applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
