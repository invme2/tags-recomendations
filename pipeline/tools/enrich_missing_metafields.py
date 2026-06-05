#!/usr/bin/env python3
"""enrich_missing_metafields.py — fill in metafield sections that Designer
skipped on a per-product basis, so each product has richer page content
instead of the same 15-section template.

Workflow per product:
  1. Pull existing custom.* metafields from Shopify (to know what's already there)
  2. Determine category-appropriate missing sections (curated allowlist per type)
  3. Call Sonnet with:
       - scrape data (from run DB)
       - existing sections as STYLE REFERENCE
       - the list of sections to FILL
     Sonnet returns JSON with only the new sections, in matching voice/tone.
  4. metafieldsSet → push only the new keys to Shopify
  5. Print a per-product summary

Cost: ~$0.10-0.15 per product in Sonnet calls. Idempotent — re-running
skips sections that now exist.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import anthropic
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
DB_PATH = REPO_ROOT / "runs" / "beauty-rerun-10" / ".db" / "pipeline.db"

API_VERSION = "2024-10"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8000

# NEW SECTIONS — these 4 are conversion-focused additions applicable to
# EVERY product regardless of category. We always try to fill them in
# addition to category-specific sections.
NEW_UNIVERSAL = [
    "unboxing_journey",
    "progress_milestones",
    "mistake_warnings",
    "use_scenarios",
]

# Category → relevant metafield sections to fill (in addition to whatever
# already exists). Designer's FILL/SKIP defaults were too conservative —
# this maps product-type substrings to richer category-appropriate sections.
# The NEW_UNIVERSAL sections are appended automatically for every product.
CATEGORY_SECTIONS = {
    # Skincare / serum / cleanser
    "skin": ["clinical_evidence", "protocol", "target_profile", "brand_story",
             "lifestyle_gallery", "sustainability", "safety", "subscription_refill"],
    "cleansing": ["protocol", "safety", "target_profile", "brand_story",
                  "lifestyle_gallery", "sustainability", "subscription_refill"],
    "facial": ["protocol", "clinical_evidence", "target_profile", "brand_story",
               "lifestyle_gallery", "sustainability", "safety"],
    "anti-aging": ["clinical_evidence", "protocol", "target_profile",
                   "brand_story", "lifestyle_gallery", "sustainability",
                   "safety", "subscription_refill", "app_showcase"],
    # Makeup / beauty / glitter
    "makeup": ["target_profile", "brand_story", "lifestyle_gallery",
               "gift_options", "care", "compare"],
    "glitter": ["target_profile", "brand_story", "lifestyle_gallery",
                "care", "sustainability", "ingredients"],
    "body": ["target_profile", "brand_story", "lifestyle_gallery",
             "care", "sustainability", "safety", "ingredients"],
    "face": ["target_profile", "brand_story", "lifestyle_gallery",
             "gift_options", "care", "compare"],
    # Dental
    "teeth": ["clinical_evidence", "protocol", "safety", "target_profile",
              "brand_story", "lifestyle_gallery"],
    "oral": ["clinical_evidence", "protocol", "safety", "target_profile",
             "brand_story", "lifestyle_gallery"],
    # Default fallback
    "_": ["target_profile", "brand_story", "lifestyle_gallery", "gift_options"],
}

# Schemas for sections we'll ask Sonnet to fill. Keeps output predictable
# and matches what the Liquid snippets already expect.
SECTION_SCHEMAS = {
    "target_profile": {
        "head": {"kicker": "WHO IT'S FOR", "h2": "string"},
        "personas": [{"name": "string", "description": "string",
                      "pain_points": ["string"]}]
    },
    "brand_story": {
        "head": {"kicker": "THE STORY", "h2": "string"},
        "chapters": [{"h3": "string", "body": "string"}]
    },
    "lifestyle_gallery": {
        "head": {"kicker": "IN REAL LIFE", "h2": "string"},
        "items": [{"caption": "string", "context": "string"}]
    },
    "clinical_evidence": {
        "head": {"kicker": "BACKED BY DERMATOLOGY", "h2": "string"},
        "studies": [{"finding": "string", "context": "string"}]
    },
    "protocol": {
        "head": {"kicker": "THE PROTOCOL", "h2": "string"},
        "phases": [{"phase": "string", "duration": "string", "what": "string"}]
    },
    "safety": {
        "head": {"kicker": "SAFETY FIRST", "h2": "string"},
        "items": [{"label": "string", "detail": "string"}]
    },
    "sustainability": {
        "head": {"kicker": "BETTER FOR THE PLANET", "h2": "string"},
        "items": [{"label": "string", "detail": "string"}]
    },
    "subscription_refill": {
        "head": {"kicker": "NEVER RUN OUT", "h2": "string"},
        "pitch": "string",
        "intervals": [{"label": "string", "discount": "string"}]
    },
    "gift_options": {
        "head": {"kicker": "GIFT-READY", "h2": "string"},
        "options": [{"label": "string", "detail": "string"}]
    },
    "care": {
        "head": {"kicker": "CARE & STORAGE", "h2": "string"},
        "items": [{"label": "string", "detail": "string"}]
    },
    "compare": {
        "head": {"kicker": "VS THE ALTERNATIVES", "h2": "string"},
        "rows": [{"feature": "string", "this": "string", "alt1": "string",
                  "alt2": "string"}],
        "alt1_label": "string", "alt2_label": "string"
    },
    "app_showcase": {
        "head": {"kicker": "TRACK YOUR ROUTINE", "h2": "string"},
        "screens": [{"label": "string", "what": "string"}]
    },
    "ingredients": {
        "head": {"kicker": "WHAT'S INSIDE", "h2": "string"},
        "items": [{"name": "string", "purpose": "string", "dose": "string"}]
    },
    # NEW conversion-focused universal sections
    "unboxing_journey": {
        "head": {"kicker": "WHAT YOU'LL OPEN", "h2": "string"},
        "steps": [{"step_number": "int", "title": "string",
                   "description": "string"}]
    },
    "progress_milestones": {
        "head": {"kicker": "YOUR JOURNEY", "h2": "string"},
        "milestones": [{"timeframe": "string (e.g. Day 1 / Week 1 / Week 4 / Week 8)",
                        "label": "string", "expected_result": "string"}]
    },
    "mistake_warnings": {
        "head": {"kicker": "DON'T DO THIS", "h2": "string"},
        "warnings": [{"mistake": "string", "why_problem": "string",
                      "instead_do": "string"}]
    },
    "use_scenarios": {
        "head": {"kicker": "WHEN TO REACH FOR IT", "h2": "string"},
        "scenarios": [{"scenario": "string", "when": "string",
                       "how_to_use": "string", "key_benefit": "string"}]
    },
}


def load_env() -> None:
    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)


def get_shopify_token() -> tuple[str, str]:
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
                      json={"query": query, "variables": variables or {}},
                      timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_product_metafields(store: str, token: str, product_id: str) -> Dict[str, dict]:
    """Return {key: parsed_value} for all custom.* JSON metafields of the product."""
    q = """
    query($id: ID!) {
      product(id: $id) {
        id handle productType title
        metafields(first: 50, namespace: "custom") {
          edges { node { key type value } }
        }
      }
    }
    """
    r = gql(store, token, q, {"id": product_id})
    p = r.get("data", {}).get("product") or {}
    mfs = {}
    for e in p.get("metafields", {}).get("edges", []):
        n = e["node"]
        if n.get("type") == "json" and n.get("value"):
            try:
                mfs[n["key"]] = json.loads(n["value"])
            except Exception:
                pass
    return {"handle": p.get("handle"), "title": p.get("title"),
            "product_type": p.get("productType"), "sections": mfs}


def pick_sections_for(product_type: str, existing: set[str]) -> List[str]:
    """Return list of sections to fill — matches category, excludes already-existing."""
    pt = (product_type or "").lower()
    picks: List[str] = []
    for keyword, sections in CATEGORY_SECTIONS.items():
        if keyword in pt or keyword == "_":
            picks.extend(sections)
            if keyword != "_":
                break  # first match wins, fallback only if no match
    if not picks:
        picks = CATEGORY_SECTIONS["_"]
    # Always try the 4 NEW universal conversion-focused sections, regardless of category
    picks = picks + NEW_UNIVERSAL
    # de-dup + exclude existing
    return [s for s in dict.fromkeys(picks) if s not in existing]


def build_prompt(product_title: str, product_type: str, scrape: dict,
                 strategy: dict, existing: Dict[str, dict],
                 to_fill: List[str]) -> str:
    style_ref = {k: v for k, v in existing.items()
                 if k in ("hero", "story", "features", "stats") and v}
    schemas = {k: SECTION_SCHEMAS[k] for k in to_fill if k in SECTION_SCHEMAS}
    voice = (strategy or {}).get("voice", "warm-confidant")
    positioning = (strategy or {}).get("positioning", "")
    selling_idea = (strategy or {}).get("selling_idea", "")
    pain_point = (strategy or {}).get("pain_point", "")
    transformation = (strategy or {}).get("transformation", "")
    return f"""You are enriching a product page that already has some metafield sections.
