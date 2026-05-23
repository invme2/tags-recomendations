#!/usr/bin/env python3
"""Валидация taxonomy.json (схема v3.x).

Проверки:
1. JSON Schema (taxonomy/schema.json).
2. Уникальность `tag` среди clusters / personas / intents / demos.
3. Уникальность section.id и section.slug.
4. cluster.section_id и cluster.section ссылаются на существующие sections.
5. cluster.related[] ссылается на существующие cluster:* теги.
6. cluster.personas[] ⊂ master persona tags.
7. cluster.intents[] ⊂ master intent tags.
8. cluster.demos.primary_gender (если непустой) ∈ master demos с type='gender'.
9. cluster.demos.ages[] ⊂ master demos с type='age'.
10. cluster.embed_text непустой и не из пробелов.

Exit codes: 0 — ок; 1 — ошибки валидации; 2 — нет источника.
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


def _schema_errors(taxonomy: Any, schema: dict) -> list[str]:
    out: list[str] = []
    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(taxonomy), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"[schema] {loc}: {err.message}")
    return out


def _check_unique(items: list[dict], key: str, kind: str) -> tuple[list[str], dict[str, int]]:
    seen: dict[str, int] = {}
    errors: list[str] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        v = item.get(key)
        if not isinstance(v, str):
            continue
        if v in seen:
            errors.append(f"[duplicate-{kind}] {key}='{v}' встречается в [{seen[v]}] и [{i}]")
        else:
            seen[v] = i
    return errors, seen


def validate(taxonomy: Any, schema: dict) -> list[str]:
    errors: list[str] = _schema_errors(taxonomy, schema)
    if not isinstance(taxonomy, dict):
        return errors

    clusters = taxonomy.get("clusters") or []
    sections = taxonomy.get("sections") or []
    personas = taxonomy.get("personas") or []
    intents = taxonomy.get("intents") or []
    demos = taxonomy.get("demos") or []

    cluster_errs, cluster_tags = _check_unique(clusters, "tag", "cluster-tag")
    persona_errs, persona_tags = _check_unique(personas, "tag", "persona-tag")
    intent_errs, intent_tags = _check_unique(intents, "tag", "intent-tag")
    demo_errs, demo_tags = _check_unique(demos, "tag", "demo-tag")
    section_id_errs, section_ids = _check_unique(sections, "id", "section-id")
    section_slug_errs, section_slugs = _check_unique(sections, "slug", "section-slug")
    errors += (cluster_errs + persona_errs + intent_errs + demo_errs
               + section_id_errs + section_slug_errs)

    valid_cluster_tags = set(cluster_tags)
    valid_persona_tags = set(persona_tags)
    valid_intent_tags = set(intent_tags)
    gender_tags = {d["tag"] for d in demos if isinstance(d, dict) and d.get("type") == "gender"}
    age_tags = {d["tag"] for d in demos if isinstance(d, dict) and d.get("type") == "age"}

    for i, c in enumerate(clusters):
        if not isinstance(c, dict):
            continue
        ctag = c.get("tag", f"index={i}")

        sid = c.get("section_id")
        if isinstance(sid, str) and sid not in section_ids:
            errors.append(f"[broken-section-id] cluster '{ctag}' ссылается на section_id='{sid}', которого нет")
        sslug = c.get("section")
        if isinstance(sslug, str) and sslug not in section_slugs:
            errors.append(f"[broken-section-slug] cluster '{ctag}' ссылается на section='{sslug}', которого нет")

        for ref in c.get("related", []) or []:
            if isinstance(ref, str) and ref not in valid_cluster_tags:
                errors.append(f"[broken-related] cluster '{ctag}' ссылается на '{ref}', которого нет")

        for ref in c.get("personas", []) or []:
            if isinstance(ref, str) and ref not in valid_persona_tags:
                errors.append(f"[unknown-persona] cluster '{ctag}' использует '{ref}', нет в master personas")

        for ref in c.get("intents", []) or []:
            if isinstance(ref, str) and ref not in valid_intent_tags:
                errors.append(f"[unknown-intent] cluster '{ctag}' использует '{ref}', нет в master intents")

        cd = c.get("demos") or {}
        if isinstance(cd, dict):
            pg = cd.get("primary_gender", "")
            if isinstance(pg, str) and pg and pg not in gender_tags:
                errors.append(f"[unknown-gender] cluster '{ctag}' primary_gender='{pg}' не gender-demo")
            for age in cd.get("ages", []) or []:
                if isinstance(age, str) and age not in age_tags:
                    errors.append(f"[unknown-age] cluster '{ctag}' age='{age}' не age-demo")

        text = c.get("embed_text")
        if isinstance(text, str) and not text.strip():
            errors.append(f"[empty-embed-text] cluster '{ctag}' имеет пустой embed_text")

    return errors


def main() -> int:
    if not TAXONOMY_PATH.exists():
        print(f"⏳ taxonomy.json отсутствует ({TAXONOMY_PATH}). Источник ещё не доставлен.")
        return 2
    if not SCHEMA_PATH.exists():
        print(f"❌ schema.json отсутствует ({SCHEMA_PATH}).")
        return 1

    taxonomy = load_json(TAXONOMY_PATH)
    schema = load_json(SCHEMA_PATH)

    errors = validate(taxonomy, schema)
    if errors:
        print(f"❌ Найдено {len(errors)} ошибок:")
        for e in errors[:50]:
            print(f"  - {e}")
        if len(errors) > 50:
            print(f"  ... и ещё {len(errors) - 50}")
        return 1

    n = len(taxonomy.get("clusters", []))
    s = len(taxonomy.get("sections", []))
    p = len(taxonomy.get("personas", []))
    i = len(taxonomy.get("intents", []))
    dm = len(taxonomy.get("demos", []))
    print(f"✅ taxonomy.json валиден. Кластеров: {n}, sections: {s}, "
          f"personas: {p}, intents: {i}, demos: {dm}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
