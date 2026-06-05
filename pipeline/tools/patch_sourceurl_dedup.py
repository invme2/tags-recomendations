#!/usr/bin/env python3
"""patch_sourceurl_dedup.py — add source_url dedup check to prevent duplicate products.

Root cause: different chunk runs generate different titles for the same EPROLO product,
so shopify_find_product(title) misses the existing product and creates a duplicate.

Fix: before creating, also query Shopify for an existing product with the same
custom.source_url metafield value. If found, UPDATE instead of CREATE.
This makes dedup robust regardless of generated title differences across runs.

nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"
CELL = 14

OLD = (
    "            existing_id = await shopify_find_product(product['title'])\n"
    "            if not existing_id and handle:\n"
    "                _hq = f'handle:{handle}'\n"
    "                r_handle = await shopify_gql('query($q:String!){products(first:1,query:$q){nodes{id}}}', {\"q\": _hq})\n"
    "                nodes = r_handle.get('data',{}).get('products',{}).get('nodes',[]) if r_handle else []\n"
    "                if nodes: existing_id = nodes[0]['id']"
)

NEW = (
    "            existing_id = await shopify_find_product(product['title'])\n"
    "            if not existing_id and handle:\n"
    "                _hq = f'handle:{handle}'\n"
    "                r_handle = await shopify_gql('query($q:String!){products(first:1,query:$q){nodes{id}}}', {\"q\": _hq})\n"
    "                nodes = r_handle.get('data',{}).get('products',{}).get('nodes',[]) if r_handle else []\n"
    "                if nodes: existing_id = nodes[0]['id']\n"
    "            # SOURCE_URL dedup (prevents duplicates when same EPROLO product is processed\n"
    "            # in multiple chunk runs with different generated titles / handles).\n"
    "            if not existing_id:\n"
    "                _src_url = (product.get('url') or '').strip().rstrip('/')\n"
    "                if _src_url:\n"
    "                    _src_q = (\n"
    "                        'query($ns:String!,$k:String!,$v:String!){'\n"
    "                        'products(first:1,query:$v){nodes{id title}}}'\n"
    "                    )\n"
    "                    _src_q2 = 'query($v:String!){products(first:2,query:$v){nodes{id title}}}'\n"
    "                    _src_r = await shopify_gql(_src_q2, {\"v\": f'metafield:custom.source_url:{_src_url}'})\n"
    "                    _src_nodes = (_src_r or {}).get('data',{}).get('products',{}).get('nodes',[]) if _src_r else []\n"
    "                    if _src_nodes:\n"
    "                        existing_id = _src_nodes[0]['id']\n"
    "                        print(f'    [dedup] Found by source_url: {existing_id} ({_src_nodes[0][\"title\"][:40]})')"
)


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    cell = nb.cells[CELL]
    if cell.source.count(OLD) != 1:
        print(f"FAIL: anchor found {cell.source.count(OLD)} times")
        return 1
    cell.source = cell.source.replace(OLD, NEW)
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("OK: source_url dedup check added to Shopify push step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
