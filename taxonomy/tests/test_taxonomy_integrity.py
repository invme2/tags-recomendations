"""Integrity- и lifecycle-тесты для taxonomy.json.

Эти тесты проверяют **реальный** `taxonomy.json` на инварианты, которые
JSON Schema не выражает (ссылочная согласованность денормализованных полей,
namespace-префиксы, регрессии вроде «v3.3 без русских keywords в embed_text»),
и эмулируют добавление новых кластеров (проверка, что валидатор корректно
ловит ошибки добавления).

Синтетические тесты на конкретные классы ошибок валидатора лежат в
`test_taxonomy.py` — здесь только то, что касается живых данных и lifecycle
правок.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "taxonomy" / "tools"))

import validate_taxonomy  # noqa: E402

REAL_TAXONOMY = ROOT / "taxonomy" / "taxonomy.json"
SCHEMA_PATH = ROOT / "taxonomy" / "schema.json"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def real() -> dict:
    if not REAL_TAXONOMY.exists():
        pytest.skip(f"{REAL_TAXONOMY} отсутствует")
    return _load(REAL_TAXONOMY)


@pytest.fixture(scope="module")
def schema() -> dict:
    return _load(SCHEMA_PATH)


# ============================================================
# Integrity — реальные данные
# ============================================================

def test_every_section_has_at_least_one_cluster(real: dict) -> None:
    """Каждая секция должна содержать хотя бы один кластер.

    Orphan-секции — мёртвый груз: либо удалить секцию, либо наполнить.
    """
    used_section_ids = {c["section_id"] for c in real["clusters"]}
    declared_section_ids = {s["id"] for s in real["sections"]}
    orphans = declared_section_ids - used_section_ids
    assert not orphans, f"Orphan-секции (есть в sections, но ни один кластер не ссылается): {sorted(orphans)}"


def test_cluster_section_denormalization_consistent(real: dict) -> None:
    """cluster.section / section_title_en должны совпадать с sections[section_id]."""
    sections = {s["id"]: s for s in real["sections"]}
    mismatches: list[str] = []
    for c in real["clusters"]:
        sec = sections.get(c["section_id"])
        if not sec:
            continue
        if c["section"] != sec["slug"]:
            mismatches.append(
                f"{c['tag']}: section='{c['section']}' но sections[{c['section_id']}].slug='{sec['slug']}'"
            )
        if c["section_title_en"] != sec["title_en"]:
            mismatches.append(
                f"{c['tag']}: section_title_en='{c['section_title_en']}' но "
                f"sections[{c['section_id']}].title_en='{sec['title_en']}'"
            )
    assert not mismatches, "\n".join(mismatches[:10])


def test_namespaced_tags_format(real: dict) -> None:
    """Все теги должны иметь корректный namespace-префикс."""
    expected = {
        "clusters": "cluster:",
        "personas": "persona:",
        "intents": "intent:",
        "demos": "demo:",
    }
    bad: list[str] = []
    for collection, prefix in expected.items():
        for item in real[collection]:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag", "")
            if not isinstance(tag, str) or not tag.startswith(prefix):
                bad.append(f"{collection}: '{tag}' должен начинаться с '{prefix}'")
    assert not bad, "\n".join(bad[:10])


def test_no_duplicate_titles_within_section(real: dict) -> None:
    """В одной секции не должно быть двух кластеров с одинаковым title_en.

    Это soft-правило: формально схема позволяет, но обычно сигнализирует о
    неаккуратности (двойной добавке).
    """
    by_section_title: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in real["clusters"]:
        by_section_title[(c["section_id"], c["title_en"].strip().lower())].append(c["tag"])
    dups = {k: v for k, v in by_section_title.items() if len(v) > 1}
    assert not dups, f"Дубликаты title_en внутри секций: {dups}"


def test_stats_total_matches_clusters_length(real: dict) -> None:
    """stats.total_clusters должен совпадать с фактическим len(clusters)."""
    actual = len(real["clusters"])
    declared = real.get("stats", {}).get("total_clusters")
    assert declared == actual, f"stats.total_clusters={declared}, факт={actual}"


def test_stats_status_counts_match(real: dict) -> None:
    """stats.approved + stats.draft должны совпадать с фактическими."""
    approved = sum(1 for c in real["clusters"] if c["status"] == "approved")
    draft = sum(1 for c in real["clusters"] if c["status"] == "draft")
    assert real["stats"]["approved"] == approved, \
        f"stats.approved={real['stats']['approved']}, факт={approved}"
    assert real["stats"]["draft"] == draft, \
        f"stats.draft={real['stats']['draft']}, факт={draft}"


def test_v33_clusters_have_russian_in_embed_text(real: dict) -> None:
    """Регрессия для bilingual-патча итерации 2.

    Кластеры source=v3.3 должны иметь русские keywords в embed_text — иначе
    cross-lingual matching (TF-IDF и слабые semantic-модели) не находит их
    по русским запросам. Признак русского — кириллический символ в тексте.
    """
    cyrillic = re.compile(r"[А-Яа-яЁё]")
    bad: list[str] = []
    for c in real["clusters"]:
        if c.get("source") == "v3.3" and not cyrillic.search(c.get("embed_text", "")):
            bad.append(c["tag"])
    assert not bad, f"v3.3 кластеры без кириллицы в embed_text: {bad}"


def test_real_taxonomy_passes_full_validator(real: dict, schema: dict) -> None:
    """Полный прогон validate() на реальных данных — должен быть чист."""
    errs = validate_taxonomy.validate(real, schema)
    assert errs == [], f"validate() на реальных данных: {errs[:5]}"


# ============================================================
# Lifecycle — добавление новых кластеров
# ============================================================

def _new_cluster(real: dict, **overrides: object) -> dict:
    """Минимальный валидный draft-кластер на базе первой секции."""
    sec = real["sections"][0]
    cluster = {
        "tag": "cluster:lifecycle-test-fixture",
        "section_id": sec["id"],
        "section": sec["slug"],
        "section_title_en": sec["title_en"],
        "section_title_ru": "",
        "title_en": "Lifecycle Fixture",
        "title_ru": "",
        "description": "",
        "embed_text": "Lifecycle Fixture | lifecycle | Fixture test embed text",
        "typical_products": ["test-item"],
        "personas": [],
        "intents": [],
        "demos": {"primary_gender": "", "ages": []},
        "related": [],
        "synonyms": [],
        "shopify_collection_hints": [],
        "status": "draft",
        "priority": "medium",
        "source": "v0-test",
    }
    cluster.update(overrides)  # type: ignore[arg-type]
    return cluster


def test_lifecycle_add_valid_cluster_passes(real: dict, schema: dict) -> None:
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real))
    errs = validate_taxonomy.validate(tax, schema)
    assert errs == [], errs


def test_lifecycle_add_unknown_section_id_fails(real: dict, schema: dict) -> None:
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real, section_id="999.99"))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("broken-section-id" in e for e in errs), errs


def test_lifecycle_add_duplicate_tag_fails(real: dict, schema: dict) -> None:
    tax = copy.deepcopy(real)
    existing_tag = tax["clusters"][0]["tag"]
    tax["clusters"].append(_new_cluster(real, tag=existing_tag))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("duplicate-cluster-tag" in e for e in errs), errs


def test_lifecycle_add_invalid_tag_namespace_fails(real: dict, schema: dict) -> None:
    """Tag без префикса 'cluster:' должен быть отклонён схемой (pattern)."""
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real, tag="bare-tag-without-namespace"))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("[schema]" in e and "tag" in e for e in errs), errs


def test_lifecycle_add_empty_embed_text_fails(real: dict, schema: dict) -> None:
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real, embed_text=" "))
    errs = validate_taxonomy.validate(tax, schema)
    has_business = any("empty-embed-text" in e for e in errs)
    has_schema = any("[schema]" in e and "embed_text" in e for e in errs)
    assert has_business or has_schema, errs


def test_lifecycle_add_unknown_persona_in_cluster_fails(real: dict, schema: dict) -> None:
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real, personas=["persona:does-not-exist"]))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("unknown-persona" in e for e in errs), errs


def test_lifecycle_add_invalid_status_fails(real: dict, schema: dict) -> None:
    """status ∈ {approved, draft} — другие значения должны падать."""
    tax = copy.deepcopy(real)
    tax["clusters"].append(_new_cluster(real, status="experimental"))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("[schema]" in e and "status" in e for e in errs), errs