Your job: write NEW JSON sections (listed below) in the EXACT same voice + style.

PRODUCT
  Title: {product_title}
  Type:  {product_type}
  Voice: {voice}
  Positioning: {positioning}
  Selling idea: {selling_idea}
  Pain point: {pain_point}
  Transformation: {transformation}

EXISTING SECTIONS (style reference — match this voice + density)
{json.dumps(style_ref, ensure_ascii=False, indent=2)}

SCRAPE (source of truth for product specifics, packaging text, etc.)
{json.dumps({k: v for k, v in scrape.items() if k in ('title', 'description', 'specs')}, ensure_ascii=False, indent=2)[:3000]}

SECTIONS TO FILL (schemas below — emit each exactly per schema)
{json.dumps(schemas, ensure_ascii=False, indent=2)}

RULES
  - ONLY return JSON. No prose, no markdown fences, no commentary.
  - Output shape: a single JSON object with keys = section names above.
  - If you genuinely cannot fill a section for this product (e.g.
    clinical_evidence for a glitter sticker), OMIT that key entirely
    rather than emit empty/fake content.
  - Match the existing voice — if it's casual & punchy, stay there; if
    it's clinical & precise, stay there.
  - For STATS / CLAIMS: ONLY use facts visible in the scrape or
    existing sections. NEVER invent percentages, certifications,
    clinical trial citations.
  - Brand_story.chapters: 2-3 chapters, 50-80 words each, narrative.
  - Lifestyle_gallery.items: 3-4 items, each a specific scene/context.
  - Target_profile.personas: 2-3 personas, named + 2-3 pain points each.
  - Protocol.phases: 3-4 phases with realistic timing.
  - Safety.items: 3-5 items, factual.
  - Sustainability: ONLY if there's a real angle (refillable, vegan,
    cruelty-free, recyclable packaging). If not, omit.
  - Compare.rows: pick a real competitor category, not made-up brand
    names. 3-5 rows of features.
  - Unboxing_journey.steps: 4-5 steps numbered 1..N, describing what the
    customer literally sees/feels opening the package. Build anticipation.
    Each step.description 20-40 words, sensory. NO shipping promises,
    NO delivery time claims. Honest about what the package actually
    contains (per scrape/strategy).
  - Progress_milestones.milestones: EXACTLY 4 milestones. Realistic
    timeframes (Day 1 / Week 1 / Week 4 / Week 8 — or category-appropriate
    like First Use / 3 Uses / 30 Days / 90 Days for items with no
    cumulative effect). expected_result: 20-30 words, honest, no
    invented percentages. label: 4-6 word headline.
  - Mistake_warnings.warnings: 4-6 common misuse patterns. mistake =
    one short sentence (action that's wrong). why_problem = factual
    explanation 15-25 words. instead_do = the correct action 10-20
    words. Tone = caring expert, not scolding.
  - Use_scenarios.scenarios: 3-5 distinct contexts. scenario = short
    name (e.g. "Morning routine", "Date night prep"). when = one-line
    context (e.g. "before makeup, 5am-9am"). how_to_use = specific
    micro-protocol for THIS context 15-25 words. key_benefit = single
    line on outcome for this specific scenario.

OUTPUT NOW (JSON only):"""


def call_sonnet(client: anthropic.Anthropic, prompt: str) -> Optional[dict]:
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            timeout=120.0,
        )
        text = resp.content[0].text
        # Strip markdown fences if model wrapped output
        if "```" in text:
            text = text.split("```", 2)
            text = text[1] if len(text) > 1 else text[0]
            if text.startswith("json\n"):
                text = text[5:]
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        print(f"    JSON parse fail: {str(e)[:100]}")
        return None
    except Exception as e:
        print(f"    Sonnet err: {type(e).__name__}: {str(e)[:120]}")
        return None


def push_metafields(store: str, token: str, product_id: str,
                    new_sections: Dict[str, dict]) -> int:
    if not new_sections:
        return 0
    inputs = [{"ownerId": product_id, "namespace": "custom", "key": k,
               "type": "json", "value": json.dumps(v, ensure_ascii=False)}
              for k, v in new_sections.items()]
    q = """
    mutation($m: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $m) {
        metafields { key }
        userErrors { field message code }
      }
    }
    """
    r = gql(store, token, q, {"m": inputs})
    errs = r.get("data", {}).get("metafieldsSet", {}).get("userErrors", []) or []
    if errs:
        print(f"    metafieldsSet errors: {errs[:3]}")
        return 0
    return len(r.get("data", {}).get("metafieldsSet", {}).get("metafields", []))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="only process first N products")
    parser.add_argument("--only", type=str, default=None,
                        help="comma-separated product PIDs to process (numeric, no gid prefix)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show plan without calling Sonnet or pushing")
    args = parser.parse_args()

    load_env()
    store, token = get_shopify_token()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                 max_retries=3)
    print(f"Shopify: {store}\nAnthropic: ready (Sonnet 4.6)\n")

    # Live products
    r = gql(store, token,
            "query{products(first:50, sortKey:CREATED_AT, reverse:true){nodes{id handle}}}")
    live = r["data"]["products"]["nodes"]
    if args.only:
        targets = set(args.only.split(","))
        live = [p for p in live if p["id"].split("/")[-1] in targets]
    if args.limit:
        live = live[:args.limit]
    print(f"Processing {len(live)} products\n" + "-" * 60)

    # DB for scrape + strategy
    db_conn = None
    if DB_PATH.exists():
        db_conn = sqlite3.connect(str(DB_PATH))
        db_conn.row_factory = sqlite3.Row

    total_added = 0
    for i, p in enumerate(live, 1):
        pid = p["id"]
        short = pid.split("/")[-1]
        handle = p["handle"]
        print(f"\n[{i}/{len(live)}] {handle} (pid={short})")

        mf = fetch_product_metafields(store, token, pid)
        existing = mf["sections"]
        print(f"    existing: {len(existing)} sections")

        to_fill = pick_sections_for(mf.get("product_type", ""), set(existing))
        if not to_fill:
            print(f"    nothing to fill (already enriched)")
            continue
        print(f"    will fill: {to_fill}")

        # Look up scrape + strategy from DB (best-effort match by handle hint)
        scrape, strategy = {}, {}
        if db_conn:
            row = db_conn.execute(
                "SELECT scrape_json, strategy_json FROM products WHERE shopify_product_id LIKE ?",
                (f"%{short}",)
            ).fetchone()
            if row:
                if row["scrape_json"]: scrape = json.loads(row["scrape_json"])
                if row["strategy_json"]: strategy = json.loads(row["strategy_json"])

        if args.dry_run:
            print(f"    [dry-run] would call Sonnet + push {len(to_fill)} sections")
            continue

        prompt = build_prompt(mf["title"], mf["product_type"], scrape,
                              strategy, existing, to_fill)
        result = call_sonnet(client, prompt)
        if not result:
            print(f"    SKIP (Sonnet failed)")
            continue

        # Filter result: only sections we actually requested + non-empty
        new_sections = {k: v for k, v in result.items()
                        if k in to_fill and isinstance(v, dict) and v}
        if not new_sections:
            print(f"    Sonnet returned 0 usable sections")
            continue

        n = push_metafields(store, token, pid, new_sections)
        total_added += n
        print(f"    pushed: {n} new sections → {list(new_sections.keys())}")
        time.sleep(0.5)

    print(f"\n{'=' * 60}\nTotal new sections added: {total_added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
