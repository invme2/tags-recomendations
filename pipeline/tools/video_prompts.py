#!/usr/bin/env python3
"""video_prompts.py — RICH varied prompt builder for the Marketing Studio video
pipeline. Goal: STOP the "every product video looks the same" problem.

Two layers of variety:
  1. Large rotating pools per preset (scenes, camera moves, reviewer personas,
     props, angles) — every slot draws from a deep list.
  2. A per-PRODUCT seed offset, so two different products do NOT get the same
     scene on the same slot. Previously rotation was by video-index only, so
     every product's index-0 clip used scene[0] — identical pattern catalog-wide.
     Now build_prompt(preset, product, index) mixes the product hash in, giving
     each product its own scene sequence while staying deterministic.

Operator rules:
  - Storefront is LIGHT: NEVER a black/dark/moody background (enforced by LIGHT_BG).
  - No "Unboxing" (model invents box contents).
  - Standard 8-comp: index0 Hyper Motion (top), UGC, Product Review, Hyper Motion,
    UGC, TV Spot, UGC, Wild Card.
"""
from __future__ import annotations
import hashlib

LIGHT_BG = ("Bright light background only — white / pastel / airy daylight. "
            "ABSOLUTELY NO black, dark, or moody studio background.")

# ── Scene pools (all LIGHT) — deep enough that index+product offset rarely repeats ──
SHOWCASE_SCENES = [
    "on bright white marble in warm morning daylight with fresh green eucalyptus and a soft folded towel, airy minimalist lifestyle scene",
    "on a soft pastel gradient backdrop (blush to cream), bright clean set with diffused soft light and gentle shadows",
    "on a sunlit bathroom shelf beside neatly arranged skincare bottles and a small plant, bright real lifestyle setting",
    "on a sleek light-wood surface with shallow water ripples and soft caustic reflections, calm bright spa atmosphere in daylight",
    "on a warm beige textured stone with dried flowers and linen, editorial flat-lay energy, soft natural light",
    "floating in a bright airy white space with subtle warm-pastel gradient light and soft bokeh, premium minimalist look",
    "in a sunlit lived-in bedroom corner on a light nightstand with fresh flowers, soft morning light",
    "on a clean cream-and-sand seamless backdrop with soft window light and gentle long shadows, bright editorial look",
    "on frosted pale-blue glass with floating soft light reflections and tiny dewdrops, fresh and clinical-bright",
    "on a pale terracotta tray with citrus slices and sprigs of rosemary, sunlit mediterranean morning vibe",
    "on a soft ribbed-ceramic pedestal in a bright gallery niche with a single pastel spotlight, museum-clean",
    "on rippling silk fabric in champagne and cream tones with airy backlight, luxe soft-focus motion",
]
UGC_SCENES = [
    "a bright modern bathroom, natural daylight",
    "a cozy living-room couch with a throw blanket, warm lamp glow",
    "a sunlit bedroom vanity in the morning",
    "a kitchen counter with coffee, casual morning vibe",
    "a get-ready-with-me moment near a big window",
    "a bright car-seat selfie in daytime, on-the-go energy",
    "a tidy desk with a ring light, casual creator setup",
    "a balcony with plants and soft afternoon sun",
    "a hotel-room mirror during a trip, fresh daylight",
    "a gym-bag flat-lay moment in a bright locker area",
]
REVIEW_SCENES = [
    "a bright kitchen table with the product and its box in soft daylight",
    "a clean home-office desk with a notebook, honest desk-review setup",
    "a sunlit living room, casual sit-down talking-to-camera review",
    "a bathroom counter mid-routine, real-use review angle",
    "a bright dining nook with the product held up to the lens",
    "a cozy reading chair by a window, relaxed candid review",
    "a tidy vanity with good ring-light, beauty-reviewer setup",
    "a kitchen island with morning light, before/after comparison on the counter",
]
REVIEWERS = [
    "a warm 30s woman with relatable everyday energy",
    "a skeptical-but-won-over man in his 40s",
    "an enthusiastic Gen-Z creator with quick cuts",
    "a calm, detail-oriented reviewer comparing it to alternatives",
    "a busy parent giving a real-life honest take",
    "a soft-spoken wellness-focused reviewer",
    "a no-nonsense practical reviewer listing pros and cons",
]
TV_SCENES = [
    "a warm cinematic home setting with soft window light, aspirational lifestyle",
    "an elegant marble vanity with golden-hour glow, premium beauty-brand mood",
    "a calm minimalist room with soft volumetric light and gentle steam",
    "a bright airy loft with sheer curtains billowing in daylight",
    "a sunlit spa retreat with pale stone and trickling water, serene luxury",
    "a pastel pop-art set with clean graphic blocks and bright even light",
    "a fresh garden terrace at midday with greenery and soft bloom",
]
WILD_SCENES = [
    "a surreal bright pastel dreamscape with floating soft-light particles, airy and luminous",
    "a clean bright white set with soft color-shifting pastel gradient light and gentle haze",
    "an editorial scene with a bright single-color (pastel) backdrop and soft graphic shadows",
    "a playful zero-gravity float of the product among pastel clouds, luminous",
    "a kaleidoscopic bright mirror set with soft prismatic light, hypnotic and clean",
    "a giant-scale macro world where the product towers over tiny pastel props, whimsical bright",
    "a liquid-splash freeze-frame in milky pastel tones, crisp and bright",
]
CAMERA_MOVES = [
    "slow orbit", "smooth push-in", "crisp top-down reveal", "gentle parallax dolly",
    "snappy whip-pan transition", "floating crane lift", "macro rack-focus pull",
]
COMPOSITIONS = [
    "centered hero framing", "rule-of-thirds off-center", "dynamic low angle",
    "overhead flat-lay", "close macro detail then pull wide", "diagonal energetic tilt",
]


