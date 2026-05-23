"""Migration: apply round 5 + 6 module additions to notebook.
  - Cell 2: insert 14 new metafield tuples before photo_pack admin block
  - Cell 6: replace _wanelo_keys with new 37-entry list (round 6 order)
  - Cell 6: append Designer prompt — JSON schemas + FILL/SKIP + kicker pools
    (operator extends Designer system prompt in a follow-up — for now we
    just verify the metafields are correctly declared; Designer prompt
    text will pick up new modules organically since Designer reads what
    metafields exist).

Designer system prompt is a long inline f-string in Cell 6. Rather than
attempt invasive surgery on it here, we leave it alone — Designer's
JSON output is permissive (it can emit new keys), and the snippets'
skip-if-blank gates will simply hide modules until the operator
manually extends the Designer system prompt with the new schema blocks.

That follow-up is documented in pipeline/.review/ROUND-5-PIPELINE-NOTES.md
and pipeline/.review/ROUND-6-PIPELINE-NOTES.md for operator reference.
"""
from __future__ import annotations
from pathlib import Path
import nbformat

NB = Path("/home/user/tags-recomendations/pipeline/Shopify_Pipeline.ipynb")

# ─────────────────────────────────────────────────────────────────
# Cell 2 — insert 14 new metafield tuples before admin block
# ─────────────────────────────────────────────────────────────────
CELL2_ANCHOR = """        ('gift_options',    'Wanelo · Gift Options',    'Gift wrap + occasions: head + wrap{available,price,options[]} + card{available,examples[]} + occasions[]. For gift intent.'),
        ('photo_pack',      'Wanelo · Photo Pack',      'Admin-only download link (type: url). One click in Admin → opens ZIP with EPROLO photos + prompt.txt for ChatGPT-UI edit workflow. NEVER exposed to storefront.'),"""

CELL2_NEW = """        ('gift_options',    'Wanelo · Gift Options',    'Gift wrap + occasions: head + wrap{available,price,options[]} + card{available,examples[]} + occasions[]. For gift intent.'),
        # ─── Round 5 additions ───
        ('safety',           'Wanelo · Safety',           'Warnings, age rating, contraindications, safety certs. FILL for beauty devices / supplements / kids toys / appliances. {head, age_rating, warnings[{label, detail}], contraindications[], safety_certs[{label, sub}]}'),
        ('protocol',         'Wanelo · Protocol',         'Ongoing usage rhythm — distinct from how_to (setup) and timeline (transformation). FILL for beauty devices / supplements / fitness / wellness rituals. {head, schedule[{phase, frequency, duration, intensity, note}], total_commitment}'),
        ('target_profile',   'Wanelo · Target Profile',   'Who is this for. {head, ideal_for[{glyph, label, detail}], not_ideal_for[], fitness_level, skin_type, age_range}'),
        ('video_demo',       'Wanelo · Video Demo',       'Embedded product video. {head, video{source, id_or_url, duration_seconds, thumbnail_url}, chapters[{time, label}]}'),
        ('compatibility',    'Wanelo · Compatibility',    'Works-with matrix. {head, platforms[{name, version, logo_hint}], accessories[{name, sku, fit_note}], incompatibility_warnings[]}'),
        ('assembly',         'Wanelo · Assembly',         'Setup time + tools. {head, time_minutes, difficulty, person_count, tools_required[{name, included, optional}], warnings[]}'),
        # ─── Round 6 additions ───
        ('sustainability',     'Wanelo · Sustainability',     'Eco/ethical credentials. Distinct from trust (awards) and safety (warnings). {head, certs[{label, since, verifier}], materials[{name, percent, note}], carbon_footprint_g, recycling}'),
        ('brand_story',        'Wanelo · Brand Story',        'COMPANY narrative — origin, founder, values. Distinct from story (PRODUCT narrative). {head, founded{year, city, founder}, mission, values[{label, detail}], founder_quote{text, author}, founder_image_url}'),
        ('nutrition_facts',    'Wanelo · Nutrition Facts',    'FDA-style nutrition label box. {head, serving_size, servings_per_container, calories, macros[{label, value, dv_percent}], highlights[], allergens[]}'),
        ('app_showcase',       'Wanelo · App Showcase',       'Companion app screens + features + store badges. Distinct from compatibility (platform support). {head, app_name, store_links[{store, url}], screens[{caption, image_url}], features[]}'),
        ('subscription_refill','Wanelo · Subscription Refill','Subscribe & Save messaging for consumables. VISUAL only — actual cart logic is operator (Recharge/Skio/Shopify Subscriptions). {head, lasts_days, default_refill_interval_days, discount_percent, perks[], savings_per_year_usd, best_for_buyer_text}'),
        ('clinical_evidence',  'Wanelo · Clinical Evidence',  'Scientific backing for claims. Distinct from trust (press/awards) and safety (warnings). {head, claims[{stat, claim, study_size, study_type, study_year}], mechanism, disclaimer}'),
        ('room_placement',     'Wanelo · Room Placement',     'Visual scale + room-fit for furniture / decor / lighting. Distinct from dimensions (numbers only). {head, best_for_rooms[], scale_photos[{image_url, caption}], pairs_well_with[]}'),
        ('lifestyle_gallery',  'Wanelo · Lifestyle Gallery',  'UGC mood grid for aspirational positioning. Distinct from story images (narrative-anchored). {head, items[{image_url, credit, caption, tall}], footer_text}'),
        # ─── Admin-only ───
        ('photo_pack',      'Wanelo · Photo Pack',      'Admin-only download link (type: url). One click in Admin → opens ZIP with EPROLO photos + prompt.txt for ChatGPT-UI edit workflow. NEVER exposed to storefront.'),"""


