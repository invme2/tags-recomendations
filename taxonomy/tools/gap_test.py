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
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--backend", choices=["auto", "st", "tfidf"], default="auto")
    args = parser.parse_args()

    if not args.self_test and args.products is None:
        parser.error("укажи --products или --self-test")
    if not TAXONOMY_PATH.exists():
        print(f"❌ {TAXONOMY_PATH} не найден")
        return 1

    products = load_products(args.products)
    if not products:
        print("❌ нет продуктов на вход")
        return 1

    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        tax = json.load(f)
    clusters = tax["clusters"]
    cluster_texts = [c["embed_text"] for c in clusters]

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
    for i, product in enumerate(products):
        matches = [
            {
                "tag": clusters[j]["tag"],
                "title": clusters[j]["title_en"],
                "status": clusters[j]["status"],
                "score": float(sims[i, j]),
            }
            for j in top_idx[i]
        ]
        best = matches[0]["score"]
        is_uncov = best < threshold
        report.append({"product": product, "best_score": best, "uncovered": is_uncov, "matches": matches})
        if is_uncov:
            uncovered += 1

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📄 JSON отчёт → {args.json}", file=sys.stderr)

    print(f"\n{'='*72}")
    print(f"  Backend: {backend} · threshold cosine={threshold:.2f} · top-k={args.top_k}")
    print(f"  Test products: {len(products)} · Uncovered: {uncovered} ({100*uncovered/len(products):.0f}%)")
    print("=" * 72)

    print(f"\n--- UNCOVERED ({uncovered}) ---")
    for r in report:
        if r["uncovered"]:
            best = r["matches"][0]
            print(f"  ❌ {r['best_score']:.3f}  {r['product']}")
            print(f"        nearest: {best['tag']:<42} ({best['score']:.3f}) {best['title']}")

    if not args.quiet:
        print(f"\n--- COVERED ({len(products) - uncovered}) ---")
        for r in report:
            if not r["uncovered"]:
                best = r["matches"][0]
                print(f"  ✅ {r['best_score']:.3f}  {r['product']:<60s}")
                print(f"        match: {best['tag']:<42} {best['title']}")

    return 3 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