def _seed(product: str) -> int:
    return int(hashlib.md5((product or "x").encode("utf-8")).hexdigest(), 16)


def _pick(seq, i, product, salt=0):
    """Rotate by video index + product hash + salt, so products differ per slot."""
    return seq[(i + _seed(product) + salt) % len(seq)]


def build_prompt(preset: str, product: str, index: int = 0) -> str:
    """Varied prompt for preset + product. Scene/camera/composition all rotate by
    (index + product-hash) so no two products repeat the same look on a slot."""
    p = product
    cam = _pick(CAMERA_MOVES, index, p, salt=3)
    comp = _pick(COMPOSITIONS, index, p, salt=7)

    if preset == "Hyper Motion":
        scene = _pick(SHOWCASE_SCENES, index, p)
        base = (f"Dynamic product showcase of the {p}, {scene}. {cam.capitalize()} with "
                f"{comp}, glossy reflections, premium daylight. No people.")
    elif preset == "UGC":
        scene = _pick(UGC_SCENES, index, p)
        base = (f"Authentic UGC selfie-style video of a real person using the {p} in {scene}. "
                f"Casual handheld phone look ({comp}), natural daylight, realistic, unscripted.")
    elif preset == "Product Review":
        scene = _pick(REVIEW_SCENES, index, p)
        who = _pick(REVIEWERS, index, p, salt=5)
        base = (f"Honest product-review video with {who} in {scene}, demonstrating the {p} "
                f"and pointing out features one by one, {comp}, trustworthy real-home energy.")
    elif preset == "TV Spot":
        scene = _pick(TV_SCENES, index, p)
        base = (f"Polished commercial-style spot for the {p} in {scene}, {cam}, "
                f"warm bright color grade, product-focused. Avoid explicit skin close-ups.")
    elif preset == "Wild Card":
        scene = _pick(WILD_SCENES, index, p)
        base = (f"Creative scroll-stopping ad for the {p} in {scene}, {cam} with {comp}, "
                f"premium and eye-catching, unexpected angle.")
    else:
        base = f"Marketing video for the {p}, bright lifestyle setting, {comp}."
    return base + " " + LIGHT_BG


if __name__ == "__main__":
    presets = ["Hyper Motion", "UGC", "Product Review", "Hyper Motion",
               "UGC", "TV Spot", "UGC", "Wild Card"]
    for prod in ["7-Color LED Device", "Heated Leg Massager", "Bee Venom Joint Cream"]:
        print(f"\n== {prod} ==")
        for i, preset in enumerate(presets):
            print(f"  [{i}] {preset}: {build_prompt(preset, prod, i)[:110]}...")
