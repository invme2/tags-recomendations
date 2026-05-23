"""Migration: extend Designer system prompt with 14 new modules from
Round 5 (safety, protocol, target_profile, video_demo, compatibility,
assembly) and Round 6 (sustainability, brand_story, nutrition_facts,
app_showcase, subscription_refill, clinical_evidence, room_placement,
lifestyle_gallery).

Three injections into Cell 6 _designer_system f-string:
  1. JSON schema examples — before "visual_style"
  2. OPTIONAL MODULES FILL/SKIP rules — after gift_options entry
  3. VARIETY KICKERS pools — after gift_options entry

Source of truth: pipeline/.review/ROUND-5-PIPELINE-NOTES.md +
                 pipeline/.review/ROUND-6-PIPELINE-NOTES.md
"""
from __future__ import annotations
from pathlib import Path
import nbformat

NB = Path("/home/user/tags-recomendations/pipeline/Shopify_Pipeline.ipynb")

# ============================================================
# Injection 1 — JSON schema examples
# Insert BEFORE `"visual_style":` line. Each line follows the existing
# pattern: continuation string concat with \n at end.
# ============================================================
SCHEMA_ANCHOR = '''                '               "ships_with":""}, // For gift intent + sections 2/5/11/10\\n'
                '  "visual_style":"ONE paragraph: unified style for the photo_pack ZIP — bg, light, palette, framing. Applies to ALL photo_briefs.",\\n\''''

