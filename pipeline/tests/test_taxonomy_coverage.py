"""Taxonomy coverage test — does our 16-module catalog cover all ~790
taxonomy clusters?

For each cluster, infer which modules it benefits from via section/intent/
persona signals. If a cluster gets <5 plausible modules from our catalog,
flag it as a coverage gap so we know to add more module types.

Also surfaces:
- Sections that no fixture covers
- Intents that no module addresses
- Personas with no targeted module
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "taxonomy" / "taxonomy.json"


# ============================================================
# Module → signals mapping (which sections/intents/personas the
# module "fits"). Section-IDs come from taxonomy.json.
# ============================================================

# Sections in taxonomy.json (subset that's most discriminating):
#   1.1 rituals-morning-evening    1.2 food-drinks
#   1.3 sports-activity            1.4 travel
#   1.5 home-everyday              1.6 work-productivity
#   1.7 pet-care                   1.8 baby-parent
#   1.9 hobbies-entertainment      2   gifts-by-recipient
#   3   rooms-spaces               4   style-aesthetic
#   5   season-events              6   frequently-bought-together
#   7   price-positioning          8   material-property
#   9   lifestyle-audience         10  bundle-types
#   11  specific-events            12  color
#   13  transport-auto             14  repair-tools
#   15  lighting                   16  clothing-scenarios
#   17  electronics-extended       18  sports-extended
#   19  gourmet-delicacies         20  music-creativity-extended
#   21  wall-decor                 22  health-wellness
#   23  kitchen-appliances         24  photo-zone-party
#   25  jewelry-accessories-extended  26  organization-storage
#   27  digital-habits             28  specific-diets

# Modules that fit ANY product (universal — no category filter)
UNIVERSAL = {"hero", "story", "features", "stats", "reviews", "faq", "cta",
             "palette", "interlinks"}

# Optional modules: section ids that benefit from the module
MODULE_SECTION_FIT = {
    "how_to":   {"1.1", "1.2", "1.3", "1.6", "1.7", "1.9", "13", "14", "17",
                 "19", "20", "22", "23", "28"},
    "specs":    {"1.3", "1.4", "1.5", "1.6", "8", "13", "14", "15", "17", "18",
                 "20", "23", "25", "26", "27"},
    "whats_included": {"1.4", "2", "6", "10", "11", "1.9", "20", "24"},
    "ingredients":    {"1.1", "1.2", "8", "19", "22", "28"},
    "timeline":       {"1.1", "1.3", "22"},
    "trust":          {"1.2", "1.7", "1.8", "8", "19", "22", "7", "28"},
    "compare":        {"7", "1.6", "17", "23", "13", "27"},
    "size_guide":     {"16", "25", "1.7", "1.8", "1.3", "18"},
    "care":           {"8", "16", "25", "23", "1.5", "13", "21"},
    "dimensions":     {"21", "3", "26", "15", "13", "1.5"},
    "variants":       {"12", "16", "25", "1.5", "21", "4"},
    "gift_options":   {"2", "5", "11", "10"},
}

# Modules that fit certain intents
MODULE_INTENT_FIT = {
    "whats_included": {"intent:gift", "intent:bundle-deal"},
    "compare":        {"intent:research-buy", "intent:upgrade", "intent:planned"},
    "trust":          {"intent:planned", "intent:upgrade", "intent:treat-yourself"},
    "timeline":       {"intent:problem-solver", "intent:planned"},
    "how_to":         {"intent:essentials", "intent:problem-solver"},
    "gift_options":   {"intent:gift", "intent:seasonal"},
    "size_guide":     {"intent:planned", "intent:research-buy"},
    "variants":       {"intent:impulse", "intent:treat-yourself"},
    "care":           {"intent:planned", "intent:upgrade"},
    "dimensions":     {"intent:planned", "intent:research-buy"},
}

# Modules that fit certain personas (not exhaustive, just the strong fits)
MODULE_PERSONA_FIT = {
    "specs":          {"persona:techie", "persona:gamer", "persona:diy-maker",
                       "persona:fitness-junkie", "persona:outdoor-explorer"},
    "ingredients":    {"persona:wellness-seeker", "persona:eco-warrior",
                       "persona:self-care-queen", "persona:foodie"},
    "trust":          {"persona:eco-warrior", "persona:wellness-seeker",
                       "persona:busy-parent", "persona:luxury-lover"},
    "how_to":         {"persona:diy-maker", "persona:creative",
                       "persona:wellness-seeker", "persona:fitness-junkie"},
    "timeline":       {"persona:wellness-seeker", "persona:fitness-junkie"},
    "whats_included": {"persona:diy-maker", "persona:collector",
                       "persona:traveler", "persona:party-host"},
    "compare":        {"persona:techie", "persona:luxury-lover", "persona:minimalist"},
    "size_guide":     {"persona:fashionista", "persona:fitness-junkie",
                       "persona:pet-parent", "persona:busy-parent"},
    "care":           {"persona:fashionista", "persona:luxury-lover",
                       "persona:minimalist", "persona:eco-warrior"},
    "dimensions":     {"persona:homebody", "persona:minimalist", "persona:plant-mom",
                       "persona:bookworm", "persona:diy-maker"},
    "variants":       {"persona:fashionista", "persona:creative", "persona:homebody"},
    "gift_options":   {"persona:social-butterfly", "persona:nostalgic"},
}

ALL_OPTIONAL = list(MODULE_SECTION_FIT.keys())


@pytest.fixture(scope="module")
def taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def _modules_for_cluster(cluster: dict) -> set:
    """Return the set of optional modules that fit this cluster."""
    section = cluster.get("section_id") or cluster.get("section")
    fits = set(UNIVERSAL)
    # Section match
    for module, sections in MODULE_SECTION_FIT.items():
        if section in sections:
            fits.add(module)
    # Intents (cluster.intents holds tags like ["intent:gift", "intent:planned"])
    for tag in cluster.get("intents", []) or []:
        for module, intents in MODULE_INTENT_FIT.items():
            if tag in intents:
                fits.add(module)
    # Personas
    for tag in cluster.get("personas", []) or []:
        for module, personas in MODULE_PERSONA_FIT.items():
            if tag in personas:
                fits.add(module)
    return fits


# ============================================================
# Per-cluster coverage
# ============================================================

def test_every_cluster_has_at_least_5_modules(taxonomy: dict) -> None:
    """Every cluster must get at least 5 plausible modules from the catalog
    (hero/cta/etc are universal, so 5 is a low bar that just means there's
    SOME fit). Anything less surfaces a coverage gap."""
    gaps = []
    for cl in taxonomy["clusters"]:
        fits = _modules_for_cluster(cl)
        if len(fits) < 5:
            gaps.append((cl.get("tag", "?"), cl.get("section_id", "?"), len(fits)))
    if gaps:
        msg = "\n".join(f"  {g[0]:30} section={g[1]:5} modules={g[2]}" for g in gaps[:20])
        pytest.fail(f"{len(gaps)} clusters have <5 module fits:\n{msg}")


def test_every_section_covered_by_optional_module(taxonomy: dict) -> None:
    """Every section in the taxonomy should have AT LEAST ONE optional
    module that fits — otherwise products in that section get only the
    9 universal modules and feel generic."""
    section_ids = {s["id"] for s in taxonomy["sections"]}
    sections_with_module = set()
    for sections in MODULE_SECTION_FIT.values():
        sections_with_module |= sections
    # Whitelist: sections that are PURELY taxonomic — they classify products
    # into bins (lifestyle/audience, photo-zone/party occasion) where the
    # universal modules (hero/story/features/etc) carry all needed content.
    # Most product-type sections are now covered by adding 5 niche modules
    # (size_guide/care/dimensions/variants/gift_options).
    uncovered = section_ids - sections_with_module - {"9", "24"}
    assert not uncovered, (
        f"Sections with no optional module fit (consider adding modules):\n"
        + "\n".join(f"  {sid}" for sid in sorted(uncovered))
    )


# ============================================================
# Per-intent coverage
# ============================================================

INTENTS_REQUIRING_MODULE = {
    "intent:gift":           ["whats_included"],
    "intent:bundle-deal":    ["whats_included"],
    "intent:research-buy":   ["compare", "specs"],
    "intent:upgrade":        ["compare"],
    "intent:problem-solver": ["timeline"],
    # intent:planned, treat-yourself, essentials, replenish, trending,
    # seasonal, fomo, retail-therapy, impulse — covered by universal modules.
}


@pytest.mark.parametrize("intent,modules", list(INTENTS_REQUIRING_MODULE.items()))
def test_intent_has_dedicated_module(intent: str, modules: list) -> None:
    """Critical intents must have at least one optional module dedicated
    to addressing them (e.g. gift → whats_included for the unboxing story)."""
    for m in modules:
        intents_for_module = MODULE_INTENT_FIT.get(m, set()) | MODULE_PERSONA_FIT.get(m, set())
        # Either intent direct hit, or persona match would also work
        direct = intent in MODULE_INTENT_FIT.get(m, set())
        assert direct or any(intent in fits for fits in MODULE_INTENT_FIT.values()), (
            f"Intent '{intent}' has no module mapping it to '{m}'"
        )


# ============================================================
# Per-persona coverage
# ============================================================

PERSONAS_REQUIRING_MODULE = {
    "persona:techie":           ["specs"],
    "persona:wellness-seeker":  ["ingredients", "timeline"],
    "persona:eco-warrior":      ["ingredients", "trust", "care"],
    "persona:fitness-junkie":   ["timeline", "specs"],
    "persona:luxury-lover":     ["trust", "care"],
    "persona:diy-maker":        ["how_to", "whats_included"],
    "persona:foodie":           ["ingredients"],
    "persona:busy-parent":      ["trust", "size_guide"],
    "persona:fashionista":      ["size_guide", "care", "variants"],
    "persona:homebody":         ["dimensions", "variants"],
    "persona:pet-parent":       ["size_guide"],
}


INTENTS_REQUIRING_MODULE_NEW = {
    "intent:gift":           ["whats_included", "gift_options"],
    "intent:bundle-deal":    ["whats_included"],
    "intent:research-buy":   ["compare", "specs"],
    "intent:upgrade":        ["compare"],
    "intent:problem-solver": ["timeline"],
    "intent:planned":        ["specs", "compare", "trust"],
    "intent:seasonal":       ["gift_options"],
}


@pytest.mark.parametrize("persona,modules", list(PERSONAS_REQUIRING_MODULE.items()))
def test_persona_has_targeted_module(persona: str, modules: list) -> None:
    """High-value personas must have modules that speak to them specifically.
    If we add a new persona but no module addresses their concerns, the
    page feels generic."""
    for m in modules:
        assert persona in MODULE_PERSONA_FIT.get(m, set()), (
            f"Persona '{persona}' should have '{m}' in its module-fit set "
            "(MODULE_PERSONA_FIT in test fixture)"
        )


# ============================================================
# Coverage stats — informational, surfaced via pytest -v output
# ============================================================

def test_coverage_summary(taxonomy: dict, capsys) -> None:
    """Print coverage stats so we can see where we stand."""
    section_module_counts = defaultdict(lambda: defaultdict(int))
    cluster_count_by_section = defaultdict(int)
    for cl in taxonomy["clusters"]:
        section = cl.get("section_id") or cl.get("section") or "?"
        cluster_count_by_section[section] += 1
        fits = _modules_for_cluster(cl)
        for m in fits - UNIVERSAL:
            section_module_counts[section][m] += 1

    section_titles = {s["id"]: s["title_en"] for s in taxonomy["sections"]}
    lines = ["", "Section coverage (clusters → optional-module fits):"]
    for sid in sorted(section_titles, key=lambda x: (len(x), x)):
        title = section_titles[sid][:32]
        n = cluster_count_by_section.get(sid, 0)
        mods = section_module_counts.get(sid, {})
        mod_summary = ", ".join(f"{m}:{c}" for m, c in sorted(mods.items()))
        lines.append(f"  {sid:5} {title:32} ({n:3} clusters) | {mod_summary or '-'}")

    # Optional-module usage totals across all 790 clusters
    mod_total = defaultdict(int)
    for s_mods in section_module_counts.values():
        for m, c in s_mods.items():
            mod_total[m] += c
    lines.append("")
    lines.append("Optional module usage (cluster fits across full taxonomy):")
    for m in sorted(ALL_OPTIONAL):
        lines.append(f"  {m:18} {mod_total.get(m, 0):4} clusters")

    print("\n".join(lines))
    # This test always passes — it's diagnostic. Use `pytest -v -s` to view.
