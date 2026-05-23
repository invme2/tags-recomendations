#!/usr/bin/env python3
"""notebook_smoke.py — валидация Shopify_Pipeline.ipynb без выполнения кода.

Проверки:
1. `nbformat.read` + `nbformat.validate` (структура notebook).
2. `ast.parse` каждой code-ячейки (синтаксис Python).
3. Дефинированность имён между ячейками — **только на module-level scope**.
   Внутрь тел функций / классов / lambda не заходим: их локальные имена и
   параметры — забота Python runtime, а не статического межъячеечного
   smoke-теста. Цель проверки — поймать удалённую функцию или сломанный
   порядок ячеек, а не валидировать имена внутри функций.

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


def _names(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _names(elt)
    elif isinstance(node, ast.Starred):
        yield from _names(node.value)


class _ModuleScopeAnalyzer(ast.NodeVisitor):
    """Собирает defined/loaded имена только в module-level scope ячейки.

    В тела функций / async-функций / lambda / класса не рекурсируем —
    их имена живут в собственном scope. От FunctionDef/ClassDef записываем
    только само имя функции/класса (оно появляется в module scope).
    Декораторы и default-значения параметров посещаем (они вычисляются
    в module scope).
    """

    def __init__(self) -> None:
        self.defined: set[str] = set()
        self.loaded: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined.add(node.name)
        for d in node.decorator_list:
            self.visit(d)
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined.add(node.name)
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defined.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.defined.add((alias.asname or alias.name).split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.defined.add((alias.asname or alias.name).split(".")[0])

    def visit_For(self, node: ast.For) -> None:
        for n in _names(node.target):
            self.defined.add(n)
        self.visit(node.iter)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For  # type: ignore[assignment]

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                for n in _names(item.optional_vars):
                    self.defined.add(n)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With  # type: ignore[assignment]

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.defined.add(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.target)
        self.visit(node.value)


def _strip_magics(source: str) -> str:
    out: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("!", "%", "?")):
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def main() -> int:
    if not NOTEBOOK_PATH.exists():
        print(f"⏳ {NOTEBOOK_PATH.name} отсутствует ({NOTEBOOK_PATH}). Источник ещё не доставлен.")
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
            errors.append(f"[syntax] code-cell #{i}: {e.msg} (line {e.lineno})")
            continue

        analyzer = _ModuleScopeAnalyzer()
        analyzer.visit(tree)

        for name in sorted(analyzer.loaded - cumulative - analyzer.defined):
            errors.append(f"[undefined-name] code-cell #{i}: '{name}' не определено на module-level")
        cumulative |= analyzer.defined

    if errors:
        print(f"❌ Найдено {len(errors)} ошибок:")
        for e in errors[:50]:
            print(f"  - {e}")
        if len(errors) > 50:
            print(f"  ... и ещё {len(errors) - 50}")
        return 1

    print(f"✅ Notebook валиден. Ячеек: {len(nb.cells)} (code: {len(code_cells)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