SCHEMA_NEW = '''                '               "ships_with":""}, // For gift intent + sections 2/5/11/10\\n'
                # ─── Round 5 module schemas ───
                '  "safety":{"head":{"kicker":"BEFORE YOU START","h2":"","desc":""},\\n'
                '             "age_rating":"",\\n'
                '             "warnings":[{"label":"","detail":""}], // 2-5 warnings\\n'
                '             "contraindications":[""], // 0-4 strings\\n'
                '             "safety_certs":[{"label":"FDA Cleared","sub":""}]}, // FILL: beauty devices, supplements, kids toys, regulated\\n'
                '  "protocol":{"head":{"kicker":"YOUR ROUTINE","h2":"","desc":""},\\n'
                '             "schedule":[{"phase":"Week 1-2","frequency":"3× per week","duration":"10 min","intensity":"Low","note":""}], // 2-5 phases\\n'
                '             "total_commitment":""}, // FILL: beauty devices, supplements, fitness, wellness rituals\\n'
                '  "target_profile":{"head":{"kicker":"WHO IT IS FOR","h2":"","desc":""},\\n'
                '             "ideal_for":[{"label":"","detail":""}], // 3-5 items\\n'
                '             "not_ideal_for":[""], // 0-4 strings\\n'
                '             "fitness_level":"", "skin_type":"", "age_range":""}, // FILL by category-fit\\n'
                '  "video_demo":{"head":{"kicker":"SEE IT IN ACTION","h2":"","desc":""},\\n'
                '             "video":{"source":"youtube|vimeo|direct","id_or_url":"","duration_seconds":0,"thumbnail_url":""},\\n'
                '             "chapters":[{"time":"0:00","label":""}]}, // FILL: fitness/beauty devices/toys/tech demos\\n'
                '  "compatibility":{"head":{"kicker":"WORKS WITH","h2":"","desc":""},\\n'
                '             "platforms":[{"name":"iOS","version":"16.0+","logo_hint":"apple"}], // logo_hint: apple|android|applewatch|bluetooth\\n'
                '             "accessories":[{"name":"","sku":"","fit_note":""}],\\n'
                '             "incompatibility_warnings":[""]}, // FILL: smart home, wearables, tech accessories\\n'
                '  "assembly":{"head":{"kicker":"SETUP","h2":"","desc":""},\\n'
                '             "time_minutes":15,\\n'
                '             "difficulty":"Easy|Moderate|Advanced",\\n'
                '             "person_count":1,\\n'
                '             "tools_required":[{"name":"","included":true,"optional":false}],\\n'
                '             "warnings":[""]}, // FILL: furniture, fitness gear, construction toys\\n'
                # ─── Round 6 module schemas ───
                '  "sustainability":{"head":{"kicker":"GOOD FOR THE PLANET","h2":"","desc":""},\\n'
                '             "certs":[{"label":"Climate Neutral","since":"2024","verifier":"climateneutral.org"}], // 1-5 certs\\n'
                '             "materials":[{"name":"","percent":80,"note":""}], // 1-4 materials\\n'
                '             "carbon_footprint_g":0,\\n'
                '             "recycling":""}, // FILL: eco/ethical positioning. SKIP: pure tech commodity\\n'
                '  "brand_story":{"head":{"kicker":"WHO MADE THIS","h2":"","desc":""},\\n'
                '             "founded":{"year":2018,"city":"","founder":""},\\n'
                '             "mission":"",\\n'
                '             "values":[{"label":"","detail":""}], // 2-4 values\\n'
                '             "founder_quote":{"text":"","author":""},\\n'
                '             "founder_image_url":""}, // FILL: premium positioning, indie/artisan, eco, family-business\\n'
                '  "nutrition_facts":{"head":{"kicker":"WHAT IS IN A SERVING","h2":"","desc":""},\\n'
                '             "serving_size":"1 scoop (32g)",\\n'
                '             "servings_per_container":30,\\n'
                '             "calories":0,\\n'
                '             "macros":[{"label":"Protein","value":"24g","dv_percent":48}], // standard FDA macros\\n'
                '             "highlights":[""], // No added sugar / Gluten-free / etc.\\n'
                '             "allergens":[""]}, // FILL: food, beverages, supplements, protein, snacks\\n'
                '  "app_showcase":{"head":{"kicker":"IN THE APP","h2":"","desc":""},\\n'
                '             "app_name":"",\\n'
                '             "store_links":[{"store":"App Store","url":""},{"store":"Google Play","url":""}],\\n'
                '             "screens":[{"caption":"","image_url":""}], // 3 phone-screen mockups\\n'
                '             "features":[""]}, // 3-5 app feature lines. FILL: smart devices with companion apps\\n'
                '  "subscription_refill":{"head":{"kicker":"NEVER RUN OUT","h2":"","desc":""},\\n'
                '             "lasts_days":60,\\n'
                '             "default_refill_interval_days":60,\\n'
                '             "discount_percent":15,\\n'
                '             "perks":["Skip or cancel anytime","Free shipping always"], // 2-4 perks\\n'
                '             "savings_per_year_usd":0,\\n'
                '             "best_for_buyer_text":""}, // FILL: consumables (skincare, supplements, coffee, pet food)\\n'
                '  "clinical_evidence":{"head":{"kicker":"THE SCIENCE","h2":"","desc":""},\\n'
                '             "claims":[{"stat":"93%","claim":"saw firmer skin after 8 weeks","study_size":"n=42","study_type":"independent clinical","study_year":2024}], // 1-3 claims\\n'
                '             "mechanism":"",\\n'
                '             "disclaimer":"Results may vary. Not a treatment for any medical condition."}, // FILL: beauty devices, supplements, wellness with clinical claims\\n'
                '  "room_placement":{"head":{"kicker":"IN YOUR SPACE","h2":"","desc":""},\\n'
                '             "best_for_rooms":[""], // 2-4 room types\\n'
                '             "scale_photos":[{"image_url":"","caption":""}], // 2 scale-reference photos\\n'
                '             "pairs_well_with":[""]}, // FILL: furniture, lamps, wall decor, rugs, large appliances\\n'
                '  "lifestyle_gallery":{"head":{"kicker":"IN THE WILD","h2":"","desc":""},\\n'
                '             "items":[{"image_url":"","credit":"","caption":"","tall":false}], // 4-5 mood photos. tall:true=2-row grid span\\n'
                '             "footer_text":""}, // FILL: fashion, accessories, candles, decor, wellness — anything aesthetic-driven\\n'
                '  "visual_style":"ONE paragraph: unified style for the photo_pack ZIP — bg, light, palette, framing. Applies to ALL photo_briefs.",\\n\''''

# ============================================================
# Injection 2 — VARIETY KICKERS pools (insert after gift_options line)
# ============================================================
KICKERS_ANCHOR = '''                "- gift_options: GIFT-READY / FOR GIFTING / WRAP IT UP / GIFT NOTES / THE GIFT VERSION\\n"
                "RULE: pick the 2nd, 3rd, or 4th option from each pool more often than the 1st — over batches the\\n"'''

