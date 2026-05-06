"""Тесты для pipeline/page_builder.py.

Проверяют ключевые инварианты сборки product-page HTML:
- module-каталог корректно описан
- assemble_page подставляет slot-значения
- :root палитра инжектится из аргумента
- topbar / footer / shipping / returns отсутствуют в выходе (требование пользователя)
- ошибочный layout/несовпадение длин — даёт ValueError
- HTML самосогласован (теги Inter+Fraunces, doctype, JS reveal-observer)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

import page_builder as pb  # noqa: E402


PALETTE = {
    "brand_1": "#ff9c70",
    "brand_2": "#aac9f5",
    "brand_3": "#a6d8be",
    "brand_soft": "#ffe9d6",
    "brand_deep": "#ffc8b0",
}


def _slots_for(module_id: str) -> dict[str, str]:
    """Минимальный валидный slot-словарь для каждого модуля."""
    spec = pb.MODULE_CATALOG[module_id]
    return {slot: f"<{slot}>" for slot in spec["slots"]}


# ============================================================
# Структура каталога
# ============================================================

def test_catalog_has_at_least_one_per_kind() -> None:
    kinds = {m["kind"] for m in pb.MODULE_CATALOG.values()}
    assert "hero" in kinds
    assert "intro" in kinds
    assert "story" in kinds
    assert "features" in kinds
    assert "facts" in kinds
    assert "reviews" in kinds


def test_catalog_descriptions_non_trivial() -> None:
    for mid, m in pb.MODULE_CATALOG.items():
        assert m["description"] and len(m["description"]) > 30, mid
        assert m["slots"], mid


def test_every_catalog_id_has_html_template() -> None:
    for mid in pb.MODULE_CATALOG:
        assert mid in pb._MODULE_HTML, mid


# ============================================================
# render_module / format_map
# ============================================================

def test_render_module_substitutes_slots() -> None:
    html = pb.render_module(
        "hero1",
        {"KICKER": "Test kicker", "H1": "Hello", "P": "World", "IMG_URL": "u.jpg", "IMG_ALT": "alt"},
    )
    assert "Test kicker" in html
    assert "Hello" in html
    assert 'src="u.jpg"' in html


def test_render_module_missing_slot_renders_empty() -> None:
    html = pb.render_module("hero1", {"H1": "Only h1"})
    assert "Only h1" in html
    # other slots should be empty strings, not braces
    assert "{KICKER}" not in html
    assert "{P}" not in html


def test_render_module_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        pb.render_module("does-not-exist", {})


def test_render_module_none_slot_value_treated_as_empty() -> None:
    html = pb.render_module("hero1", {"KICKER": None, "H1": "ok"})
    assert "ok" in html
    assert "None" not in html


# ============================================================
# Theme tokens / palette injection
# ============================================================

def test_palette_injected_into_root() -> None:
    css = pb.render_theme_tokens(PALETTE)
    for key, hex_val in PALETTE.items():
        assert hex_val in css, key
    assert ":root{" in css


def test_palette_partial_uses_defaults_for_missing() -> None:
    css = pb.render_theme_tokens({"brand_1": "#000000"})
    assert "#000000" in css
    # the others must fall back to defaults (template defaults)
    assert "#aac9f5" in css  # default brand_2


def test_palette_none_uses_all_defaults() -> None:
    css = pb.render_theme_tokens(None)
    assert "#ff9c70" in css


# ============================================================
# assemble_page — full assembly
# ============================================================

def test_assemble_minimal_shopify_fragment_default() -> None:
    """По умолчанию — shopify_fragment с wa-page wrapper."""
    out = pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE)
    assert out.startswith('<div class="rte wa-page"')
    assert out.strip().endswith("</div>")
    assert "<!doctype" not in out.lower()
    assert "<html" not in out
    assert "hero-alt hero1" in out


def test_assemble_full_document_when_requested() -> None:
    out = pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE, output_format="full", title="Demo")
    assert out.startswith("<!doctype html>")
    assert "</html>" in out.strip()
    assert "<title>Demo</title>" in out
    assert 'class="rte wa-page"' not in out


def test_assemble_unknown_output_format_raises() -> None:
    with pytest.raises(ValueError, match="output_format"):
        pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE, output_format="weird")


def test_assemble_six_module_layout() -> None:
    layout = ["hero1", "m16", "m21", "m32", "m41", "m51"]
    slot_values = [_slots_for(m) for m in layout]
    out = pb.assemble_page(layout, slot_values, PALETTE)
    for m in layout:
        # Each module's CSS class must appear in output
        if m == "hero1":   assert "hero-alt hero1" in out
        elif m == "m16":   assert 'class="m16 reveal"' in out
        elif m == "m21":   assert "story-row reveal" in out
        elif m == "m32":   assert 'class="m32 reveal"' in out
        elif m == "m41":   assert 'class="m41 reveal"' in out
        elif m == "m51":   assert "m51-stage reveal" in out


def test_assemble_repeated_modules_allowed() -> None:
    """Opus может выбрать m21 дважды — для двухчаптерной story."""
    out = pb.assemble_page(
        ["m21", "m21"],
        [_slots_for("m21"), _slots_for("m21")],
        PALETTE,
    )
    assert out.count("story-row reveal") == 2


def test_assemble_layout_slots_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="len.*!=.*"):
        pb.assemble_page(["hero1", "m21"], [_slots_for("hero1")], PALETTE)


def test_assemble_unknown_module_raises() -> None:
    with pytest.raises(ValueError, match="unknown module ids"):
        pb.assemble_page(["does-not-exist"], [{}], PALETTE)


# ============================================================
# Анти-требования: чего В ВЫХОДЕ НЕ ДОЛЖНО БЫТЬ
# ============================================================

def test_assembled_html_has_no_topbar() -> None:
    out = pb.assemble_page(["hero1", "m51"], [_slots_for("hero1"), _slots_for("m51")], PALETTE)
    assert "topbar" not in out.lower()
    assert "<nav" not in out.lower()


def test_assembled_html_has_no_footer() -> None:
    out = pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE)
    assert "<footer" not in out.lower()


def test_assembled_html_has_no_shipping_or_returns_text() -> None:
    out = pb.assemble_page(["hero1", "m41"], [_slots_for("hero1"), _slots_for("m41")], PALETTE)
    low = out.lower()
    for forbidden in ("shipping", "returns policy", "delivery", "доставка", "возврат"):
        assert forbidden not in low, forbidden


# ============================================================
# Required head tags
# ============================================================

def test_assembled_html_links_inter_and_fraunces_fonts() -> None:
    out = pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE)
    assert "Inter:wght" in out
    assert "Fraunces:ital" in out


def test_assembled_html_includes_reveal_observer_js() -> None:
    out = pb.assemble_page(["hero1"], [_slots_for("hero1")], PALETTE)
    assert "IntersectionObserver" in out
    assert "reveal" in out


def test_render_badges_marks_first_n_solid() -> None:
    html = pb.render_badges(["A", "B", "C", "D"], solid_first=2)
    assert html.count('class="badge solid"') == 2
    assert html.count('class="badge"') == 2  # rest
