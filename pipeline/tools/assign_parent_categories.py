#!/usr/bin/env python3
"""assign_parent_categories.py — give every Shopify collection a PARENT category,
stored in the collection metafield `custom.parent_category`
(single_line_text_field). The storefront silo reads this key to build automatic
internal links:

  * homepage "Shop by category" hubs (wanelo-category-hubs.liquid) — one card per
    distinct parent, with a representative icon, concentrating SEO equity;
  * footer "All collections" directory (wanelo-collections-directory.liquid) —
    every collection grouped under its parent (the HTML-sitemap pattern).

Both render with {% for c in collections %} from the LIVE collections object, so a
newly created collection appears automatically once it has a parent_category. The
Shopify pipeline (Cell 6) sets parent_category on creation using the SAME keyword
logic exported here (PARENT_RULES + parent_for / parent_slug), so the operator
never maintains link lists by hand.

Flow:
  1. OAuth (client_credentials) -> access_token  (same as resume_with_retries).
  2. Page every collection (handle + title).
  3. Keyword-match title/handle -> parent display name (PARENT_RULES, first match
     wins; rules ordered most-specific -> generic). Fallback = "More".
  4. Ensure metafield DEFINITION custom.parent_category exists (idempotent).
  5. metafieldsSet custom.parent_category = parent name for each collection (batched).
  6. Print a collection -> parent table + a parent-grouping summary.

USAGE:
  python pipeline/tools/assign_parent_categories.py --dry-run   # show matches only
  python pipeline/tools/assign_parent_categories.py             # write metafields

Idempotent: re-running just re-writes the same values.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
API_VERSION = "2024-10"
NAMESPACE = "custom"
KEY = "parent_category"

# Fallback parent when nothing matches. Kept generic so a never-seen collection
# still appears in the directory under a sane bucket.
FALLBACK_PARENT = "More"

# ── Keyword -> PARENT category rules. ORDER MATTERS: first matching substring
# wins, so the most specific phrases come first and broad ones last. `any` = list
# of substrings (the lowercased "title handle" string, with '-' turned to ' ', is
# searched). Each parent also names a representative icon key (must exist in
# pipeline/theme_assets/snippets/wanelo-icon.liquid) used on the homepage hub card.
#
# Tuple shape: (parent_display_name, icon_key, [substrings])
PARENT_RULES: list[tuple[str, str, list[str]]] = [
    # ===================== BABY & KIDS =====================
    ("Baby & Kids", "heart", [
        "baby", "infant", "newborn", "toddler", "nursery", "diaper", "stroller",
        "potty", "feeding", "pregnancy", "maternity", "kids", "kid ", "kid's",
        "boys", "boy's", "girls", "girl's", "childrens", "children's", "teen",
        "young adult", "school supplies", "classroom", "parenting",
    ]),
    # ===================== FOOT & LEG CARE =====================
    ("Foot & Leg Care", "foot-care", [
        "foot care", "foot health", "foot scrub", "foot massag", "foot detox",
        "detox foot", "foot pad", "foot patch", "callus", "pedicure", "feet",
        "leg care", "leg massag", "leg slimming", "calf", "thigh",
        "compression sock", "compression", "open toe", "open-toe",
    ]),
    # ===================== JOINT & MUSCLE =====================
    ("Joint & Muscle", "muscle", [
        "joint", "arthritis", "knee", "muscle", "back pain", "neck pain",
        "shoulder pain", "sciatica", "tendon", "cramp", "bee venom",
        "pain relief", "pain patch", "relief patch", "heating pad",
    ]),
    # ===================== MASSAGE & RELAXATION =====================
    ("Massage & Relaxation", "massage", [
        "massage", "massager", "massagers", "massage gun", "massage tool",
        "relaxation", "acupressure", "shiatsu", "foam roller", "spa",
    ]),
    # ===================== SKIN CARE =====================
    ("Skin Care", "skin-care", [
        "skin care", "skincare", "facial", "face care", "face wash", "face mask",
        "moisturizer", "moisturizing", "moisturiz", "hydrating", "serum",
        "essence", "anti-aging", "anti aging", "wrinkle", "acne", "pimple",
        "blemish", "dark spot", "discoloration", "whitening", "brightening",
        "lightening", "scar", "wart", "mole", "skin tag", "cream", "lotion",
        "ointment", "balm", "vision care", "cleansing oil", "eye care",
        "skin treatment", "itch relief", "daily routine", "natural & organic",
        "natural organic",
    ]),
    # ===================== BATH & BODY =====================
    ("Bath & Body", "wave", [
        "bath", "shower", "soap", "body wash", "body scrub", "body care",
        "body lotion", "body oil", "body shaping", "body sculpting", "exfoliat",
        "scrubber", "scrub brush", "towel", "loofah", "bath bomb", "deodorant",
    ]),
    # ===================== HAIR CARE =====================
    ("Hair Care", "wave", [
        "hair", "scalp", "shampoo", "conditioner", "bonnet", "hair towel",
        "hair dry", "hair cap", "wig", "headband", "hair accessor",
    ]),
    # ===================== MAKEUP & NAILS =====================
    ("Makeup & Nails", "palette", [
        "makeup", "cosmetic", "lipstick", "lip gloss", "lip color", "lip care",
        "eyeliner", "eyeshadow", "mascara", "eyelash", "lash", "brow ",
        "concealer", "foundation", "palette", "nail", "manicure", "tattoo",
    ]),
    # ===================== ORAL CARE =====================
    ("Oral Care", "oral-care", [
        "oral care", "oral hygiene", "toothbrush", "toothpaste", "teeth",
        "tooth ", "dental", "denture", "tongue cleaner", "floss", "mouthwash",
    ]),
    # ===================== INTIMATE & SEXUAL WELLNESS =====================
    ("Intimate & Wellness", "womens-intimate", [
        "intimate", "feminine", "vaginal", "ph balanced", "sexual wellness",
        "libido", "testosterone", "male enhancement", "prostate", "breast",
        "butt care", "butt enhancement",
    ]),
    # ===================== SLEEP & WELLNESS =====================
    ("Sleep & Wellness", "sleep-patch", [
        "sleep", "insomnia", "snore", "snoring", "anti-snoring", "wellness",
        "relaxation product", "aromatherapy", "stress relief", "anxiety",
        "meditation", "essential oil",
    ]),
    # ===================== PATCHES & PADS =====================
    ("Patches & Pads", "patch", [
        "patch", "patches", "kinoki", "lifewave", "transdermal",
    ]),
    # ===================== SUPPLEMENTS & VITAMINS =====================
    ("Supplements & Vitamins", "supplement", [
        "supplement", "vitamin", "gummies", "gummy", "probiotic", "collagen",
        "magnesium", "multivitamin", "electrolyte", "dietary", "mineral",
        "capsule", "tablet", "pills", "pill", "drops", "tincture",
        "slimming tea", "detox tea", "slimming", "weight loss", "fat burn",
        "tea", "coffee",
    ]),
    # ===================== HEALTH DEVICES & MONITORS =====================
    ("Health Devices", "monitor", [
        "monitor", "blood pressure", "glucose", "thermometer", "test kit",
        "medical supplies", "medical supply", "first aid", "bandage", "wound",
        "light therapy", "red light", "infrared", "ear care", "ear wax",
        "nasal", "nose care", "throat", "health monitor", "wellness monitor",
        "personal care electronics", "oral care electronics", "health device",
    ]),
    # ===================== MEN'S =====================
    ("Men's", "mens-care", [
        "men's", "mens ", "shaving", "razor", "men ",
    ]),
    # ===================== WOMEN'S FASHION =====================
    ("Women's Fashion", "lips", [
        "women's", "womens", "ladies", "beachwear", "swimwear", "bikini",
        "lingerie", "dress", "skirt", "blouse", "denim", "women ",
    ]),
    # ===================== CLOTHING & SHOES =====================
    ("Clothing & Shoes", "star", [
        "clothing", "apparel", "shoes", "sneakers", "boots", "sandals",
        "loafers", "pumps", "mules", "clogs", "athletic", "t-shirt", "shirt",
        "jacket", "coat", "pants", "uniform", "costume", "ties", "belt",
    ]),
    # ===================== BAGS & JEWELRY =====================
    ("Bags & Jewelry", "star", [
        "bag", "bags", "luggage", "backpack", "wallet", "purse", "handbag",
        "tote", "crossbody", "clutch", "jewelry", "jewellery", "ring ",
        "necklace", "earring", "bracelet", "watch", "smartwatch", "eyewear",
        "sunglasses", "umbrella", "keyring", "keychain",
    ]),
    # ===================== HOME & KITCHEN =====================
    ("Home & Kitchen", "home", [
        "furniture", "home", "kitchen", "cookware", "bakeware", "drinkware",
        "glassware", "appliance", "vacuum", "laundry", "cleaning", "household",
        "decor", "wall art", "storage", "organization", "lighting", "light bulb",
        "bedroom", "living room", "patio", "bathroom", "nursery decor", "candle",
        "refrigerator", "fridge", "fan ", "heater", "air conditioner", "pest",
        "garden", "planter", "plant ", "plants", "seeds", "greenhouse",
        "patio", "outdoor holiday", "canopy", "gazebo", "bedding", "pond",
        "air quality", "holiday & party", "party supplies", "anti vibration",
        "led strip", "lighting",
    ]),
    # ===================== PET SUPPLIES =====================
    ("Pet Supplies", "heart", [
        "pet", "dog ", "cat ", "puppy", "kitten", "bird", "fish ", "reptile",
        "horse", "small animal", "aquarium",
    ]),
    # ===================== TECH & ELECTRONICS =====================
    ("Tech & Electronics", "monitor", [
        "phone", "cell phone", "charger", "power bank", "cable", "adapter",
        "smart home", "smart device", "smart light", "wifi", "networking",
        "doorbell", "camera", "surveillance", "headphone", "earbud", "speaker",
        "electronic", "gadget", "computer", "laptop", "tablet ", "tech",
    ]),
    # ===================== MUSIC & INSTRUMENTS =====================
    ("Music & Instruments", "star", [
        "musical instrument", "guitar", "drum", "percussion", "keyboard",
        "midi", "microphone", "stringed", "brass", "woodwind", "dj equipment",
        "studio recording", "instrument",
    ]),
    # ===================== OFFICE & SCHOOL =====================
    ("Office & School", "star", [
        "office", "school supplies", "writing", "stationery", "desk", "paper",
        "label", "tape", "adhesive", "greeting card", "gift wrap", "craft",
        "crafting", "beading", "packing", "shipping",
    ]),
    # ===================== BOOKS & MEDIA =====================
    ("Books & Media", "star", [
        "book", "books", "media", "literature", "fiction", "comic",
        "graphic novel", "cookbook", "reference", "education", "teaching",
        "audiobook", "magazine",
    ]),
    # ===================== SPORTS & OUTDOORS =====================
    ("Sports & Outdoors", "star", [
        "sports", "outdoor", "fitness", "exercise", "camping", "hiking",
        "fishing", "cycling", "bike", "pool", "hot tub", "adventure",
    ]),
    # ===================== TOOLS & AUTO =====================
    ("Tools & Auto", "star", [
        "hand tool", "power tool", "tools", "welding", "soldering",
        "automotive", "auto ", "car ", "oils & fluids", "maintenance",
        "repair", "hardware", "lighter", "utility tool", "electrical",
        "plumbing", "fastener", "building supplies", "industrial", "abrasive",
        "generator", "battery", "batteries", "power strip", "plug", "outlet",
        "3d printer", "material handling", "lab ", "scientific", "safety",
        "personal protective", "test, measure", "snow removal",
    ]),
    # ===================== FOOD & GROCERY =====================
    ("Food & Grocery", "leaf", [
        "food", "grocery", "snack", "beverage", "wine making", "coffee bean",
    ]),
]


def load_env() -> None:
    load_dotenv(ENV_FILE, override=True)


def get_token() -> tuple[str, str]:
    store = os.environ["SHOPIFY_STORE"]
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"},
        timeout=15,
    )
    r.raise_for_status()
    return store, r.json()["access_token"]


def gql(store: str, token: str, query: str, variables: Optional[dict] = None) -> dict:
    url = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers,
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    return r.json()


def parent_for(title: str, handle: str) -> str:
    """Return the PARENT display name for a collection. Pure keyword logic so the
    pipeline (Cell 6) can import and reuse it on collection creation."""
    hay = f"{title} {handle}".lower().replace("-", " ")
    for parent, _icon, needles in PARENT_RULES:
        for n in needles:
            if n in hay:
                return parent
    return FALLBACK_PARENT


def parent_icon(parent: str) -> str:
    """Representative icon key for a parent display name (for the homepage hub)."""
    for p, icon, _needles in PARENT_RULES:
        if p == parent:
            return icon
    return "generic"


def parent_slug(parent: str) -> str:
    """URL/anchor slug for a parent name (e.g. 'Foot & Leg Care' -> 'foot-leg-care')."""
    s = parent.lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "&", "-", "/", "'"):
            out.append(" ")
    return "-".join("".join(out).split())


def fetch_collections(store: str, token: str) -> list[dict]:
    out, cursor = [], None
    while True:
        r = gql(store, token,
                "query($c:String){collections(first:250, after:$c){"
                "pageInfo{hasNextPage endCursor} "
                "nodes{id handle title productsCount{count}}}}",
                {"c": cursor})
        pg = r["data"]["collections"]
        out.extend(pg["nodes"])
        if not pg["pageInfo"]["hasNextPage"]:
            break
        cursor = pg["pageInfo"]["endCursor"]
    return out


def ensure_definition(store: str, token: str) -> None:
    m = """
    mutation {
      metafieldDefinitionCreate(definition:{
        name:"Parent Category", namespace:"%s", key:"%s",
        type:"single_line_text_field", ownerType:COLLECTION,
        description:"Parent category bucket. Drives the homepage category hubs and the footer All-collections directory (automatic internal linking)."
      }){ createdDefinition{ id } userErrors{ code message } }
    }""" % (NAMESPACE, KEY)
    r = gql(store, token, m)
    errs = r.get("data", {}).get("metafieldDefinitionCreate", {}).get("userErrors", [])
    if errs:
        codes = {e.get("code") for e in errs}
        if codes <= {"TAKEN"}:
            print(f"[def] custom.{KEY} definition already exists — ok.")
        else:
            print(f"[def] userErrors: {errs}")
    else:
        print(f"[def] created custom.{KEY} definition.")


def write_parents(store: str, token: str, rows: list[tuple[str, str]]) -> int:
    """rows = [(collection_gid, parent_name), ...]. Returns count written."""
    m = """
    mutation set($mf:[MetafieldsSetInput!]!){
      metafieldsSet(metafields:$mf){
        metafields{ id key value }
        userErrors{ field message code }
      }
    }"""
    written = 0
    BATCH = 25
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        mfs = [{"ownerId": gid, "namespace": NAMESPACE, "key": KEY,
                "type": "single_line_text_field", "value": parent}
               for gid, parent in chunk]
        r = gql(store, token, m, {"mf": mfs})
        data = r.get("data", {}).get("metafieldsSet", {})
        if r.get("errors"):
            print(f"[write] GraphQL errors: {r['errors']}")
        ue = data.get("userErrors", [])
        if ue:
            print(f"[write] userErrors: {ue[:5]}")
        written += len(data.get("metafields", []) or [])
        time.sleep(0.4)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print matches without writing metafields")
    ap.add_argument("--only-nonempty", action="store_true",
                    help="only assign to collections that have products")
    args = ap.parse_args()

    load_env()
    store, token = get_token()
    cols = fetch_collections(store, token)
    print(f"[collections] fetched {len(cols)}")

    rows, counts = [], {}
    table = []
    for c in cols:
        cnt = (c.get("productsCount") or {}).get("count", 0)
        if args.only_nonempty and cnt == 0:
            continue
        parent = parent_for(c["title"], c["handle"])
        counts[parent] = counts.get(parent, 0) + 1
        rows.append((c["id"], parent))
        table.append((parent, c["handle"], cnt, c["title"]))

    table.sort(key=lambda r: (r[0], r[1]))
    print(f"\n{'PARENT':<24} {'CNT':>4}  HANDLE  ->  TITLE")
    print("-" * 100)
    for parent, handle, cnt, title in table:
        print(f"{parent:<24} {cnt:>4}  {handle}  ->  {title[:46]}")

    print("\n[summary] parent grouping:")
    for parent, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {parent:<24} {n:>4}   (icon: {parent_icon(parent)}, slug: {parent_slug(parent)})")
    fb = counts.get(FALLBACK_PARENT, 0)
    print(f"\n[summary] {len(rows)} collections, {len(counts)} parents, "
          f"{fb} '{FALLBACK_PARENT}' fallback ({100*fb//max(len(rows),1)}%).")

    if args.dry_run:
        print("\n[dry-run] no metafields written.")
        return 0

    ensure_definition(store, token)
    n = write_parents(store, token, rows)
    print(f"\n[done] wrote custom.{KEY} to {n}/{len(rows)} collections.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
