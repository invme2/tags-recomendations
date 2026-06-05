#!/usr/bin/env python3
"""patch_title_meta_fix.py — fix two systemic issues found in spot-check:

1. meta_description truncation: models consistently generate 160-275 chars
   despite the 140-155 prompt rule. Add hard truncation at 155 chars in the
   pipeline assembly, preserving whole words.

2. product title on UPDATE: shopify_update_product updates SEO fields but
   does NOT update the product title, leaving the original messy EPROLO title.
   Fix: pass seo_t as the new title on update too (same as on create).

nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 14

EDITS = [
    # Fix 1: truncate meta_description hard at 155 chars (whole word)
    (
        "            seo_t = row['seo_title'] or product['title'][:60]\n"
        "            seo_d = row['seo_description'] or ''",
        "            seo_t = row['seo_title'] or product['title'][:60]\n"
        "            seo_d = row['seo_description'] or ''\n"
        "            # Hard-truncate meta description to 155 chars (Google limit).\n"
        "            # Models overshoot the prompt rule; enforce it in assembly.\n"
        "            if len(seo_d) > 155:\n"
        "                seo_d = seo_d[:152].rsplit(' ', 1)[0] + '...'"
    ),
    # Fix 2: also update product title on UPDATE (not just SEO fields)
    (
        "            if existing_id:\n"
        "                shop_pid = await shopify_update_product(existing_id, body_html, seo_t, seo_d, handle)\n"
        "                print(f'    Updated: {existing_id}')",
        "            if existing_id:\n"
        "                # Also update product title (old EPROLO title was stuck on update)\n"
        "                _title_update = seo_t or product['title'][:60]\n"
        "                await shopify_gql(\n"
        "                    'mutation($id:ID!,$t:String!){productUpdate(input:{id:$id,title:$t}){product{id}}}',\n"
        "                    {'id': existing_id, 't': _title_update})\n"
        "                shop_pid = await shopify_update_product(existing_id, body_html, seo_t, seo_d, handle)\n"
        "                print(f'    Updated: {existing_id}')"
    ),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    for idx, (old, new) in enumerate(EDITS):
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx}: found {n} matches")
            print(f"  old: {old[:60]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx}")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("title/meta fixes applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
