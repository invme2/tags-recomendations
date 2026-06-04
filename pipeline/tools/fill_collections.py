#!/usr/bin/env python3
"""fill_collections.py — fill empty/thin keyword-collections with topically
relevant catalog products, so each DataForSEO landing page actually has stock to
rank + convert. FREE: no DataForSEO, no Claude — pure local TF-IDF matching
against the taxonomy, then Shopify collectionAddProducts.

WHY static add (not smart rules): Shopify silently refuses to add a ruleSet to a
collection created as manual (type is fixed at creation), so manual keyword
collections cannot be converted to smart. We therefore add explicit membership.
Idempotent + additive — safe to re-run after each new product chunk.

MATCHING
  collection_doc = title + handle words + meta_title + meta_description
  cluster_doc    = title_en + synonyms + typical_products + embed_text + section
  Joint TF-IDF vectorizer (shared vocab). For each target collection:
    1. cosine vs every taxonomy cluster; keep clusters with sim >= --min-sim
       (always allow the single best if it clears --floor), cap --max-clusters.
    2. candidate products = union of catalog products tagged cluster:<matched>.
    3. re-rank candidates by cosine(product_doc, collection_doc); keep top
       --max-products above --prod-floor.
  A product may land in several collections (good internal-link equity), but is
  capped to its --max-coll best collections to avoid spammy over-membership.

USAGE
  python pipeline/tools/fill_collections.py                 # DRY-RUN (default)
  python pipeline/tools/fill_collections.py --include-thin   # also top-up 1-4
  python pipeline/tools/fill_collections.py --execute        # apply adds
  flags: --min-sim 0.20 --floor 0.12 --max-clusters 4 --max-products 40
         --prod-floor 0.06 --max-coll 8 --limit N(debug)
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, time, glob
from collections import defaultdict
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"
TAX = ROOT / "taxonomy" / "taxonomy.json"
OUT = ROOT / "pipeline" / "runs" / "_logs" / "fill_collections_plan.json"

_WORD = re.compile(r"[a-z0-9]+")


def words(s: str) -> str:
    return " ".join(_WORD.findall((s or "").lower()))


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None, retries=6):
    r = {}
    for a in range(retries):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok,
                                        "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=90).json()
        errs = r.get("errors") or []
        if errs and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in errs):
            time.sleep(2 + a * 2); continue
        return r
    return r


# ---------- load taxonomy clusters ----------
def load_clusters():
    tax = json.loads(TAX.read_text(encoding="utf-8"))
    out = {}
    for c in tax["clusters"]:
        tag = c.get("tag", "")
        slug = tag.split("cluster:")[-1] if tag.startswith("cluster:") else tag
        if not slug:
            continue
        syn = c.get("synonyms") or []
        typ = c.get("typical_products") or []
        doc = " ".join([
            c.get("title_en", ""), c.get("title_en", ""),  # weight title x2
            " ".join(syn) if isinstance(syn, list) else str(syn),
            " ".join(typ) if isinstance(typ, list) else str(typ),
            c.get("embed_text", ""), c.get("section_title_en", ""),
            c.get("description", ""),
        ])
        out[slug] = words(doc)
    return out


# ---------- load catalog products (gid, doc, clusters) ----------
def load_products():
    prod = {}  # gid -> {"doc":..., "clusters":set}
    cl_to_prod = defaultdict(set)
    for db in glob.glob(str(ROOT / "runs" / "*" / "pipeline.db")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
            rows = con.execute("SELECT shopify_product_id,name,product_tags,seo_title "
                               "FROM products WHERE status='done' AND shopify_product_id IS NOT NULL").fetchall()
            con.close()
        except Exception:
            continue
        for gid, name, tags, seo in rows:
            if not gid or gid in prod:
                continue
            cls = set(re.findall(r"cluster:([a-z0-9\-]+)", tags or ""))
            if not cls:
                continue
            prod[gid] = {"doc": words(f"{seo or ''} {name or ''} {' '.join(cls)}"), "clusters": cls}
            for c in cls:
                cl_to_prod[c].add(gid)
    return prod, cl_to_prod


# ---------- load catalog products from LIVE Shopify (corruption-proof) ----------
def load_products_shopify(tok):
    """Source products + cluster tags from the live store, not local DBs. Immune
    to a corrupted pipeline.db and covers EVERY active product (incl. chunk2)."""
    prod = {}
    cl_to_prod = defaultdict(set)
    cur = None
    while True:
        r = gql(tok, """query($c:String){products(first:200,after:$c,query:"status:active"){
          pageInfo{hasNextPage endCursor} nodes{id title tags}}}""", {"c": cur})
        d = (r.get("data") or {}).get("products")
        if not d:
            print("ERR products:", json.dumps(r)[:300]); break
        for n in d["nodes"]:
            gid = n["id"]
            cls = {t.split("cluster:")[-1] for t in (n.get("tags") or []) if t.startswith("cluster:")}
            if not cls:
                continue
            prod[gid] = {"doc": words(f"{n.get('title','')} {' '.join(cls)}"), "clusters": cls}
            for c in cls:
                cl_to_prod[c].add(gid)
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.2)
        else:
            break
    return prod, cl_to_prod


# ---------- load Shopify collections ----------
def load_collections(tok):
    cur = None
    cols = []
    while True:
        r = gql(tok, """query($c:String){collections(first:200,after:$c){pageInfo{hasNextPage endCursor}
          nodes{id handle title productsCount{count} ruleSet{rules{column}}
            mt:metafield(namespace:"custom",key:"parent_category"){value}
            md:metafield(namespace:"global",key:"description_tag"){value}}}}""", {"c": cur})
        d = (r.get("data") or {}).get("collections")
        if not d:
            print("ERR collections:", json.dumps(r)[:300]); break
        cols.extend(d["nodes"])
        if d["pageInfo"]["hasNextPage"]:
            cur = d["pageInfo"]["endCursor"]; time.sleep(0.25)
        else:
            break
    return cols


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--include-thin", action="store_true", help="also top-up collections with 1-4 products")
    ap.add_argument("--prod-sim", type=float, default=0.13, help="min direct collection↔product cosine to add")
    ap.add_argument("--min-sim", type=float, default=0.20, help="min collection↔cluster cosine for fallback recall")
    ap.add_argument("--floor", type=float, default=0.14, help="min sim to accept the single best cluster")
    ap.add_argument("--max-clusters", type=int, default=4)
    ap.add_argument("--max-products", type=int, default=40)
    ap.add_argument("--prod-floor", type=float, default=0.06)
    ap.add_argument("--min-picks", type=int, default=2, help="min products to fill a collection…")
    ap.add_argument("--strong", type=float, default=0.22, help="…unless the single best match scores >= this")
    ap.add_argument("--max-coll", type=int, default=8, help="max collections one product may be added to")
    ap.add_argument("--limit", type=int, default=0, help="debug: only first N target collections")
    ap.add_argument("--from-shopify", action="store_true",
                    help="source products+cluster tags from LIVE Shopify (corruption-proof, all products)")
    args = ap.parse_args()

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except Exception:
        print("нужен scikit-learn: pip install scikit-learn"); return 1

    print("Загрузка таксономии + каталога…")
    clusters = load_clusters()
    tok = token()
    if args.from_shopify:
        prod, cl_to_prod = load_products_shopify(tok)
        print(f"  источник товаров: LIVE Shopify")
    else:
        prod, cl_to_prod = load_products()
        print(f"  источник товаров: локальные pipeline.db")
    print(f"  кластеров: {len(clusters)} | товаров: {len(prod)} | кластеров с товарами: {len(cl_to_prod)}")

    cols = load_collections(tok)
    target = [c for c in cols if not c.get("ruleSet") and
              ((c.get("productsCount") or {}).get("count", 0) == 0 or
               (args.include_thin and (c.get("productsCount") or {}).get("count", 0) <= 4))]
    if args.limit:
        target = target[:args.limit]
    print(f"  коллекций всего: {len(cols)} | целей (manual пустых{'/тонких' if args.include_thin else ''}): {len(target)}")

    # ---- joint TF-IDF over clusters + collections + products (shared vocab) ----
    cl_slugs = list(clusters)
    cl_docs = [clusters[s] for s in cl_slugs]
    col_docs = [words(f"{c['title']} {c['handle'].replace('-',' ')} {c['handle'].replace('-',' ')} "
                      f"{(c.get('md') or {}).get('value','')}") for c in target]
    gids = list(prod)
    gid_pos = {g: i for i, g in enumerate(gids)}
    prod_docs = [prod[g]["doc"] for g in gids]
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    vec.fit(cl_docs + col_docs + prod_docs)
    CL = vec.transform(cl_docs)
    CO = vec.transform(col_docs)
    PV = vec.transform(prod_docs)

    clu_sim = cosine_similarity(CO, CL)   # [n_target x n_clusters]  (recall booster)
    dir_sim = cosine_similarity(CO, PV)   # [n_target x n_products]  (precision driver)

    plan = []
    per_product_adds = defaultdict(list)
    for ti, c in enumerate(target):
        scores = {}  # gid_index -> score
        # (a) DIRECT product match — product title/tags share the keyword theme
        drow = dir_sim[ti]
        for pi in drow.argsort()[::-1][:args.max_products * 2]:
            if drow[pi] >= args.prod_sim:
                scores[pi] = float(drow[pi])
            else:
                break
        # (b) CLUSTER boost — only RESCUE products that still share vocabulary with
        # the collection (dir_sim >= gate). Cluster membership alone never adds an
        # off-theme product (precision-first: no "menopause cream" in skincare-sets).
        crow = clu_sim[ti]
        gate = args.prod_sim * 0.55
        chosen = []
        for j in crow.argsort()[::-1][:args.max_clusters]:
            if crow[j] >= args.min_sim or (not chosen and crow[j] >= args.floor):
                chosen.append((cl_slugs[j], float(crow[j])))
        for slug, cs in chosen:
            for g in cl_to_prod.get(slug, ()):
                pi = gid_pos[g]
                if drow[pi] >= gate:                     # must be on-theme by words too
                    boosted = drow[pi] + 0.25 * cs       # cluster agreement lifts rank
                    if boosted > scores.get(pi, 0.0):
                        scores[pi] = float(boosted)
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        picks = [(gids[pi], s) for pi, s in ranked if s >= args.prod_floor][:args.max_products]
        if not picks:
            continue
        # confidence gate: accept a small collection only if it has >= min-picks
        # products OR a single very-strong match. Kills "1 marginal wrong product".
        if len(picks) < args.min_picks and picks[0][1] < args.strong:
            continue
        plan.append({"cidx": ti, "handle": c["handle"], "title": c["title"],
                     "now": (c.get("productsCount") or {}).get("count", 0),
                     "clusters": chosen[:2], "picks": picks})
        for g, s in picks:
            per_product_adds[g].append((ti, s))

    # cap product over-membership: keep each product's top --max-coll collections
    keep = defaultdict(set)  # cidx -> set(gid)
    for g, lst in per_product_adds.items():
        for ti, s in sorted(lst, key=lambda x: x[1], reverse=True)[:args.max_coll]:
            keep[ti].add(g)

    # finalize plan with capped picks
    final = []
    total_adds = 0
    for p in plan:
        kept = [(g, s) for g, s in p["picks"] if g in keep[p["cidx"]]]
        if not kept:
            continue
        p["picks"] = kept
        total_adds += len(kept)
        final.append(p)

    # ---- report ----
    filled = len(final)
    print(f"\n{'='*66}\nПЛАН НАПОЛНЕНИЯ ({'EXECUTE' if args.execute else 'DRY-RUN'})\n{'='*66}")
    print(f"  коллекций будет наполнено: {filled}/{len(target)}")
    print(f"  всего добавлений товар→коллекция: {total_adds}")
    if final:
        sizes = sorted(len(p["picks"]) for p in final)
        print(f"  товаров на коллекцию: min={sizes[0]} медиана={sizes[len(sizes)//2]} max={sizes[-1]}")
    print(f"\n  ПРИМЕРЫ (первые 12) — проверь релевантность:")
    for p in final[:14]:
        cls = ", ".join(f"{s}:{sc:.2f}" for s, sc in p["clusters"]) or "—"
        top = p["picks"][0][1]
        names = [f"{prod[g]['doc'][:32]}·{sc:.2f}" for g, sc in p["picks"][:3]]
        print(f"   ▸ {p['handle']:<32} +{len(p['picks']):<3} top={top:.2f} | кл: {cls}")
        print(f"       {' | '.join(names)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([{**{k: v for k, v in p.items() if k != "picks"},
                                "picks": [[g, round(s, 3)] for g, s in p["picks"]]} for p in final],
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  план сохранён: {OUT}")

    if not args.execute:
        print("\n  это DRY-RUN. Запуск с --execute применит добавления.")
        return 0

    # ---- execute: collectionAddProducts in batches ----
    print(f"\n  Применяю {total_adds} добавлений в {filled} коллекций…")
    done = 0
    for p in final:
        cid = target[p["cidx"]]["id"]
        ids = [g for g, _ in p["picks"]]
        for b in range(0, len(ids), 200):
            chunk = ids[b:b+200]
            r = gql(tok, """mutation($id:ID!,$pids:[ID!]!){collectionAddProducts(id:$id,productIds:$pids){
                userErrors{field message}}}""", {"id": cid, "pids": chunk})
            ue = (((r.get("data") or {}).get("collectionAddProducts") or {}).get("userErrors")) or []
            if ue:
                print(f"   ! {p['handle']}: {ue[:2]}")
            else:
                done += len(chunk)
            time.sleep(0.4)
        print(f"   ✅ {p['handle']:<34} +{len(ids)}")
    print(f"\nГотово: добавлено {done} вхождений в {filled} коллекций.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
