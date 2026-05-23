#!/usr/bin/env python3
"""
enrich_taxonomy.py — fills empty metadata fields in taxonomy.json via Claude API.

Fills per cluster:
  - title_ru        — Russian title (1–3 words)
  - description     — 1-sentence purpose (English)
  - personas        — 1–3 from the master persona list
  - intents         — 1–2 from the master intent list
  - demos           — primary_gender + ages
  - synonyms        — 2–4 search synonyms (incl. TikTok slang)
  - shopify_collection_hints — 1–3 collection slug hints

Then computes 'related' via FAISS embedding similarity (top 5 neighbors).

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python enrich_taxonomy.py --input taxonomy.json --output taxonomy.enriched.json
  python enrich_taxonomy.py --only-drafts          # only enrich draft V3.2 clusters
  python enrich_taxonomy.py --batch-size 10        # clusters per API call
  python enrich_taxonomy.py --resume               # continue from .progress.json
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import anthropic

ENRICH_MODEL = "claude-sonnet-4-5-20250929"  # good cost/quality balance
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # for `related` computation


# ─────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────
def build_enrich_prompt(batch, persona_tags, intent_tags, demo_gender_tags, demo_age_tags):
    """Generate the user message for a batch of clusters."""
    persona_list = ", ".join(persona_tags)
    intent_list = ", ".join(intent_tags)
    gender_list = ", ".join(demo_gender_tags)
    age_list = ", ".join(demo_age_tags)

    cluster_blocks = []
    for c in batch:
        products = ", ".join(c["typical_products"][:8])
        block = (
            f"---\n"
            f"tag: {c['tag']}\n"
            f"section: {c['section_title_en']}\n"
            f"title_en: {c['title_en']}\n"
            f"typical_products: {products}\n"
        )
        cluster_blocks.append(block)
    clusters_str = "\n".join(cluster_blocks)

    prompt = f"""For each cluster below, fill in metadata.

PERSONAS (pick 1-3 most likely buyers): {persona_list}

INTENTS (pick 1-2 purchase modes): {intent_list}

DEMO_GENDER (pick exactly 1): {gender_list}
DEMO_AGES (pick 1-3): {age_list}

CLUSTERS TO ENRICH:
{clusters_str}

For EACH cluster output an object with these keys:
- tag (echo from input)
- title_ru: Russian title, 1-3 words, lowercase first letter unless proper noun
- description: 1 sentence in English, 8-15 words, what scenario this serves
- personas: 1-3 tags from the PERSONAS list ONLY
- intents: 1-2 tags from the INTENTS list ONLY
- demos: object with "primary_gender" (1 tag from DEMO_GENDER) and "ages" (1-3 from DEMO_AGES)
- synonyms: array of 2-4 English search phrases buyers might use (include TikTok/Instagram slang where relevant, e.g. "GRWM", "stanley cup", "y2k", "clean girl")
- shopify_collection_hints: array of 1-3 Shopify-style collection slugs (lowercase, hyphens) likely to contain these products, e.g. ["beauty", "hair-tools", "skincare"]

OUTPUT: Return ONLY a valid JSON array of objects, one per cluster, in the same order. No prose, no markdown, no code fence. Start with [ and end with ]."""

    return prompt


SYSTEM_PROMPT = """You are a senior taxonomy specialist for a global e-commerce platform.
You enrich product cluster metadata to power personalization algorithms.