KICKERS_NEW = '''                "- gift_options: GIFT-READY / FOR GIFTING / WRAP IT UP / GIFT NOTES / THE GIFT VERSION\\n"
                "- safety:         BEFORE YOU START / SAFETY FIRST / IMPORTANT / READ THIS / FYI\\n"
                "- protocol:       YOUR ROUTINE / THE REGIMEN / SCHEDULE / HOW OFTEN / THE RHYTHM\\n"
                "- target_profile: WHO IT'S FOR / MADE FOR / IDEAL FOR / IF YOU / FIT CHECK\\n"
                "- video_demo:     SEE IT IN ACTION / WATCH / 30-SECOND DEMO / IN MOTION / IN USE\\n"
                "- compatibility:  WORKS WITH / PAIRS WITH / COMPATIBLE / IN YOUR ECOSYSTEM / SETUP SAVVY\\n"
                "- assembly:       SETUP / OUT OF THE BOX / FROM FLATPACK / READY IN 15 / EASY BUILD\\n"
                "- sustainability: GOOD FOR THE PLANET / MADE RESPONSIBLY / GREENPRINT / PLANET FIRST / OUR FOOTPRINT\\n"
                "- brand_story:    WHO MADE THIS / OUR STORY / SINCE / THE MAKERS / FROM OUR TABLE\\n"
                "- nutrition_facts: WHAT IS IN A SERVING / NUTRITION / FUEL FACTS / ON YOUR PLATE / PER SERVING\\n"
                "- app_showcase:   IN THE APP / TRACK + TUNE / IN YOUR POCKET / CONNECTED / THE COMPANION\\n"
                "- subscription_refill: NEVER RUN OUT / AUTO-REPLENISH / SUBSCRIBE & SAVE / SET IT, FORGET IT / ON A SCHEDULE\\n"
                "- clinical_evidence: THE SCIENCE / PROVEN / TESTED VERIFIED / CLINICAL PROOF / EVIDENCE-BASED\\n"
                "- room_placement: IN YOUR SPACE / MADE TO FIT / WHERE IT LIVES / IN CONTEXT / ROOM READY\\n"
                "- lifestyle_gallery: IN THE WILD / ON REAL PEOPLE / OUT THERE / BY THE COMMUNITY / EVERYDAY\\n"
                "RULE: pick the 2nd, 3rd, or 4th option from each pool more often than the 1st — over batches the\\n"'''

# ============================================================
# Injection 3 — OPTIONAL MODULES FILL/SKIP rules (insert after
# gift_options entry, before "RULE: never fabricate ...")
# ============================================================
FILLSKIP_ANCHOR = '''                "- gift_options: wrap{} + card{} + occasions[]. FILL for: section 2 (gifts-by-recipient), section 11\\n"
                "    (specific events), section 10 (bundle-types), or anything tagged intent:gift. wrap.options 2-3,\\n"
                "    card.examples 2-3 message templates, occasions 3-6 (Birthday, Anniversary, Mother\\u2019s Day, etc.).\\n"
                "    SKIP for: utility products, electronics not typically gifted, B2B-style items.\\n\\n"
                "RULE: never fabricate certs/specs/ingredients. Pull only what VISION ANALYSIS confirmed (packaging text,\\n"'''

