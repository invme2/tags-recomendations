#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_then_delete_junk.py — fix junk product metafields the RIGHT way.

Live theme has a generic `wanelo-auto-section` fallback that RENDERS any custom
metafield shaped {head, <array>}. So the typo/variant keys
(timerline/comparison/ingredients_explanation/idline) actually render as visible
duplicate sections — deleting them blindly would blank a section on ~88 products.

Phase A (MIGRATE, additive/safe): for every product that owns a typo key but has
NO canonical, copy the value onto the canonical key (timeline/compare/
ingredients) so it renders via the proper dedicated snippet.
Phase B (DELETE, destructive): delete all junk definitions (typo keys now
redundant + invisible inline_* photo-brief leaks + placeholders) with
deleteAllAssociatedMetafields:true.

DRY-RUN by default; --execute applies.
"""
from __future__ import annotations
import argparse, os, re, sys, time, json
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"

MIGRATE = [("timerline", "timeline"), ("comparison", "compare"),
           ("ingredients_explanation", "ingredients"), ("idline", "timeline")]
JUNK_DROP = {"variant_key", "additional_keys"}
ALIAS_KEYS = {m[0] for m in MIGRATE}


def is_junk_def(k):
    return (k in ALIAS_KEYS or k in JUNK_DROP or bool(re.match(r"^inline[-_]", k))
            or "inline_photo" in k or k.endswith("_inline_photos"))


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    for a in range(5):
        r = requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                          json={"query": q, "variables": v or {}}, timeout=60).json()
        if r.get("errors") and any("THROTTLED" in str(e.get("extensions", {}).get("code", "")) for e in r["errors"]):
            time.sleep(2 + a); continue
        return r
    return r


PQ = """query($c:String){products(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{id
  timerline:metafield(namespace:"custom",key:"timerline"){value}
  timeline:metafield(namespace:"custom",key:"timeline"){id}
  comparison:metafield(namespace:"custom",key:"comparison"){value}
  compare:metafield(namespace:"custom",key:"compare"){id}
  ingredients_explanation:metafield(namespace:"custom",key:"ingredients_explanation"){value}
  ingredients:metafield(namespace:"custom",key:"ingredients"){id}
  idline:metafield(namespace:"custom",key:"idline"){value}
}}}"""


def collect_migrations(tok):
    """-> list of (product_gid, [(canon_key, value), ...])"""
    cur, out = None, []
    n_prod = 0
    while True:
        r = gql(tok, PQ, {"c": cur})
        d = ((r.get("data") or {}).get("products") or {})
        for nd in d.get("nodes", []):
            n_prod += 1
            sets = []
            has_canon = {"timeline": bool(nd.get("timeline")), "compare": bool(nd.get("compare")),
                         "ingredients": bool(nd.get("ingredients"))}
            for typo, canon in MIGRATE:
                tv = (nd.get(typo) or {})
                val = tv.get("value") if isinstance(tv, dict) else None
                if val and not has_canon.get(canon, True):
                    sets.append((canon, val))
                    has_canon[canon] = True  # don't double-write (idline+timerline both -> timeline)
            if sets:
                out.append((nd["id"], sets))
        if d.get("pageInfo", {}).get("hasNextPage"):
            cur = d["pageInfo"]["endCursor"]
        else:
            break
    return out, n_prod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    tok = token()

    # ── Phase A: migrate ──
    print(f"=== Phase A: migrate typo->canonical [{mode}] ===")
    migs, n_prod = collect_migrations(tok)
    n_sets = sum(len(s) for _, s in migs)
    from collections import Counter
    bycanon = Counter(c for _, sets in migs for c, _ in sets)
    print(f"  scanned {n_prod} products | products needing migration: {len(migs)} | metafields to write: {n_sets}")
    print(f"  by canonical key: {dict(bycanon)}")
    if args.execute:
        mset = ("mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){metafields{key} userErrors{field message}}}")
        wrote = wfail = 0
        for gid, sets in migs:
            inputs = [{"ownerId": gid, "namespace": "custom", "key": c, "type": "json", "value": v} for c, v in sets]
            r = gql(tok, mset, {"m": inputs})
            ue = (((r.get("data") or {}).get("metafieldsSet") or {}).get("userErrors")) or []
            if ue:
                wfail += 1; print(f"    ! {gid}: {ue[:1]}")
            else:
                wrote += len(inputs)
            time.sleep(0.12)
        print(f"  migrated metafields written: {wrote} (product failures: {wfail})")
    else:
        print("  (dry-run: no writes)")

    # ── Phase B: delete junk definitions ──
    print(f"\n=== Phase B: delete junk definitions [{mode}] ===")
    r = gql(tok, 'query{metafieldDefinitions(first:250,ownerType:PRODUCT,namespace:"custom"){nodes{id key metafieldsCount}}}')
    nodes = (((r.get("data") or {}).get("metafieldDefinitions") or {}).get("nodes")) or []
    junk = [n for n in nodes if is_junk_def(n["key"])]
    print(f"  junk definitions to delete: {len(junk)}")
    for n in junk:
        tag = "(migrated->canonical)" if n["key"] in ALIAS_KEYS else "(invisible leak)"
        print(f"    - {n['key']:<24} values={n.get('metafieldsCount','?')} {tag}")
    if args.execute:
        if not migs and n_sets == 0:
            pass
        # safety: only delete typo defs AFTER migration ran (it did, above)
        mut = ("mutation($id:ID!){metafieldDefinitionDelete(id:$id, deleteAllAssociatedMetafields:true)"
               "{deletedDefinitionId userErrors{field message}}}")
        ddone = dfail = 0
        for n in junk:
            rr = gql(tok, mut, {"id": n["id"]})
            dd = ((rr.get("data") or {}).get("metafieldDefinitionDelete") or {})
            if dd.get("deletedDefinitionId") and not dd.get("userErrors"):
                ddone += 1; print(f"    ✅ deleted {n['key']}")
            else:
                dfail += 1; print(f"    ! {n['key']}: {dd.get('userErrors') or rr.get('errors')}")
            time.sleep(0.25)
        print(f"\n  deleted {ddone}/{len(junk)} junk definitions (fail {dfail}).")
    else:
        print("\nDRY-RUN — re-run with --execute to migrate + delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
