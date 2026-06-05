#!/usr/bin/env python3
"""patch_parent_category.py — wire automatic parent_category assignment into the
pipeline's collection-creation cell (Cell 4 / id=066bb296), so every NEW
collection created by the pipeline auto-gets custom.parent_category. This keeps
the homepage category hubs + footer All-collections directory fully automatic:
the operator never maintains link lists by hand.

The keyword logic MIRRORS pipeline/tools/assign_parent_categories.py
(PARENT_RULES / parent_for). Kept self-contained inside the notebook cell so it
runs in Colab without importing the repo.

Edits cell id=066bb296 (str_replace, each anchor must be unique):
  1. insert _PARENT_RULES + _parent_for() + _set_parent_category() after
     `import shutil`;
  2. call the helper in the CREATED branch (new collection);
  3. call the helper in the FOUND branch (idempotent backfill for existing).

Run notebook_smoke.py afterwards; must stay valid. Snapshot first.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NB = ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
CELL_ID = "066bb296"

HELPER = '''import shutil

# ── Automatic PARENT CATEGORY assignment (mirrors
# pipeline/tools/assign_parent_categories.py) ──────────────────────────────
# Every collection the pipeline creates gets custom.parent_category set by the
# same keyword logic the bulk tool uses, so the homepage category hubs and the
# footer All-collections directory (both rendered from the live `collections`
# object) stay fully automatic — no hand-maintained link lists, ever.
_PARENT_FALLBACK = "More"
_PARENT_RULES = [
    ("Baby & Kids", ["baby", "infant", "newborn", "toddler", "nursery", "diaper",
        "stroller", "potty", "feeding", "pregnancy", "maternity", "kids", "kid ",
        "kid's", "boys", "boy's", "girls", "girl's", "childrens", "children's",
        "teen", "young adult", "school supplies", "classroom", "parenting"]),
    ("Foot & Leg Care", ["foot care", "foot health", "foot scrub", "foot massag",
        "foot detox", "detox foot", "foot pad", "foot patch", "callus",
        "pedicure", "feet", "leg care", "leg massag", "leg slimming", "calf",
        "thigh", "compression sock", "compression", "open toe", "open-toe"]),
    ("Joint & Muscle", ["joint", "arthritis", "knee", "muscle", "back pain",
        "neck pain", "shoulder pain", "sciatica", "tendon", "cramp",
        "bee venom", "pain relief", "pain patch", "relief patch", "heating pad"]),
    ("Massage & Relaxation", ["massage", "massager", "massagers", "massage gun",
        "massage tool", "relaxation", "acupressure", "shiatsu", "foam roller",
        "spa"]),
    ("Skin Care", ["skin care", "skincare", "facial", "face care", "face wash",
        "face mask", "moisturizer", "moisturizing", "moisturiz", "hydrating",
        "serum", "essence", "anti-aging", "anti aging", "wrinkle", "acne",
        "pimple", "blemish", "dark spot", "discoloration", "whitening",
        "brightening", "lightening", "scar", "wart", "mole", "skin tag",
        "cream", "lotion", "ointment", "balm", "vision care", "cleansing oil",
        "eye care", "skin treatment", "itch relief", "daily routine",
        "natural & organic", "natural organic"]),
    ("Bath & Body", ["bath", "shower", "soap", "body wash", "body scrub",
        "body care", "body lotion", "body oil", "body shaping", "body sculpting",
        "exfoliat", "scrubber", "scrub brush", "towel", "loofah", "bath bomb",
        "deodorant"]),
    ("Hair Care", ["hair", "scalp", "shampoo", "conditioner", "bonnet",
        "hair towel", "hair dry", "hair cap", "wig", "headband", "hair accessor"]),
    ("Makeup & Nails", ["makeup", "cosmetic", "lipstick", "lip gloss",
        "lip color", "lip care", "eyeliner", "eyeshadow", "mascara", "eyelash",
        "lash", "brow ", "concealer", "foundation", "palette", "nail",
        "manicure", "tattoo"]),
    ("Oral Care", ["oral care", "oral hygiene", "toothbrush", "toothpaste",
        "teeth", "tooth ", "dental", "denture", "tongue cleaner", "floss",
        "mouthwash"]),
    ("Intimate & Wellness", ["intimate", "feminine", "vaginal", "ph balanced",
        "sexual wellness", "libido", "testosterone", "male enhancement",
        "prostate", "breast", "butt care", "butt enhancement"]),
    ("Sleep & Wellness", ["sleep", "insomnia", "snore", "snoring",
        "anti-snoring", "wellness", "relaxation product", "aromatherapy",
        "stress relief", "anxiety", "meditation", "essential oil"]),
    ("Patches & Pads", ["patch", "patches", "kinoki", "lifewave", "transdermal"]),
    ("Supplements & Vitamins", ["supplement", "vitamin", "gummies", "gummy",
        "probiotic", "collagen", "magnesium", "multivitamin", "electrolyte",
        "dietary", "mineral", "capsule", "tablet", "pills", "pill", "drops",
        "tincture", "slimming tea", "detox tea", "slimming", "weight loss",
        "fat burn", "tea", "coffee"]),
    ("Health Devices", ["monitor", "blood pressure", "glucose", "thermometer",
        "test kit", "medical supplies", "medical supply", "first aid",
        "bandage", "wound", "light therapy", "red light", "infrared",
        "ear care", "ear wax", "nasal", "nose care", "throat",
        "health monitor", "wellness monitor", "personal care electronics",
        "oral care electronics", "health device"]),
    ("Men's", ["men's", "mens ", "shaving", "razor", "men "]),
    ("Women's Fashion", ["women's", "womens", "ladies", "beachwear", "swimwear",
        "bikini", "lingerie", "dress", "skirt", "blouse", "denim", "women "]),
    ("Clothing & Shoes", ["clothing", "apparel", "shoes", "sneakers", "boots",
        "sandals", "loafers", "pumps", "mules", "clogs", "athletic", "t-shirt",
        "shirt", "jacket", "coat", "pants", "uniform", "costume", "ties",
        "belt"]),
    ("Bags & Jewelry", ["bag", "bags", "luggage", "backpack", "wallet", "purse",
        "handbag", "tote", "crossbody", "clutch", "jewelry", "jewellery",
        "ring ", "necklace", "earring", "bracelet", "watch", "smartwatch",
        "eyewear", "sunglasses", "umbrella", "keyring", "keychain"]),
    ("Home & Kitchen", ["furniture", "home", "kitchen", "cookware", "bakeware",
        "drinkware", "glassware", "appliance", "vacuum", "laundry", "cleaning",
        "household", "decor", "wall art", "storage", "organization", "lighting",
        "light bulb", "bedroom", "living room", "patio", "bathroom",
        "nursery decor", "candle", "refrigerator", "fridge", "fan ", "heater",
        "air conditioner", "pest", "garden", "planter", "plant ", "plants",
        "seeds", "greenhouse", "outdoor holiday", "canopy", "gazebo", "bedding",
        "pond", "air quality", "holiday & party", "party supplies",
        "anti vibration", "led strip"]),
    ("Pet Supplies", ["pet", "dog ", "cat ", "puppy", "kitten", "bird",
        "fish ", "reptile", "horse", "small animal", "aquarium"]),
    ("Tech & Electronics", ["phone", "cell phone", "charger", "power bank",
        "cable", "adapter", "smart home", "smart device", "smart light", "wifi",
        "networking", "doorbell", "camera", "surveillance", "headphone",
        "earbud", "speaker", "electronic", "gadget", "computer", "laptop",
        "tablet ", "tech"]),
    ("Music & Instruments", ["musical instrument", "guitar", "drum",
        "percussion", "keyboard", "midi", "microphone", "stringed", "brass",
        "woodwind", "dj equipment", "studio recording", "instrument"]),
    ("Office & School", ["office", "school supplies", "writing", "stationery",
        "desk", "paper", "label", "tape", "adhesive", "greeting card",
        "gift wrap", "craft", "crafting", "beading", "packing", "shipping"]),
    ("Books & Media", ["book", "books", "media", "literature", "fiction",
        "comic", "graphic novel", "cookbook", "reference", "education",
        "teaching", "audiobook", "magazine"]),
    ("Sports & Outdoors", ["sports", "outdoor", "fitness", "exercise",
        "camping", "hiking", "fishing", "cycling", "bike", "pool", "hot tub",
        "adventure"]),
    ("Tools & Auto", ["hand tool", "power tool", "tools", "welding",
        "soldering", "automotive", "auto ", "car ", "oils & fluids",
        "maintenance", "repair", "hardware", "lighter", "utility tool",
        "electrical", "plumbing", "fastener", "building supplies", "industrial",
        "abrasive", "generator", "battery", "batteries", "power strip", "plug",
        "outlet", "3d printer", "material handling", "lab ", "scientific",
        "safety", "personal protective", "test, measure", "snow removal"]),
    ("Food & Grocery", ["food", "grocery", "snack", "beverage", "wine making",
        "coffee bean"]),
]

def _parent_for(title, handle):
    hay = f"{title or ''} {handle or ''}".lower().replace("-", " ")
    for parent, needles in _PARENT_RULES:
        for n in needles:
            if n in hay:
                return parent
    return _PARENT_FALLBACK

async def _set_parent_category(coll_gid, title, handle):
    """Idempotently write custom.parent_category for a collection gid. No-op if
    SHOPIFY_TOKEN is missing or the gid is falsy."""
    if not coll_gid or not SHOPIFY_TOKEN:
        return None
    parent = _parent_for(title, handle)
    try:
        r = await shopify_gql(
            "mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m)"
            "{metafields{id} userErrors{field message code}}}",
            {"m": [{"ownerId": coll_gid, "namespace": "custom",
                    "key": "parent_category", "type": "single_line_text_field",
                    "value": parent}]})
        errs = (((r or {}).get("data", {}) or {}).get("metafieldsSet", {}) or {}).get("userErrors", [])
        if errs:
            print(f"  ⚠ parent_category {handle}: {errs[:1]}")
        return parent
    except Exception as _e_pc:
        print(f"  ⚠ parent_category write failed for {handle}: {str(_e_pc)[:80]}")
        return None'''

CREATED_OLD = """                db.execute('UPDATE collections SET shopify_collection_id=? WHERE id=?', (cid, c['id']))
                db.commit(); created += 1
                print(f'  CREATED: {title[:45]}')"""
CREATED_NEW = """                db.execute('UPDATE collections SET shopify_collection_id=? WHERE id=?', (cid, c['id']))
                db.commit(); created += 1
                _pc = await _set_parent_category(cid, title, handle)
                print(f'  CREATED: {title[:45]}  [parent: {_pc}]')"""

FOUND_OLD = """            db.execute('UPDATE collections SET shopify_collection_id=? WHERE id=?', (coll['id'], c['id']))
            db.commit(); found += 1
            print(f'  FOUND: {title[:45]}')"""
FOUND_NEW = """            db.execute('UPDATE collections SET shopify_collection_id=? WHERE id=?', (coll['id'], c['id']))
            db.commit(); found += 1
            await _set_parent_category(coll['id'], title, handle)
            print(f'  FOUND: {title[:45]}')"""


def main() -> int:
    import nbformat
    nb = nbformat.read(NB, as_version=4)
    cell = next((c for c in nb.cells if c.get("id") == CELL_ID), None)
    if cell is None:
        print(f"cell id {CELL_ID} not found")
        return 1
    src = cell.source

    if "_set_parent_category" in src:
        print("[skip] parent_category helper already present in cell.")
        return 0

    edits = [
        ("import shutil", HELPER),
        (CREATED_OLD, CREATED_NEW),
        (FOUND_OLD, FOUND_NEW),
    ]
    for old, new in edits:
        n = src.count(old)
        if n != 1:
            print(f"[fail] anchor not unique ({n}x): {old[:60]!r}")
            return 1
        src = src.replace(old, new, 1)

    cell.source = src
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("[ok] patched cell 066bb296 with automatic parent_category assignment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
