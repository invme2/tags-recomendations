"""Тесты валидатора taxonomy на синтетических данных + контрактный тест на реальный taxonomy.json.

Синтетика покрывает все классы ошибок валидатора. Контрактный тест на
реальный файл (если он существует) гарантирует, что прод-данные всегда
проходят валидацию.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "taxonomy" / "tools"))

import validate_taxonomy  # noqa: E402


@pytest.fixture(scope="module")
def schema() -> dict:
    with (ROOT / "taxonomy" / "schema.json").open(encoding="utf-8") as f:
        return json.load(f)


def _valid_taxonomy() -> dict:
    return {
        "version": "3.2",
        "schema_version": "1",
        "updated": "2026-05-05",
        "stats": {"total_clusters": 2},
        "sections": [
            {"id": "1.1", "slug": "rituals-morning-evening", "title_en": "Rituals"},
            {"id": "2",   "slug": "gifts-by-recipient",       "title_en": "Gifts"},
        ],
        "personas": [
            {"tag": "persona:techie", "title_en": "Techie", "embed_text": "tech gadget"},
            {"tag": "persona:gamer",  "title_en": "Gamer",  "embed_text": "rgb console"},
        ],
        "intents": [
            {"tag": "intent:gift",    "title_en": "Gift",    "embed_text": "give present", "rule": "for someone else"},
            {"tag": "intent:impulse", "title_en": "Impulse", "embed_text": "spontaneous", "rule": "under $30"},
        ],
        "demos": [
            {"tag": "demo:female", "title_en": "Female", "type": "gender"},
            {"tag": "demo:male",   "title_en": "Male",   "type": "gender"},
            {"tag": "demo:adult",  "title_en": "Adult",  "type": "age"},
            {"tag": "demo:teen",   "title_en": "Teen",   "type": "age"},
        ],
        "clusters": [
            {
                "tag": "cluster:morning-routine",
                "section_id": "1.1",
                "section": "rituals-morning-evening",
                "section_title_en": "Rituals",
                "section_title_ru": "",
                "title_en": "Morning Routine",
                "title_ru": "",
                "description": "",
                "embed_text": "morning hair makeup mirror",
                "typical_products": ["hair-dryer", "mirror"],
                "personas": ["persona:techie"],
                "intents": ["intent:gift"],
                "demos": {"primary_gender": "demo:female", "ages": ["demo:adult"]},
                "related": ["cluster:gift-set"],
                "synonyms": [],
                "shopify_collection_hints": [],
                "status": "approved",
                "priority": "medium",
                "source": "v3.1",
            },
            {
                "tag": "cluster:gift-set",
                "section_id": "2",
                "section": "gifts-by-recipient",
                "section_title_en": "Gifts",
                "section_title_ru": "",
                "title_en": "Gift Set",
                "title_ru": "",
                "description": "",
                "embed_text": "gift box bundle present",
                "typical_products": ["box"],
                "personas": [],
                "intents": [],
                "demos": {"primary_gender": "", "ages": []},
                "related": [],
                "synonyms": [],
                "shopify_collection_hints": [],
                "status": "draft",
                "priority": "medium",
                "source": "v3.2",
            },
        ],
    }


def test_valid_taxonomy_passes(schema: dict) -> None:
    assert validate_taxonomy.validate(_valid_taxonomy(), schema) == []


def test_duplicate_cluster_tag_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"].append(copy.deepcopy(tax["clusters"][0]))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("duplicate-cluster-tag" in e for e in errs), errs


def test_duplicate_persona_tag_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["personas"].append(copy.deepcopy(tax["personas"][0]))
    errs = validate_taxonomy.validate(tax, schema)
    assert any("duplicate-persona-tag" in e for e in errs), errs


def test_duplicate_section_id_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["sections"].append({"id": "1.1", "slug": "another-slug", "title_en": "x"})
    errs = validate_taxonomy.validate(tax, schema)
    assert any("duplicate-section-id" in e for e in errs), errs


def test_broken_related_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["related"] = ["cluster:does-not-exist"]
    errs = validate_taxonomy.validate(tax, schema)
    assert any("broken-related" in e for e in errs), errs


def test_broken_section_id_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["section_id"] = "9999"
    errs = validate_taxonomy.validate(tax, schema)
    assert any("broken-section-id" in e for e in errs), errs


def test_broken_section_slug_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["section"] = "no-such-section"
    errs = validate_taxonomy.validate(tax, schema)
    assert any("broken-section-slug" in e for e in errs), errs


def test_unknown_persona_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["personas"] = ["persona:unknown"]
    errs = validate_taxonomy.validate(tax, schema)
    assert any("unknown-persona" in e for e in errs), errs


def test_unknown_intent_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["intents"] = ["intent:unknown"]
    errs = validate_taxonomy.validate(tax, schema)
    assert any("unknown-intent" in e for e in errs), errs


def test_unknown_gender_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["demos"]["primary_gender"] = "demo:adult"
    errs = validate_taxonomy.validate(tax, schema)
    assert any("unknown-gender" in e for e in errs), errs


def test_unknown_age_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["demos"]["ages"] = ["demo:female"]
    errs = validate_taxonomy.validate(tax, schema)
    assert any("unknown-age" in e for e in errs), errs


def test_empty_primary_gender_is_allowed(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["demos"]["primary_gender"] = ""
    assert validate_taxonomy.validate(tax, schema) == []


def test_empty_embed_text_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["embed_text"] = "   "
    errs = validate_taxonomy.validate(tax, schema)
    has_empty = any("empty-embed-text" in e for e in errs)
    has_schema_minlen = any("embed_text" in e and "[schema]" in e for e in errs)
    assert has_empty or has_schema_minlen, errs


def test_missing_required_tag_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    del tax["clusters"][0]["tag"]
    errs = validate_taxonomy.validate(tax, schema)
    assert any("[schema]" in e and "tag" in e for e in errs), errs


def test_real_taxonomy_validates() -> None:
    """Контракт: реальный taxonomy.json (если он есть в репо) обязан валидироваться."""
    real = ROOT / "taxonomy" / "taxonomy.json"
    if not real.exists():
        pytest.skip(f"{real} отсутствует — пропуск контрактного теста")
    schema_path = ROOT / "taxonomy" / "schema.json"
    with real.open(encoding="utf-8") as f:
        data = json.load(f)
    with schema_path.open(encoding="utf-8") as f:
        schema = json.load(f)
    errs = validate_taxonomy.validate(data, schema)
    assert errs == [], f"Real taxonomy.json не прошёл валидацию: {errs[:5]}"