Rules:
- Only use exact tags from the provided lists. Never invent new tags.
- Keep descriptions tight and concrete.
- For ambiguous-gender clusters, prefer demo:unisex.
- For age, default to demo:young-adult + demo:adult unless context says otherwise.
- Synonyms should reflect real search intent — include English terms even for items in other languages.
- Output strict JSON. No commentary."""


# ─────────────────────────────────────────────────────────────────
# JSON parsing with fallback
# ─────────────────────────────────────────────────────────────────
def parse_json_array(raw):
    """Robust extraction of a JSON array from model output."""
    text = raw.strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    # Find first [ and last ] for safety
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────
def validate_enriched(item, valid_personas, valid_intents, valid_genders, valid_ages):
    """Drop tags that aren't in the master lists. Returns sanitized item."""
    item["personas"] = [t for t in item.get("personas", []) if t in valid_personas][:3]
    item["intents"] = [t for t in item.get("intents", []) if t in valid_intents][:2]
    demos = item.get("demos", {})
    g = demos.get("primary_gender", "")
    if g not in valid_genders:
        g = "demo:unisex"
    ages = [a for a in demos.get("ages", []) if a in valid_ages][:3]
    if not ages:
        ages = ["demo:young-adult", "demo:adult"]
    item["demos"] = {"primary_gender": g, "ages": ages}
    item["synonyms"] = [s for s in item.get("synonyms", []) if isinstance(s, str)][:4]
    item["shopify_collection_hints"] = [
        h for h in item.get("shopify_collection_hints", []) if isinstance(h, str)
    ][:3]
    item["title_ru"] = (item.get("title_ru") or "").strip()
    item["description"] = (item.get("description") or "").strip()
    return item


