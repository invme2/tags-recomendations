"""Тесты валидатора taxonomy на синтетических данных.

Тестируем сам валидатор: что он принимает корректные данные и ловит
конкретные классы ошибок. Реальный taxonomy.json в эту проверку не входит
(для него — отдельная цель в CI).
"""

from __future__ import annotations

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
        "version": "0.1.0",
        "personas": ["new-mom", "gamer"],
        "intents": ["gift", "self-use"],
        "demos": ["female", "male"],
        "clusters": [
            {
                "tag": "baby-blanket-organic",
                "personas": ["new-mom"],
                "intents": ["gift"],
                "demos": ["female"],
                "related": ["baby-toy-wooden"],
                "embed_text": "organic cotton baby blanket, soft, hypoallergenic",
            },
            {
                "tag": "baby-toy-wooden",
                "personas": ["new-mom"],
                "intents": ["gift", "self-use"],
                "demos": ["female", "male"],
                "related": [],
                "embed_text": "wooden baby toy, eco-friendly, montessori",
            },
        ],
    }


def test_valid_taxonomy_passes(schema: dict) -> None:
    errors = validate_taxonomy.validate(_valid_taxonomy(), schema)
    assert errors == []


def test_duplicate_tag_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"].append(
        {"tag": "baby-blanket-organic", "embed_text": "duplicate"}
    )
    errors = validate_taxonomy.validate(tax, schema)
    assert any("duplicate-tag" in e for e in errors), errors


def test_broken_related_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["related"] = ["does-not-exist"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("broken-related" in e for e in errors), errors


def test_empty_embed_text_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["embed_text"] = "   "
    errors = validate_taxonomy.validate(tax, schema)
    assert any("empty-embed-text" in e for e in errors), errors


def test_missing_required_tag_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    del tax["clusters"][0]["tag"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("schema" in e and "tag" in e for e in errors), errors


def test_missing_required_embed_text_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    del tax["clusters"][0]["embed_text"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("schema" in e and "embed_text" in e for e in errors), errors


def test_unknown_persona_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["personas"] = ["unknown-persona"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("unknown-persona" in e for e in errors), errors


def test_unknown_intent_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["intents"] = ["unknown-intent"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("unknown-intent" in e for e in errors), errors


def test_unknown_demo_detected(schema: dict) -> None:
    tax = _valid_taxonomy()
    tax["clusters"][0]["demos"] = ["unknown-demo"]
    errors = validate_taxonomy.validate(tax, schema)
    assert any("unknown-demo" in e for e in errors), errors


def test_no_master_lists_means_no_membership_check(schema: dict) -> None:
    tax = _valid_taxonomy()
    del tax["personas"]
    del tax["intents"]
    del tax["demos"]
    errors = validate_taxonomy.validate(tax, schema)
    assert errors == []
