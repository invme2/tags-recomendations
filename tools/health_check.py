#!/usr/bin/env python3
"""health_check.py — общий smoke-тест проекта.

Запускает:
1. taxonomy/tools/validate_taxonomy.py
2. pipeline/tools/notebook_smoke.py

Возврат:
  0 — оба прошли успешно (не считая «источник отсутствует»).
  1 — хотя бы одна реальная ошибка валидации.
  2 — оба источника отсутствуют (нечего проверять).

«Источник отсутствует» (exit code 2 от под-чека) трактуется как warning,
а не failure — это нормальное состояние свежего bootstrap-репо до доставки
исходников от пользователя.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = [
    ("taxonomy", ROOT / "taxonomy" / "tools" / "validate_taxonomy.py"),
    ("notebook", ROOT / "pipeline" / "tools" / "notebook_smoke.py"),
]


def main() -> int:
    real_failures = 0
    missing_sources = 0
    successes = 0

    for name, path in CHECKS:
        print(f"\n=== {name}: {path.relative_to(ROOT)} ===")
        if not path.exists():
            print(f"❌ Тул отсутствует: {path}")
            real_failures += 1
            continue
        result = subprocess.run([sys.executable, str(path)])
        if result.returncode == 0:
            successes += 1
        elif result.returncode == 2:
            missing_sources += 1
        else:
            real_failures += 1

    print("\n=== Итог ===")
    print(f"  ok:               {successes}")
    print(f"  missing-source:   {missing_sources}")
    print(f"  real-failures:    {real_failures}")

    if real_failures:
        return 1
    if successes == 0 and missing_sources > 0:
        print("⏳ Все источники отсутствуют. Это ожидаемо для свежего bootstrap-репо.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
