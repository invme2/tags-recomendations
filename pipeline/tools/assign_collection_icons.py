#!/usr/bin/env python3
"""assign_collection_icons.py — give every Shopify collection a category-
appropriate line-icon, stored in the collection metafield `custom.icon`
(single_line_text_field). The storefront ("Explore more" interlinks +
related-collections + the homepage grid) reads that key and renders the
matching inline SVG via the `wanelo-icon` snippet.

Flow:
  1. OAuth (client_credentials) → access_token  (same as resume_with_retries).
  2. Page every collection (handle + title).
  3. Keyword-match title/handle → best icon key (ICON_RULES, first match wins;
     rules are ordered most-specific → generic). Fallback = "generic".
  4. Ensure metafield DEFINITION custom.icon exists (idempotent).
  5. metafieldsSet custom.icon = key for each collection (batched).
  6. Print a collection → icon table.

USAGE:
  python pipeline/tools/assign_collection_icons.py --dry-run   # show matches only
  python pipeline/tools/assign_collection_icons.py             # write metafields

The icon keys MUST exist in pipeline/theme_assets/snippets/wanelo-icon.liquid.
Unknown keys fall back to the snippet's generic glyph, so a typo is graceful.
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
KEY = "icon"

# ── Keyword → icon rules. ORDER MATTERS: first matching substring wins, so the
# most specific phrases come first and broad ones last. `any` = list of
# substrings (lowercased title+handle is searched). All keys must be defined in
# the wanelo-icon.liquid snippet.
ICON_RULES: list[tuple[str, list[str]]] = [
    # ===== HIGH-PRIORITY operator-named categories (win over broad rules) =====
    ("capsule",          ["body capsule", "joint capsule", "butt care capsule", "vitamin capsule", "capsule"]),
    ("body-oil",         ["body oil", "body oils", "slimming oil", "massage oil"]),
    ("drops",            ["body drop", "body drops", "joint drop", "muscle drop", "slimming drop", "tanning drop"]),
    ("mens-care",        ["men's care", "mens care", "men's wellness", "mens wellness", "men's supplement", "mens supplement"]),
    ("sleep-patch",      ["sleep aid", "sleep patch", "sleep aids", "insomnia"]),
    ("wellness-patch",   ["wellness patch", "wellness patches", "lifewave", "energy enhancer"]),
    ("firming-patch",    ["firming patch", "firming patches"]),
    ("patch",            ["body patch", "body patches"]),
    ("discoloration",    ["body discoloration", "discoloration", "body treatment"]),
    ("slimming-tea",     ["slimming tea", "detox tea", "slimming coffee", "detox slimming"]),
    # ----- foot / leg / compression -----
    ("detox-foot-patch", ["detox foot", "foot detox", "foot patch", "foot pad", "kinoki", "foot pads"]),
    ("compression",      ["compression sock", "open toe compression", "open-toe compression", "compression"]),
    ("foot-care",        ["foot care", "pedicure", "callus", "foot scrub", "foot health", "foot support", "foot massag", "hand & foot", "hand and foot", "feet"]),
    ("leg-care",         ["leg care", "leg massag", "calf", "leg slimming", "leg & thigh", "thigh"]),
    # ----- joint / muscle / massage -----
    ("joint-cream",      ["joint cream", "joint relief cream", "muscle rub", "joint gel", "joint care gel", "joint relief gel", "joint spray", "bee venom"]),
    ("joint-care",       ["joint care", "joint relief", "arthritis", "joint capsule", "joint patch", "joint pain", "joint drop", "knee brace", "knee", "joint massager", "joint"]),
    ("muscle",           ["muscle massager", "muscle care", "muscle pain", "muscle supplement", "muscle rub", "muscle", "massage gun", "massagers", "massager"]),
    ("massage",          ["massage cream", "massage oil", "massage therapy", "massage", "heated massage", "heating pad", "neck massager"]),
    # ----- patches -----
    ("sleep-patch",      ["sleep patch"]),
    ("firming-patch",    ["firming patch", "firming patches"]),
    ("wellness-patch",   ["wellness patch", "lifewave", "energy enhancer"]),
    ("care-patch",       ["care patch", "frownies", "facial patch", "forehead patch", "skincare patch", "wrinkle patch"]),
    ("patch",            ["body patch", "pain relief patch", "relief patch", "weight loss patch", "slimming patch", "hangover", "anti-snoring patch", "throat", "patch", "patches"]),
    # ----- wart / mole / skin-tag / discoloration -----
    ("wart-removal",     ["wart removal", "wart", "corn care"]),
    ("mole-removal",     ["mole removal", "mole", "skin tag", "blemish removal", "dark spot", "tattoo", "ink removal", "freckle"]),
    ("discoloration",    ["discoloration", "skin whitening", "skin brightening", "lightening", "whitening", "glutathione", "tanning", "bronz", "tan face"]),
    # ----- breast / intimate / prostate -----
    ("breast-care",      ["breast care", "breast enhancement", "breast enlargement", "breast"]),
    ("womens-intimate",  ["women's intimate", "womens intimate", "feminine hygiene", "feminine", "ph balanced", "vaginal"]),
    ("mens-intimate",    ["men's intimate", "mens intimate", "male enhancement", "men's enhancement", "mens enhancement", "libido", "testosterone", "butt enhancement", "butt care", "maca"]),
    ("prostate",         ["prostate", "enlarged prostate"]),
    # ----- ear / nasal / nose / eye / throat / oral -----
    ("ear-care",         ["ear care", "earache", "ear wax", "ear candle", "ear corrector", "ear"]),
    ("nasal-care",       ["nasal", "aspirator", "nose care", "nose ", "congestion", "decongestant", "snore", "snoring"]),
    ("eye-drops",        ["eye drop", "eye drops"]),
    ("throat-care",      ["throat", "sore throat"]),
    ("oral-care",        ["oral care", "oral hygiene", "toothbrush", "teeth whitening", "dental", "denture", "teeth", "tooth"]),
    # ----- pimple / acne / scar / serum -----
    ("pimple",           ["pimple patch", "acne patch", "acne pimple", "pimple", "acne"]),
    ("serum",            ["serum", "essence", "facial essence", "skin essence"]),
    # ----- nails -----
    ("nail-care",        ["nail care", "nail repair", "nail extension", "press-on nail", "press on nail", "gel nail", "nail polish", "nail art", "manicure", "nail"]),
    # ----- devices / monitors / first-aid / jewelry -----
    ("light-therapy",    ["light therapy", "laser therapy", "red light", "led red light", "infrared"]),
    ("monitor",          ["health monitor", "blood pressure", "glucose", "thermometer", "test kit", "monitor"]),
    ("bandage",          ["bandage", "band-aid", "band aid", "wound care", "first aid", "anti-choking", "rescue device"]),
    ("bracelet",         ["bracelet", "medical alert", "magnetic ring", "wellness ring", "smart ring", "health ring"]),
    # ----- face / skin / moisturizer / lotion / cream -----
    ("face-care",        ["face & body moisturizer", "facial skincare", "facial care", "face primer", "facial cleanser", "facial gel", "facial mist", "facial steamer", "facial device", "face wash", "face moistur", "face lifting", "facial"]),
    ("moisturizer",      ["moisturizer", "moisturizing", "moistur", "hydrating", "face & body", "skin soothing"]),
    ("lotion",           ["body lotion", "lotion"]),
    ("cream",            ["body cream", "skin cream", "scar cream", "repair cream", "firming cream", "skin repair", "herbal cream", "herbal balm", "herbal ointment", "cream", "ointment", "balm"]),
    ("chest-care",       ["chest care", "chest tightness", "chest"]),
    ("body-care",        ["body care", "body treatment", "body powder", "body scrub", "body cleanser", "body shaping", "body sculpting", "body firming", "body slimming", "body shaper", "body"]),
    ("skin-care",        ["skin care", "skincare", "skin treatment", "skin therapy", "skin", "anti-aging", "anti aging", "daily routine", "morning routine", "routine"]),
    # ----- oils / spray / shower / mens -----
    ("body-oil",         ["body oil", "essential oil", "massage oil", "facial oil", "rose oil", "slimming oil", "cleansing oil", "hair oil", "scalp oil", "oil"]),
    ("spray",            ["body spray", "deodorant spray", "skin spray", "magnesium spray", "nasal spray", "joint spray", "spray", "mist"]),
    ("shower",           ["shower gel", "shower", "bath ", "bathroom", "soap", "cleanser", "body wash", "exfoliat", "scrubber"]),
    ("mens-care",        ["men's care", "mens care", "men's wellness", "mens wellness", "men's supplement", "mens supplement", "shaving"]),
    # ----- tea / drops / capsules / supplements -----
    ("slimming-tea",     ["slimming tea", "detox tea", "slimming coffee", "slimming"]),
    ("tea",              ["tea", "collagen tea", "herbal tea", "prostate tea", "wellness tea", "coffee"]),
    ("drops",            ["body drop", "joint drop", "muscle drop", "slimming drop", "tanning drop", "digestive drop", "liver detox drop", "drops", "drop"]),
    ("capsule",          ["body capsule", "body care capsule", "capsule", "capsules"]),
    ("supplement",       ["supplement", "vitamin", "gummies", "gummy", "probiotic", "collagen", "magnesium", "multivitamin", "electrolyte", "energy", "dietary", "mineral", "drink powder", "pills", "pill"]),
    # ----- wellness / detox / sleep / patches misc -----
    ("sleep-patch",      ["sleep aid", "sleep", "insomnia", "magnesium spray"]),
    ("detox-foot-patch", ["detox", "liver detox", "lymphatic"]),
    ("wellness-patch",   ["wellness bracelet", "wellness ring", "wellness", "anion"]),
    # ----- makeup / skincare legacy short keys -----
    ("lipstick",         ["lipstick", "lip color"]),
    ("lips",             ["lip care", "lip gloss", "lip "]),
    ("eye",              ["eyeliner", "eyeshadow", "eyelash", "lash", "brow", "eye care", "eye ", "vision", "mascara"]),
    ("palette",          ["makeup kit", "makeup tools", "makeup", "palette", "cosmetic", "concealer", "freckle sticker", "flash tattoo"]),
    ("leaf",             ["natural", "organic", "herbal", "aromatherapy", "essential", "plant"]),
    ("wave",             ["hair care", "haircare", "hair oil", "hair", "scalp", "bath", "bonnet", "towel"]),
    ("star",             ["best seller", "dental kit", "top "]),
    ("drop",             ["serum", "essence", "moistur"]),
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


def match_icon(title: str, handle: str) -> str:
    hay = f"{title} {handle}".lower().replace("-", " ")
    for icon, needles in ICON_RULES:
        for n in needles:
            if n in hay:
                return icon
    return "generic"


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
        name:"Icon", namespace:"%s", key:"%s",
        type:"single_line_text_field", ownerType:COLLECTION,
        description:"Line-icon key rendered by the wanelo-icon snippet."
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


def write_icons(store: str, token: str, rows: list[tuple[str, str]]) -> int:
    """rows = [(collection_gid, icon_key), ...]. Returns count written."""
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
                "type": "single_line_text_field", "value": icon}
               for gid, icon in chunk]
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
                    help="only assign icons to collections that have products")
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
        icon = match_icon(c["title"], c["handle"])
        counts[icon] = counts.get(icon, 0) + 1
        rows.append((c["id"], icon))
        table.append((c["handle"], cnt, icon, c["title"]))

    table.sort(key=lambda r: (r[2], r[0]))
    print(f"\n{'ICON':<18} {'CNT':>4}  HANDLE  ->  TITLE")
    print("-" * 92)
    for handle, cnt, icon, title in table:
        print(f"{icon:<18} {cnt:>4}  {handle}  ->  {title[:48]}")

    print("\n[summary] icon usage:")
    for icon, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {icon:<18} {n}")
    generic = counts.get("generic", 0)
    print(f"\n[summary] {len(rows)} collections, "
          f"{generic} generic-fallback ({100*generic//max(len(rows),1)}%).")

    if args.dry_run:
        print("\n[dry-run] no metafields written.")
        return 0

    ensure_definition(store, token)
    n = write_icons(store, token, rows)
    print(f"\n[done] wrote custom.{KEY} to {n}/{len(rows)} collections.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