# ─────────────────────────────────────────────────────────────────
# Cell 6 — replace _wanelo_keys with round-6 order (37 entries)
# ─────────────────────────────────────────────────────────────────
CELL6_KEYS_ANCHOR = """                    _wanelo_keys = ['hero', 'story', 'features', 'stats', 'reviews',
                                    'faq', 'cta', 'palette', 'interlinks',
                                    'how_to', 'specs', 'whats_included', 'ingredients',
                                    'timeline', 'trust', 'compare',
                                    'size_guide', 'care', 'dimensions', 'variants', 'gift_options',
                                    'photo_pack', 'source']"""

CELL6_KEYS_NEW = """                    # Round-6 order — matches sections/wanelo-product-page.liquid render
                    # sequence. 35 storefront + 2 admin-only = 37 keys total.
                    _wanelo_keys = [
                        # Hero + positioning
                        'hero', 'target_profile', 'brand_story',
                        # Narrative + media
                        'story', 'features', 'video_demo', 'lifestyle_gallery',
                        # Ingredients + usage
                        'ingredients', 'nutrition_facts', 'how_to', 'protocol',
                        'timeline', 'clinical_evidence',
                        # Specs + tech
                        'stats', 'specs', 'compatibility', 'app_showcase',
                        # Fit + form
                        'size_guide', 'dimensions', 'room_placement', 'variants',
                        # Care + box
                        'care', 'whats_included', 'assembly',
                        # Conversion
                        'gift_options', 'subscription_refill', 'compare',
                        # Credentials
                        'trust', 'sustainability', 'safety',
                        # Social + close
                        'reviews', 'faq', 'cta', 'interlinks',
                        # Theme + admin
                        'palette',
                        'photo_pack', 'source',
                    ]"""


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cells = {c.get("id"): c for c in nb.cells if c.cell_type == "code"}

    c2 = cells.get("b810afd7")
    if CELL2_ANCHOR not in c2["source"]:
        print("ERR: Cell 2 anchor missing"); return 1
    c2["source"] = c2["source"].replace(CELL2_ANCHOR, CELL2_NEW, 1)

    c6 = cells.get("ce20f070")
    if CELL6_KEYS_ANCHOR not in c6["source"]:
        print("ERR: Cell 6 _wanelo_keys anchor missing"); return 2
    c6["source"] = c6["source"].replace(CELL6_KEYS_ANCHOR, CELL6_KEYS_NEW, 1)

    nbformat.write(nb, NB)
    print("✅ Notebook updated: +14 metafields, _wanelo_keys=37")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
