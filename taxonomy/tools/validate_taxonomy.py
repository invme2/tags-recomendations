#!/usr/bin/env python3
"""Валидация taxonomy.json.

Проверки:
1. JSON Schema (taxonomy/schema.json).
2. Уникальность `tag` среди кластеров.
3. Все `related[]` ссылаются на существующие `tag`.
4. `embed_text` непуст и не состоит из пробелов.
5. Если на верхнем уровне есть master-списки `personas`/`intents`/`demos`,
   все значения этих полей в кластерах должны входить в master.

Exit codes: 0 — всё ок; 1 — ошибки валидации; 2 — нет источника.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "taxonomy" / "taxonomy.json"
SCHEMA_PATH = ROOT / "taxonomy" / "schema.json"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def validate(taxonomy: Any, schema: dict) -> list[str]:
    errors: list[str] = []

    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(taxonomy), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"[schema] {loc}: {err.message}")

    if not isinstance(taxonomy, dict):
        return errors
    clusters = taxonomy.get("clusters")
    if not isinstance(clusters, list):
        return errors

    seen_tags: dict[str, int] = {}
    for i, cluster in enumerate(clusters):
        if not isinstance(cluster, dict):
            continue
        tag = cluster.get("tag")
        if not isinstance(tag, str):
            continue
        if tag in seen_tags:
            errors.append(
                f"[duplicate-tag] '{tag}' встречается в clusters[{seen_tags[tag]}] и clusters[{i}]"
            )
        else:
            seen_tags[tag] = i

    valid_tags = set(seen_tags)
    for i, cluster in enumerate(clusters):
        if not isinstance(cluster, dict):
            continue
        related = cluster.get("related", [])
        if not isinstance(related, list):
            continue
        for ref in related:
            if isinstance(ref, str) and ref not in valid_tags:
                errors.append(
                    f"[broken-related] clusters[{i}].related ссылается на несуществующий tag '{ref}'"
                )

    for i, cluster in enumerate(clusters):
        if not isinstance(cluster, dict):
            continue
        text = cluster.get("embed_text")
        if isinstance(text, str) and not text.strip():
            tag = cluster.get("tag", f"index={i}")
            errors.append(f"[empty-embed-text] cluster '{tag}' имеет пустой embed_text")

    for field in ("personas", "intents", "demos"):
        master = taxonomy.get(field)
        if not isinstance(master, list):
            continue
        master_set = {x for x in master if isinstance(x, str)}
        for i, cluster in enumerate(clusters):
            if not isinstance(cluster, dict):
                continue
            values = cluster.get(field, [])
            if not isinstance(values, list):
                continue
            for v in values:
                if isinstance(v, str) and v not in master_set:
                    tag = cluster.get("tag", f"index={i}")
                    errors.append(
                        f"[unknown-{field[:-1]}] cluster '{tag}' использует '{v}', "
                        f"которого нет в master-списке {field}"
                    )

    return errors


def main() -> int:
    if not TAXONOMY_PATH.exists():
        print(f"⏳ taxonomy.json отсутствует ({TAXONOMY_PATH}). Источник ещё не доставлен.")
        print("   Это не ошибка валидации, но и не успех. Вернёт exit code 2.")
        return 2

    if not SCHEMA_PATH.exists():
        print(f"❌ schema.json отсутствует ({SCHEMA_PATH}).")
        return 1

    taxonomy = load_json(TAXONOMY_PATH)
    schema = load_json(SCHEMA_PATH)

    errors = validate(taxonomy, schema)
    if errors:
        print(f"❌ Найдено {len(errors)} ошибок:")
        for e in errors:
            print(f"  - {e}")
        return 1

    n_clusters = len(taxonomy.get("clusters", [])) if isinstance(taxonomy, dict) else 0
    print(f"✅ taxonomy.json валиден. Кластеров: {n_clusters}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