# ─────────────────────────────────────────────────────────────────
# FAISS-based "related" computation
# ─────────────────────────────────────────────────────────────────
def compute_related_via_embeddings(clusters, top_k=5):
    """Find top-K nearest clusters by embedding similarity."""
    try:
        from sentence_transformers import SentenceTransformer
        import faiss
        import numpy as np
    except ImportError:
        print("⚠ sentence-transformers / faiss not installed — skipping 'related' computation")
        print("  Install: pip install sentence-transformers faiss-cpu")
        return clusters

    print(f"  Loading embedder: {EMBED_MODEL}...")
    embedder = SentenceTransformer(EMBED_MODEL)
    texts = [c["embed_text"] for c in clusters]
    print(f"  Encoding {len(texts)} clusters...")
    vectors = embedder.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    vectors = vectors.astype("float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    # For each cluster, find top_k+1 (first hit is itself)
    D, I = index.search(vectors, top_k + 1)
    for i, cluster in enumerate(clusters):
        related_tags = []
        for j in I[i]:
            if j != i and len(related_tags) < top_k:
                related_tags.append(clusters[j]["tag"])
        cluster["related"] = related_tags
    return clusters


# ─────────────────────────────────────────────────────────────────
# Main enrichment loop
# ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="taxonomy.json")
    parser.add_argument("--output", default="taxonomy.enriched.json")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--only-drafts", action="store_true",
                        help="Only enrich clusters with status=draft")
    parser.add_argument("--resume", action="store_true",
                        help="Continue from .progress.json")
    parser.add_argument("--skip-related", action="store_true",
                        help="Skip FAISS-based 'related' computation")
    parser.add_argument("--max-batches", type=int, default=0,
                        help="Stop after N batches (0=all). For testing.")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # ─── Load taxonomy ───
    with open(args.input, encoding="utf-8") as f:
        tax = json.load(f)
    clusters = tax["clusters"]

    valid_personas = {p["tag"] for p in tax["personas"]}
    valid_intents = {i["tag"] for i in tax["intents"]}
    valid_genders = {d["tag"] for d in tax["demos"] if d["type"] == "gender"}
    valid_ages = {d["tag"] for d in tax["demos"] if d["type"] == "age"}

    persona_tags = sorted(valid_personas)
    intent_tags = sorted(valid_intents)
    gender_tags = sorted(valid_genders)
    age_tags = sorted(valid_ages, key=lambda x: ["baby", "kids", "teen", "young-adult", "adult", "senior"].index(x.split(":")[1]))

    # ─── Determine which clusters to enrich ───
    needs_enrich = []
    for c in clusters:
        if args.only_drafts and c["status"] != "draft":
            continue
        # Already enriched if has personas + intents + demos.primary_gender
        if c.get("personas") and c.get("intents") and c.get("demos", {}).get("primary_gender"):
            continue
        needs_enrich.append(c)

    print(f"Total clusters: {len(clusters)}")
    print(f"Need enrichment: {len(needs_enrich)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Estimated batches: {(len(needs_enrich) + args.batch_size - 1) // args.batch_size}")

    # ─── Resume support ───
    progress_path = Path(args.output + ".progress.json")
    enriched_by_tag = {}
    if args.resume and progress_path.exists():
        print(f"Resuming from {progress_path}")
        with open(progress_path, encoding="utf-8") as f:
            prog = json.load(f)
        for c in prog["clusters"]:
            if c.get("personas"):  # been enriched
                enriched_by_tag[c["tag"]] = c
        needs_enrich = [c for c in needs_enrich if c["tag"] not in enriched_by_tag]
        print(f"  Already done: {len(enriched_by_tag)}")
        print(f"  Remaining: {len(needs_enrich)}")

    # ─── Enrichment loop ───
    total_cost = 0.0
    batches_done = 0
    for i in range(0, len(needs_enrich), args.batch_size):
        if args.max_batches and batches_done >= args.max_batches:
            print(f"Stopped at max-batches={args.max_batches}")
            break
        batch = needs_enrich[i : i + args.batch_size]
        print(f"\nBatch {batches_done + 1}: clusters {i + 1}-{i + len(batch)} of {len(needs_enrich)}")
        for c in batch[:3]:
            print(f"  {c['tag']}")
        if len(batch) > 3:
            print(f"  ... +{len(batch) - 3} more")

        prompt = build_enrich_prompt(
            batch, persona_tags, intent_tags, gender_tags, age_tags
        )

        try:
            resp = client.messages.create(
                model=ENRICH_MODEL,
                max_tokens=4000,
                temperature=0.3,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            cost = resp.usage.input_tokens * 3 / 1e6 + resp.usage.output_tokens * 15 / 1e6
            total_cost += cost
            raw = resp.content[0].text
            try:
                items = parse_json_array(raw)
            except json.JSONDecodeError as e:
                print(f"  ⚠ JSON parse failed: {e}")
                print(f"  Raw[:300]: {raw[:300]}")
                continue

            # Map by tag (model might reorder)
            by_tag = {it.get("tag"): it for it in items if isinstance(it, dict) and it.get("tag")}
            for c in batch:
                enrich = by_tag.get(c["tag"])
                if not enrich:
                    print(f"  ⚠ Missing in response: {c['tag']}")
                    continue
                enrich = validate_enriched(
                    enrich, valid_personas, valid_intents, valid_genders, valid_ages
                )
                c["title_ru"] = enrich["title_ru"]
                c["description"] = enrich["description"]
                c["personas"] = enrich["personas"]
                c["intents"] = enrich["intents"]
                c["demos"] = enrich["demos"]
                c["synonyms"] = enrich["synonyms"]
                c["shopify_collection_hints"] = enrich["shopify_collection_hints"]
                enriched_by_tag[c["tag"]] = c

            print(f"  ✓ ${cost:.4f} (total ${total_cost:.4f}) | enriched {len(by_tag)}/{len(batch)}")
        except anthropic.APIError as e:
            print(f"  ⚠ API error: {e}. Sleeping 30s...")
            time.sleep(30)
            continue

        batches_done += 1

        # Save progress every 5 batches
        if batches_done % 5 == 0:
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump(tax, f, ensure_ascii=False, indent=2)
            print(f"  💾 Progress saved")

        # Gentle rate limit
        time.sleep(0.3)

    # ─── FAISS related computation ───
    if not args.skip_related:
        print("\n=== Computing 'related' via embeddings ===")
        clusters = compute_related_via_embeddings(clusters, top_k=5)

    # ─── Save final ───
    tax["clusters"] = clusters
    tax["enriched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tax["enrichment_cost_usd"] = round(total_cost, 4)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(tax, f, ensure_ascii=False, indent=2)

    if progress_path.exists():
        progress_path.unlink()

    print(f"\n✓ Saved to {args.output}")
    print(f"  Enriched: {len(enriched_by_tag)} clusters")
    print(f"  Total cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
