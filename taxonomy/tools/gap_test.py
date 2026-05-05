#!/usr/bin/env python3
"""gap_test.py — matching списка товаров против таксономии.

Для каждого продукта находит top-K ближайших кластеров через cosine similarity.

**Backend выбирается автоматически:**
- В проде / Colab — `sentence-transformers` + `paraphrase-multilingual-MiniLM-L12-v2`
  (мультиязычный, ~зеленая точность для синонимов и кросс-языка).
- В сандбоксе Claude Code on the Web `huggingface.co` блокируется на сетевом
  уровне → автоматический фоллбэк на **TF-IDF** (scikit-learn). Менее точно для
  синонимов и кросс-языка, но работоспособно для английских названий товаров
  против `embed_text` (которые содержат английские ключевые слова).

Usage:
    python taxonomy/tools/gap_test.py --self-test
    python taxonomy/tools/gap_test.py --products products.txt
    python taxonomy/tools/gap_test.py --products catalog.csv

    # принудительный backend
    python taxonomy/tools/gap_test.py --self-test --backend tfidf
    python taxonomy/tools/gap_test.py --self-test --backend st  # sentence-transformers

Параметры:
    --top-k N        сколько ближайших кластеров показывать (default 3)
    --threshold X    cosine ниже X считаем «непокрытым»
                     (default 0.45 для st, 0.10 для tfidf — у TF-IDF
                     абсолютные scores ниже из-за sparse vectors;
                     значения <0.06 обычно означают «семантически мимо»)
    --json out.json  выгрузить полный отчёт в JSON
    --quiet          печатать только uncovered

Exit codes: 0 — все покрыты; 3 — есть непокрытые.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "taxonomy" / "taxonomy.json"
ST_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

DEFAULT_TEST_PRODUCTS = [
    # === sanity (должны быть покрыты в любом виде таксономии) ===
    "Bluetooth headphones with active noise cancelling, over-ear, premium",
    "Эргономичное офисное кресло с поясничной поддержкой",
    "Robot vacuum cleaner with mapping",
    "Diffuser essential oil aromatherapy",
    "Wedding ring set platinum",
    "Yoga mat non-slip eco",
    "Stainless steel water bottle 1L",
    "Plant pot ceramic indoor",
    # === покрыты благодаря v3.3-добавлениям ===
    "Smart air purifier HEPA Levoit Core 300",
    "Dash cam 4K with night vision and parking mode",
    "Standing electric desk Flexispot 48 inch",
    "Yale August smart deadbolt with Wi-Fi bridge",
    "Sleep tracker Oura ring gen 4",
    "TP-Link Kasa smart plug 4-pack",
    "Brita pitcher water filter 10-cup",
    "Pepper spray keychain self-defense",
    "Anti-aging retinol serum 1% encapsulated",
    "Salicylic acid acne spot treatment",
    "Furbo dog camera with treat tossing",
    "Karcher SC2 EasyFix steam cleaner",
    "GPS tracker for cat / dog with Wi-Fi",
    # === потенциальные новые гэпы ===
    "Tactical flashlight rechargeable USB-C with strobe mode",
    "Beard trimmer cordless waterproof Philips",
    "Reusable menstrual cup silicone",
    "DJI Mini 4 Pro drone with 4K camera",
    "Hydroponic indoor garden AeroGarden harvest 360",
    "Massage gun percussion deep tissue Theragun",
    "Adult coloring book set with markers and pencils",
    "VR fitness game Beat Saber bundle",
    "Scuba diving mask snorkel set with fins",
    "Hammock with stand for backyard portable",
    "Acoustic guitar capo and tuner kit",
    "Sourdough bread starter kit ceramic crock",
    "Heated blanket electric king size dual control",
    "Knitting needle set bamboo with case",
    "Кухонные ножи японские шеф-нож набор Damascus steel",
    "EV electric vehicle charger Level 2 home",
    "3D printer FDM resin starter kit",
    "Acoustic foam panels for home recording studio",
]


# Per-section probe set: для каждой section_id — список (≥1) тестовых
# продуктов, которые ОЖИДАЕТСЯ что top-1 кластер будет в этой секции.
# Помогает ловить «section-coverage gaps»: секция объявлена, но никакой
# типичный продукт её темы не находит подходящего кластера ВНУТРИ неё.
PER_SECTION_PROBES: dict[str, list[str]] = {
    "1.1": ["Hair dryer ionic cordless", "Silk pillowcase for skin and hair"],
    "1.2": ["French press coffee maker glass", "Matcha green tea ceremonial grade"],
    "1.3": ["Resistance bands set with door anchor", "Running shoes max cushion road"],
    "1.4": ["Compression packing cubes set", "Universal travel adapter with USB-C"],
    "1.5": ["Smart air quality monitor PM2.5", "Cordless handheld vacuum"],
    "1.6": ["Mechanical keyboard hot-swappable RGB", "Wireless mouse ergonomic vertical"],
    "1.7": ["Automatic cat litter box self-cleaning", "Dog harness no-pull padded"],
    "1.8": ["Diaper bag backpack waterproof", "Baby monitor with camera Wi-Fi"],
    "1.9": ["Board game strategy 4-player", "Drone racing FPV beginner kit"],
    "2":   ["Charcuterie gift basket meat cheese", "Personalized photo frame engraved"],
    "3":   ["Dining table extendable solid wood", "L-shape office desk corner"],
    "4":   ["Boho macrame wall hanging tassel", "Minimalist Scandinavian decor"],
    "5":   ["Christmas tree artificial pre-lit 7ft", "Halloween costume adult vampire"],
    "6":   ["Coffee bundle French press kettle scale grinder", "Yoga starter kit mat blocks strap"],
    "7":   ["Luxury watch under five thousand dollars", "Affordable gift under twenty"],
    "8":   ["Linen bedding king size set 100% flax", "Walnut wood serving board hand-rubbed"],
    "9":   ["Maximalist colorful eclectic decor", "Wabi-sabi minimalist wellness set"],
    "10":  ["Skincare routine bundle 5 steps cleanser toner moisturizer", "Tea sampler box 12 varieties"],
    "11":  ["Bachelorette party kit decorations sash", "New baby announcement gift box"],
    "12":  ["Sage green decor accent set", "Terracotta orange pottery vase"],
    "13":  ["Car seat covers waterproof full set", "Bike rack hitch-mounted 4-bike"],
    "14":  ["Cordless drill driver 20V brushless", "Soldering iron station temperature controlled"],
    "15":  ["Smart RGB strip lights 32ft Wi-Fi", "Sunset lamp projector amber"],
    "16":  ["Workout leggings high-waist squat-proof", "Beach vacation outfit set linen"],
    "17":  ["Wireless earbuds in-ear active noise cancelling", "External SSD 2TB USB-C portable"],
    "18":  ["Pickleball paddle graphite carbon fiber", "Surfboard inflatable beginner SUP"],
    "19":  ["Truffle oil black 250ml gourmet", "Saffron threads premium grade"],
    "20":  ["Acrylic paint set 24 colors professional", "MIDI keyboard 49 keys USB"],
    "21":  ["Framed canvas print large abstract", "Wall mirror round decorative"],
    "22":  ["Foot massager shiatsu deep kneading", "Pulse oximeter fingertip"],
    "23":  ["Stand mixer 6-quart professional baking", "Coffee grinder burr conical electric"],
    "24":  ["Balloon arch kit gold rose pearl", "Polaroid camera instant film"],
    "25":  ["Pearl necklace freshwater multi-strand", "Silk scarf large square women"],
    "26":  ["Closet system modular wardrobe", "Drawer organizer set bamboo expandable"],
    "27":  ["Phone stand desk adjustable", "Cable organizer box management"],
    "28":  ["Keto snacks variety pack low-carb", "Vegan protein powder plant-based"],
}


def load_products(path: Path | None) -> list[str]:
    if path is None:
        return list(DEFAULT_TEST_PRODUCTS)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and "title" in reader.fieldnames:
                return [r["title"].strip() for r in reader if r.get("title", "").strip()]
            f.seek(0)
            rows = [r[0].strip() for r in csv.reader(f) if r and r[0].strip()]
            return rows[1:] if rows and rows[0].lower() in {"title", "name", "product"} else rows
    return [
        s.strip()
        for s in path.read_text(encoding="utf-8").splitlines()
        if s.strip() and not s.strip().startswith("#")
    ]


def encode_st(texts_a: list[str], texts_b: list[str]):
    from sentence_transformers import SentenceTransformer  # type: ignore

    model = SentenceTransformer(ST_MODEL)
    a = model.encode(texts_a, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
    b = model.encode(texts_b, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
    return a, b


def encode_tfidf(texts_a: list[str], texts_b: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    import numpy as np  # type: ignore

    vec = TfidfVectorizer(
        lowercase=True,
        analyzer="word",
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    combined = texts_a + texts_b
    matrix = vec.fit_transform(combined)
    a = matrix[: len(texts_a)].toarray().astype(np.float32)
    b = matrix[len(texts_a) :].toarray().astype(np.float32)

    def normalize(x):
        norms = np.linalg.norm(x, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return x / norms

    return normalize(a), normalize(b)


def pick_backend(prefer: Literal["auto", "st", "tfidf"]) -> Literal["st", "tfidf"]:
    if prefer == "tfidf":
        return "tfidf"
    if prefer == "st":
        return "st"
    try:
        import sentence_transformers  # noqa: F401
        from sentence_transformers import SentenceTransformer  # type: ignore

        SentenceTransformer(ST_MODEL)
        return "st"
    except Exception:
        return "tfidf"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--probe-set",
        choices=["default", "per-section", "all"],
        default=None,
        help="default = смешанный из 39 продуктов; per-section = ~70 проб по 1-2 на каждую section_id с проверкой что top-1 попадает в ожидаемую section; all = объединение",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--backend", choices=["auto", "st", "tfidf"], default="auto")
    args = parser.parse_args()

    if not args.self_test and args.probe_set is None and args.products is None:
        parser.error("укажи --products, --self-test или --probe-set")
    if not TAXONOMY_PATH.exists():
        print(f"❌ {TAXONOMY_PATH} не найден")
        return 1

    # Build (product, expected_section_id) — expected может быть None
    triples: list[tuple[str, str | None]] = []
    if args.products is not None:
        for p in load_products(args.products):
            triples.append((p, None))
    elif args.probe_set == "per-section":
        for sid, ps in PER_SECTION_PROBES.items():
            for p in ps:
                triples.append((p, sid))
    elif args.probe_set == "all":
        for p in DEFAULT_TEST_PRODUCTS:
            triples.append((p, None))
        for sid, ps in PER_SECTION_PROBES.items():
            for p in ps:
                triples.append((p, sid))
    else:  # --self-test or --probe-set default
        for p in DEFAULT_TEST_PRODUCTS:
            triples.append((p, None))

    if not triples:
        print("❌ нет продуктов на вход")
        return 1
    products = [t[0] for t in triples]
    expected = [t[1] for t in triples]

    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        tax = json.load(f)
    clusters = tax["clusters"]
    cluster_texts = [c["embed_text"] for c in clusters]
    cluster_section_ids = [c["section_id"] for c in clusters]
    sections_by_id = {s["id"]: s for s in tax["sections"]}

    backend = pick_backend(args.backend)
    threshold = args.threshold if args.threshold is not None else (0.45 if backend == "st" else 0.10)
    print(f"backend={backend} threshold={threshold:.2f}", file=sys.stderr)

    if backend == "st":
        cl_emb, pr_emb = encode_st(cluster_texts, products)
    else:
        cl_emb, pr_emb = encode_tfidf(cluster_texts, products)

    import numpy as np  # type: ignore

    sims = pr_emb @ cl_emb.T  # (P, C)
    top_idx = np.argsort(-sims, axis=1)[:, : args.top_k]

    report = []
    uncovered = 0
    section_mismatched = 0
    for i, product in enumerate(products):
        matches = [
            {
                "tag": clusters[j]["tag"],
                "title": clusters[j]["title_en"],
                "section_id": clusters[j]["section_id"],
                "status": clusters[j]["status"],
                "score": float(sims[i, j]),
            }
            for j in top_idx[i]
        ]
        best = matches[0]
        is_uncov = best["score"] < threshold
        section_ok: bool | None
        if expected[i] is not None:
            section_ok = best["section_id"] == expected[i]
            if not section_ok:
                section_mismatched += 1
        else:
            section_ok = None
        report.append(
            {
                "product": product,
                "expected_section": expected[i],
                "best_score": best["score"],
                "uncovered": is_uncov,
                "section_ok": section_ok,
                "matches": matches,
            }
        )
        if is_uncov:
            uncovered += 1

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📄 JSON отчёт → {args.json}", file=sys.stderr)

    has_expected = any(r["expected_section"] is not None for r in report)

    print(f"\n{'='*72}")
    print(f"  Backend: {backend} · threshold cosine={threshold:.2f} · top-k={args.top_k}")
    print(f"  Test products: {len(products)} · Uncovered: {uncovered} ({100*uncovered/len(products):.0f}%)")
    if has_expected:
        n_exp = sum(1 for r in report if r["expected_section"] is not None)
        print(f"  Section mismatches: {section_mismatched}/{n_exp} ({100*section_mismatched/n_exp:.0f}%)")
    print("=" * 72)

    if has_expected and section_mismatched:
        print(f"\n--- SECTION MISMATCHES ({section_mismatched}) ---")
        print("(top-1 кластер попал не в ту секцию, что ожидали)")
        per_section_bad: dict[str, list[str]] = {}
        for r in report:
            if r["expected_section"] is not None and r["section_ok"] is False:
                exp = r["expected_section"]
                actual_sid = r["matches"][0]["section_id"]
                exp_title = sections_by_id.get(exp, {}).get("title_en", "?")
                act_title = sections_by_id.get(actual_sid, {}).get("title_en", "?")
                line = (
                    f"  ⚠️  expected sec {exp} ({exp_title}) → got sec {actual_sid} ({act_title})\n"
                    f"      product: {r['product']}\n"
                    f"      top-1:   {r['matches'][0]['tag']} ({r['matches'][0]['score']:.3f})"
                )
                print(line)
                per_section_bad.setdefault(exp, []).append(r["product"])

    if uncovered:
        print(f"\n--- UNCOVERED by absolute threshold ({uncovered}) ---")
        for r in report:
            if r["uncovered"]:
                best = r["matches"][0]
                tag = best["tag"]
                print(f"  ❌ {r['best_score']:.3f}  {r['product']}")
                print(f"        nearest: {tag:<42} ({best['score']:.3f}) {best['title']}")

    if not args.quiet:
        n_cov = len(products) - uncovered
        print(f"\n--- COVERED ({n_cov}) ---")
        for r in report:
            if not r["uncovered"]:
                best = r["matches"][0]
                tag = best["tag"]
                marker = (
                    "✅"
                    if r["section_ok"] is None or r["section_ok"]
                    else "🟡"  # покрыт по score, но top-1 в чужой секции
                )
                print(f"  {marker} {r['best_score']:.3f}  {r['product']}")
                print(f"        match: {tag:<42} {best['title']}")

    return 3 if (uncovered or section_mismatched) else 0


if __name__ == "__main__":
    sys.exit(main())
