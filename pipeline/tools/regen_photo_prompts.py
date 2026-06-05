#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regen_photo_prompts.py — rebuild the photo-pack .txt prompts for specific
products from ALREADY-COMPUTED pipeline data (scrape + image_urls + designer
meta), reusing the REAL builders from the (patched) notebook so output matches
the pipeline byte-for-byte. Does NOT re-run Vision/Strategy/Designer and does
NOT touch Shopify.

Usage: python tools/regen_photo_prompts.py <run_db> <pid> [<pid> ...]
Outputs to: runs/<run>/regen/<handle>/{prompt_carousel,prompt_inline,prompt_reviews}.txt
"""
from __future__ import annotations
import json, re, sqlite3, sys, textwrap, importlib.util
from pathlib import Path
import requests
import nbformat

ROOT = Path(__file__).resolve().parents[1]            # pipeline/
NB = ROOT / "Shopify_Pipeline.ipynb"
PATCH = ROOT / "tools" / "patch_photo_prompts.py"


def _cell(nb, cid):
    return next(c.source for c in nb.cells if c.get("id") == cid)


def _slice(src, start_mark, end_mark):
    lines = src.split("\n")
    si = next(i for i, l in enumerate(lines) if start_mark in l)
    ei = next(i for i, l in enumerate(lines) if end_mark in l and i > si)
    return textwrap.dedent("\n".join(lines[si:ei]))


def build_namespace():
    """Exec the real builders (_INLINE_ASPECT + _build_scope_prompt) and the
    funnel order into a namespace; return it. product/_visual_style_pp are
    injected per-product before each call."""
    nb = nbformat.read(NB, as_version=4)
    c2 = _cell(nb, "b810afd7")
    c14 = _cell(nb, "ce20f070")

    ns: dict = {}
    # funnel order/idx from cell 2
    funnel_src = _slice(c2, "_PHOTO_FUNNEL_ORDER = [", "_PHOTO_FUNNEL_IDX = {")
    funnel_src += "\n_PHOTO_FUNNEL_IDX = {s: i for i, s in enumerate(_PHOTO_FUNNEL_ORDER)}\n"
    exec(funnel_src, ns)
    # _INLINE_ASPECT + _build_scope_prompt from cell 14 (patched)
    builder_src = _slice(c14, "_INLINE_ASPECT = {", "_prompt_carousel_txt = _build_scope_prompt")
    # builder references globals product/_visual_style_pp at call-time
    ns["_build_scope_src"] = builder_src
    # reviews block — LIVE from the patched notebook cell (single source of truth)
    ns["_reviews_rel"] = _slice(c14, "# Per-product review scenes. PRIMARY",
                                '_prompt_reviews_txt = "\\n".join(_rev_lines)')
    return ns


def _safe_slot(s):
    return "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in (s or "photo"))[:40]


def _ext_for(url):
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            if "png" in ct or r.content[:8] == b"\x89PNG\r\n\x1a\n":
                return "png"
            if "webp" in ct:
                return "webp"
    except Exception:
        pass
    return "jpg"


def regen(run_db: Path, pid: int, ns: dict, outroot: Path):
    c = sqlite3.connect(f"file:{run_db}?mode=ro", uri=True)
    row = c.execute(
        "SELECT name,url_handle,scrape_json,image_urls_json,final_html,strategy_json FROM products WHERE id=?",
        (pid,),
    ).fetchone()
    c.close()
    name, handle, scrape, imgs, fh, strat = row
    product = json.loads(scrape or "{}")
    img_data = json.loads(imgs or "{}")
    meta = (json.loads(fh or "{}") or {}).get("meta") or {}
    visual_style = meta.get("visual_style") or ""
    briefs = meta.get("photo_briefs") or []
    strat_d = json.loads(strat or "{}")
    hero = (strat_d or {}).get("hero") or {}
    use_context = (hero.get("lead") or hero.get("h1") or "")[:200]

    all_eprolo = (img_data.get("top") or []) + (img_data.get("desc") or [])
    resolved = []
    for b in briefs:
        try:
            raw = int(b.get("source_index", 0) or 0)
        except (TypeError, ValueError):
            raw = 0
        idx = raw - 1
        if 0 <= idx < len(all_eprolo):
            u = all_eprolo[idx].get("url", "")
            if u.startswith("http"):
                resolved.append((b, u))
    resolved.sort(key=lambda rb: ns["_PHOTO_FUNNEL_IDX"].get(rb[0].get("slot", "") or "", 999))

    files = []
    for bi, (b, u) in enumerate(resolved[:30]):
        ext = _ext_for(u)
        fname = f"{bi+1:02d}-{_safe_slot(b.get('slot', 'photo'))}.{ext}"
        files.append((bi, b, b"", u, fname))

    carousel = [e for e in files if e[1].get("slot", "").startswith("carousel-")]
    inline = [e for e in files if e[1].get("slot", "").startswith("inline-")]

    # call the real _build_scope_prompt with per-product globals
    call_ns = dict(ns)
    call_ns["product"] = product
    call_ns["_visual_style_pp"] = visual_style
    exec(call_ns["_build_scope_src"], call_ns)
    carousel_txt = call_ns["_build_scope_prompt"]("carousel", carousel)
    inline_txt = call_ns["_build_scope_prompt"]("inline", inline)

    # reviews via the patched relative block
    rev_ns = {"product": product, "_use_context": use_context,
              "_visual_style_pp": visual_style, "_meta_pp": meta}
    exec(ns["_reviews_rel"], rev_ns)
    reviews_txt = "\n".join(rev_ns["_rev_lines"])

    outdir = outroot / (handle or f"pid{pid}")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "prompt_carousel.txt").write_text(carousel_txt, encoding="utf-8")
    (outdir / "prompt_inline.txt").write_text(inline_txt, encoding="utf-8")
    (outdir / "prompt_reviews.txt").write_text(reviews_txt, encoding="utf-8")
    print(f"  pid {pid} [{name[:40]}] -> {outdir}")
    print(f"    carousel slots: {[e[4] for e in carousel]}")
    print(f"    inline slots:   {[e[4] for e in inline]}")
    return outdir


def main():
    run_db = Path(sys.argv[1])
    pids = [int(x) for x in sys.argv[2:]]
    ns = build_namespace()
    outroot = run_db.resolve().parents[1] / "regen" if run_db.parent.name == ".db" else run_db.resolve().parent / "regen"
    print(f"regen -> {outroot}")
    for pid in pids:
        regen(run_db, pid, ns, outroot)


if __name__ == "__main__":
    main()
