#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_junk_metafields.py — delete the junk product metafield DEFINITIONS the
pipeline auto-created from leaked/typo Designer keys, AND their associated values
(deleteAllAssociatedMetafields: true). Part 4 of the junk-sections cleanup.

Deletes ONLY confirmed junk (typo/variant of real sections + inline_* photo-brief
leaks + placeholders). KEEPS legitimate extras (html_description, videos,
research_refs, rating, trust_strip, source_url, user_stories, scent_profile).

DRY-RUN by default; --execute applies. Destructive on live Shopify — confirmed.
"""
from __future__ import annotations
import argparse, os, re, sys, time
import requests
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
STORE = os.environ["SHOPIFY_STORE"]
API = f"https://{STORE}/admin/api/2024-10/graphql.json"

ALIAS = {'timerline', 'comparison', 'ingredients_explanation', 'idline'}
JUNK_DROP = {'variant_key', 'additional_keys'}


def is_junk_key(k):
    return (k in ALIAS or k in JUNK_DROP or bool(re.match(r'^inline[-_]', k))
            or 'inline_photo' in k or k.endswith('_inline_photos'))


def token():
    return requests.post(f"https://{STORE}/admin/oauth/access_token",
        json={"client_id": os.environ["SHOPIFY_CLIENT_ID"],
              "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
              "grant_type": "client_credentials"}, timeout=15).json()["access_token"]


def gql(tok, q, v=None):
    return requests.post(API, headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
                         json={"query": q, "variables": v or {}}, timeout=40).json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    tok = token()
    r = gql(tok, 'query{metafieldDefinitions(first:250,ownerType:PRODUCT,namespace:"custom"){nodes{id key name metafieldsCount}}}')
    nodes = (((r.get("data") or {}).get("metafieldDefinitions") or {}).get("nodes")) or []
    junk = [n for n in nodes if is_junk_key(n["key"])]
    keep = [n for n in nodes if not is_junk_key(n["key"])]
    print(f"custom PRODUCT metafield definitions: {len(nodes)} | junk: {len(junk)} | keep: {len(keep)}\n")
    print("JUNK to delete (definition + all associated values):")
    for n in junk:
        print(f"  - {n['key']:<24} (values: {n.get('metafieldsCount', '?')})")
    print("\nKEPT (not touched):")
    print("  " + ", ".join(sorted(n["key"] for n in keep)))

    if not args.execute:
        print("\nDRY-RUN — re-run with --execute to delete.")
        return 0

    print(f"\nDeleting {len(junk)} junk definitions (+ associated values)...")
    mut = ("mutation($id:ID!){metafieldDefinitionDelete(id:$id, deleteAllAssociatedMetafields:true)"
           "{deletedDefinitionId userErrors{field message}}}")
    done = fail = 0
    for n in junk:
        rr = gql(tok, mut, {"id": n["id"]})
        d = ((rr.get("data") or {}).get("metafieldDefinitionDelete") or {})
        ue = d.get("userErrors") or []
        if d.get("deletedDefinitionId") and not ue:
            done += 1; print(f"  ✅ {n['key']}")
        else:
            fail += 1; print(f"  ! {n['key']}: {ue or rr.get('errors')}")
        time.sleep(0.25)
    print(f"\nDeleted {done}/{len(junk)} junk definitions (fail {fail}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
