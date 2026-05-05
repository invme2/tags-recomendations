#!/usr/bin/env python3
"""notebook_smoke.py — валидация Shopify_Pipeline.ipynb без выполнения кода.

Проверки:
1. `nbformat.read` + `nbformat.validate` (структура notebook).
2. `ast.parse` каждой code-ячейки (синтаксис Python).
3. Дефинированность имён между ячейками: для каждого имени, используемого
   как Load (чтение), требуется чтобы оно было определено в этой или
   предыдущей ячейке (Store), либо относилось к stdlib/builtins/импорту.
   Эвристика — не строгий type-checker, цель — словить сломанный порядок
   ячеек или удалённую функцию.

Exit codes: 0 — ок; 1 — ошибки; 2 — нет источника.
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"


def _collect_defined(tree: ast.AST) -> set[str]:
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                defined.update(_targets(tgt))
        elif isinstance(node, ast.AugAssign):
            defined.update(_targets(node.target))
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            defined.update(_targets(node.target))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            defined.update(_targets(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    defined.update(_targets(item.optional_vars))
        elif isinstance(node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for gen in getattr(node, "generators", []):
                defined.update(_targets(gen.target))
        elif isinstance(node, ast.NamedExpr):
            defined.update(_targets(node.target))
        elif isinstance(node, ast.Global):
            defined.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            defined.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    return defined


def _targets(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _targets(elt)
    elif isinstance(node, ast.Starred):
        yield from _targets(node.value)


def _collect_loaded(tree: ast.AST) -> set[str]:
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)
    return loaded


def _strip_magics(source: str) -> str:
    out_lines: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("!") or stripped.startswith("%") or stripped.startswith("?"):
            out_lines.append("")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def main() -> int:
    if not NOTEBOOK_PATH.exists():
        print(f"⏳ {NOTEBOOK_PATH.name} отсутствует ({NOTEBOOK_PATH}). Источник ещё не доставлен.")
        print("   Это не ошибка валидации, но и не успех. Вернёт exit code 2.")
        return 2

    try:
        import nbformat
    except ImportError:
        print("❌ nbformat не установлен. `pip install -r requirements-dev.txt`")
        return 1

    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    try:
        nbformat.validate(nb)
    except nbformat.ValidationError as e:
        print(f"❌ nbformat.validate: {e}")
        return 1

    errors: list[str] = []
    cumulative: set[str] = set(dir(builtins))
    code_cells = [c for c in nb.cells if c.cell_type == "code"]

    for i, cell in enumerate(code_cells):
        source = _strip_magics(cell.source or "")
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            errors.append(f"[syntax] cell #{i}: {e.msg} (line {e.lineno})")
            continue

        loaded = _collect_loaded(tree)
        defined_here = _collect_defined(tree)
        for name in sorted(loaded - cumulative - defined_here):
            errors.append(f"[undefined-name] cell #{i}: '{name}' используется до определения")
        cumulative |= defined_here

    if errors:
        print(f"❌ Найдено {len(errors)} ошибок:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"✅ Notebook валиден. Ячеек: {len(nb.cells)} (code: {len(code_cells)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