FILLSKIP_NEW = '''                "- gift_options: wrap{} + card{} + occasions[]. FILL for: section 2 (gifts-by-recipient), section 11\\n"
                "    (specific events), section 10 (bundle-types), or anything tagged intent:gift. wrap.options 2-3,\\n"
                "    card.examples 2-3 message templates, occasions 3-6 (Birthday, Anniversary, Mother\\u2019s Day, etc.).\\n"
                "    SKIP for: utility products, electronics not typically gifted, B2B-style items.\\n"
                "- safety: warnings + age_rating + contraindications + safety_certs. FILL for: beauty devices (LED,\\n"
                "    microcurrent, RF, IPL), supplements, kids toys (CPSIA / ASTM-F963 age ratings), kitchen appliances\\n"
                "    with sharp/hot parts, fitness equipment with injury risk, anything FDA-regulated.\\n"
                "    SKIP for: fashion accessories, decor, candles, jewelry, clothing.\\n"
                "- protocol: schedule[] of usage phases. Distinct from how_to (one-time setup) and timeline\\n"
                "    (transformation milestones). FILL for: beauty devices (treatment schedule), supplements (dosing\\n"
                "    cycles), fitness (workout program), wellness rituals (daily/weekly rhythm).\\n"
                "    SKIP for: one-time-use products, decor, accessories.\\n"
                "- target_profile: ideal_for + not_ideal_for + category-tag (fitness_level/skin_type/age_range).\\n"
                "    FILL for: fitness (skill level), beauty (skin type/age), supplements (lifestyle goal),\\n"
                "    toys (age range), pet products (species/size).\\n"
                "    SKIP for: broad-appeal commodity, decor, food.\\n"
                "- video_demo: embedded product video (youtube/vimeo/direct).\\n"
                "    FILL for: fitness (form demos), beauty devices (application demos), toys (play patterns),\\n"
                "    tech (UI walkthroughs), kitchen tools (cooking demos).\\n"
                "    SKIP for: apparel, accessories, decor, supplements.\\n"
                "- compatibility: platforms[] + accessories[] + incompatibility_warnings[]. Distinct from\\n"
                "    app_showcase (which is COMPANION-APP). FILL for: phone accessories (iOS/Android), smart home\\n"
                "    (HomeKit/Alexa/Google), fitness wearables, beauty replaceable heads.\\n"
                "    SKIP for: standalone non-tech products.\\n"
                "- assembly: time + tools + difficulty for one-time setup. Distinct from how_to (ongoing usage).\\n"
                "    FILL for: furniture (beds, desks), fitness equipment (foldable bikes, racks), kids construction\\n"
                "    toys, decor requiring mounting.\\n"
                "    SKIP for: ready-to-use products.\\n"
                "- sustainability: certs[] + materials[] + carbon + recycling. Distinct from trust (positive\\n"
                "    press/awards) and safety (cautionary warnings). FILL for: skincare/food with eco claims,\\n"
                "    fashion (recycled fabric, Fair Trade), decor (FSC wood), pet (sustainably sourced).\\n"
                "    SKIP for: pure tech, generic commodity.\\n"
                "- brand_story: COMPANY narrative — founded + mission + values + founder_quote. Distinct from\\n"
                "    story (PRODUCT problem→solution narrative). FILL for: premium positioning, indie/artisan\\n"
                "    products, eco brands, family-business positioning.\\n"
                "    SKIP for: commodity, dropship, unbranded.\\n"
                "- nutrition_facts: FDA-style label box — serving + macros + highlights + allergens.\\n"
                "    FILL for: food, beverages, supplements, protein powders, snacks.\\n"
                "    SKIP for: anything non-edible / non-ingestible.\\n"
                "- app_showcase: app_name + store_links + screens + features. Distinct from compatibility\\n"
                "    (platform support). FILL for: smart home, fitness wearables, beauty devices with apps,\\n"
                "    connected kitchen/sleep/wellness products.\\n"
                "    SKIP for: non-connected products.\\n"
                "- subscription_refill: VISUAL Subscribe & Save messaging — lasts_days + discount + perks.\\n"
                "    Actual subscription commerce logic is operator (Recharge/Skio/Shopify Subscriptions); this\\n"
                "    module just communicates value. FILL for: skincare/supplements/coffee/food/pet food/contact\\n"
                "    lenses — anything refilled.\\n"
                "    SKIP for: one-time-buy products.\\n"
                "- clinical_evidence: scientific claims + mechanism. Distinct from trust (press/awards) and\\n"
                "    safety (warnings). FILL for: beauty devices, supplements, wellness products with clinical\\n"
                "    claims.\\n"
                "    SKIP for: generic / commodity.\\n"
                "- room_placement: visual scale + room-fit. Distinct from dimensions (numbers only).\\n"
                "    FILL for: furniture, lamps, wall decor, mirrors, rugs, large kitchen appliances.\\n"
                "    SKIP for: small / portable items.\\n"
                "- lifestyle_gallery: UGC-mood photography grid. Distinct from story chapter images\\n"
                "    (narrative-anchored). FILL for: fashion, accessories, candles, decor, wellness — anything\\n"
                "    where aesthetic = part of the value.\\n"
                "    SKIP for: utility products.\\n\\n"
                "RULE: never fabricate certs/specs/ingredients. Pull only what VISION ANALYSIS confirmed (packaging text,\\n"'''


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cells = {c.get("id"): c for c in nb.cells if c.cell_type == "code"}
    c6 = cells.get("ce20f070")

    for label, old, new in [
        ("schema injection",     SCHEMA_ANCHOR,    SCHEMA_NEW),
        ("kickers pool",         KICKERS_ANCHOR,   KICKERS_NEW),
        ("FILL/SKIP rules",      FILLSKIP_ANCHOR,  FILLSKIP_NEW),
    ]:
        if old not in c6["source"]:
            print(f"ERR: {label} anchor missing"); return 1
        c6["source"] = c6["source"].replace(old, new, 1)

    nbformat.write(nb, NB)
    print("✅ Designer prompt extended with 14 new modules (schema + kickers + FILL/SKIP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
