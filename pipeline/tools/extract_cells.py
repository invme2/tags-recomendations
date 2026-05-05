#!/usr/bin/env python3
"""extract_cells.py — конвертирует .ipynb в плоский .py для удобного чтения.

Каждая ячейка обернута в комментарий-заголовок с её индексом и cell_id.
Markdown-ячейки идут как блок `# === MARKDOWN cell #N === ` с содержимым
в комментариях.

Использование:
    python pipeline/tools/extract_cells.py
        # → pipeline/Shopify_Pipeline.extracted.py

    python pipeline/tools/extract_cells.py --notebook path/to/other.ipynb --out other.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NB = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
DEFAULT_OUT = ROOT / "pipeline" / "Shopify_Pipeline.extracted.py"


def extract(nb_path: Path, out_path: Path) -> int:
    if not nb_path.exists():
        print(f"⏳ {nb_path} отсутствует. Источник ещё не доставлен.")
        return 2

    try:
        import nbformat
    except ImportError:
        print("❌ nbformat не установлен. `pip install -r requirements-dev.txt`")
        return 1

    nb = nbformat.read(nb_path, as_version=4)
    chunks: list[str] = [
        f"# Auto-generated from {nb_path.name}. DO NOT EDIT — правь .ipynb через apply_patch.py.\n"
    ]
    for i, cell in enumerate(nb.cells):
        cid = cell.get("id", "<no-id>")
        header = f"\n# === {cell.cell_type.upper()} cell #{i} (id={cid}) ===\n"
        chunks.append(header)
        if cell.cell_type == "code":
            chunks.append((cell.source or "") + "\n")
        else:
            commented = "\n".join(f"# {line}" for line in (cell.source or "").splitlines())
            chunks.append(commented + "\n")
    out_path.write_text("".join(chunks), encoding="utf-8")
    print(f"✅ Извлечено в {out_path} ({len(nb.cells)} ячеек).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    return extract(args.notebook, args.out)


if __name__ == "__main__":
    sys.exit(main())
