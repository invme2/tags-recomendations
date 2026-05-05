#!/usr/bin/env python3
"""apply_patch.py — точечный str_replace в конкретной ячейке .ipynb через nbformat.

Workflow (см. ADR-003):
1. Перед использованием — снимок: `cp pipeline/Shopify_Pipeline.ipynb pipeline/.snapshots/$(date +%Y%m%d_%H%M%S)_before-xxx.ipynb`
2. `python pipeline/tools/apply_patch.py --cell 14 --old "image_urls_json['images']" --new "image_urls_json.get('images', [])"`
3. `python pipeline/tools/notebook_smoke.py` — должен пройти.
4. Запись в `pipeline/PATCHES.md` (что было / что стало / зачем).

Параметры:
    --cell INDEX        индекс ячейки (0-based) или
    --cell-id ID        cell_id из notebook (предпочтительнее, если стабилен)
    --old TEXT          старая подстрока (должна встречаться РОВНО ОДИН РАЗ)
    --new TEXT          новая подстрока
    --notebook PATH     путь к .ipynb (по умолчанию pipeline/Shopify_Pipeline.ipynb)
    --dry-run           показать diff, не писать
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NB = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NB)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--cell", type=int, help="индекс ячейки (0-based)")
    g.add_argument("--cell-id", type=str, help="cell_id из notebook")
    parser.add_argument("--old", required=True, help="старая подстрока")
    parser.add_argument("--new", required=True, help="новая подстрока")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.notebook.exists():
        print(f"❌ {args.notebook} не существует.")
        return 1

    try:
        import nbformat
    except ImportError:
        print("❌ nbformat не установлен. `pip install -r requirements-dev.txt`")
        return 1

    nb = nbformat.read(args.notebook, as_version=4)

    if args.cell is not None:
        if not (0 <= args.cell < len(nb.cells)):
            print(f"❌ cell index {args.cell} вне диапазона [0; {len(nb.cells) - 1}]")
            return 1
        cell = nb.cells[args.cell]
        cell_label = f"#{args.cell}"
    else:
        matched = [(i, c) for i, c in enumerate(nb.cells) if c.get("id") == args.cell_id]
        if not matched:
            print(f"❌ cell_id '{args.cell_id}' не найден")
            return 1
        idx, cell = matched[0]
        cell_label = f"#{idx} (id={args.cell_id})"

    if cell.cell_type != "code":
        print(f"❌ cell {cell_label} — не code (type={cell.cell_type}). Не патчим.")
        return 1

    src = cell.source or ""
    occurrences = src.count(args.old)
    if occurrences == 0:
        print(f"❌ Подстрока не найдена в cell {cell_label}.")
        return 1
    if occurrences > 1:
        print(
            f"❌ Подстрока встречается {occurrences} раз в cell {cell_label}. "
            "Уточни --old, чтобы было ровно одно совпадение."
        )
        return 1

    new_src = src.replace(args.old, args.new, 1)
    diff = difflib.unified_diff(
        src.splitlines(keepends=True),
        new_src.splitlines(keepends=True),
        fromfile=f"cell {cell_label} (before)",
        tofile=f"cell {cell_label} (after)",
    )
    sys.stdout.writelines(diff)

    if args.dry_run:
        print("\n[dry-run] изменения не записаны.")
        return 0

    cell.source = new_src
    nbformat.validate(nb)
    nbformat.write(nb, args.notebook)
    print(f"\n✅ Записано в {args.notebook}. Запусти notebook_smoke.py и обнови PATCHES.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
