#!/usr/bin/env python3
"""patch_deepseek_designer.py — wire DeepSeek V4 Pro into the Designer step
behind a flag (DESIGNER_PROVIDER=anthropic|deepseek, default anthropic).

A/B (3 real products) showed DeepSeek: valid JSON 3/3, ~20x cheaper, ~5x faster,
copy quality on par. Two tunable gaps addressed via a provider nudge appended to
the system prompt for DeepSeek only: (1) keep <em> emphasis tags, (2) fill more
sections (AIM HIGH).

Design: a shim response object exposes .usage.input_tokens/.output_tokens so the
existing _track_anthropic_response(...) + cost accounting work unchanged. The
DeepSeek HTTP call runs off-thread (asyncio.to_thread) so it never blocks the
event loop under BATCH_CONCURRENCY. Default path (anthropic) is byte-for-byte
the original streaming call. nbformat path. After: notebook_smoke + pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path
import nbformat

NB = Path(__file__).resolve().parents[1] / "Shopify_Pipeline.ipynb"

# ── EDIT 1: config flag (cell 2), after MODEL_DESIGNER ──
CFG_OLD = 'MODEL_DESIGNER = "claude-sonnet-4-6"  # writes JSON content (cheaper, structural).'
CFG_NEW = CFG_OLD + "\n".join([
    "",
    "# Designer provider switch (A/B-validated). 'deepseek' = ~20x cheaper Designer step.",
    "DESIGNER_PROVIDER = os.environ.get('DESIGNER_PROVIDER', 'anthropic').strip().lower()",
    "DEEPSEEK_MODEL    = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')",
    "DEEPSEEK_API_KEY  = os.environ.get('DEEPSEEK_API_KEY', '')",
])

# ── EDIT 2: helper (cell 4), before _check_anthropic_budget ──
HELPER = "\n".join([
    "# ─── DeepSeek Designer provider (flagged: DESIGNER_PROVIDER=deepseek) ───",
    "_DEEPSEEK_DESIGNER_NUDGE = (",
    '    "\\n\\n## PROVIDER NOTE — follow strictly:\\n"',
    '    "- Put <em>...</em> around 1-2 emotional words in EVERY heading (h1/h2/h4). "',
    '    "It powers the italic serif styling — never omit it.\\n"',
    '    "- AIM HIGH on modules: FILL 18-25 of the available sections whenever the "',
    '    "product supports them. Do NOT be conservative — a richer page converts better.\\n"',
    ")",
    "",
    "class _ShimUsage:",
    "    def __init__(self, i, o):",
    "        self.input_tokens = int(i or 0); self.output_tokens = int(o or 0)",
    "",
    "class _ShimResp:",
    "    def __init__(self, i, o):",
    "        self.usage = _ShimUsage(i, o)",
    "",
    "async def _deepseek_designer(system_text, user_text, max_tokens=8192):",
    '    """Call DeepSeek (OpenAI-compatible, JSON mode) off-thread so the event',
    '    loop is not blocked. Returns (raw_json_text, shim_response_with_usage)."""',
    "    import asyncio as _aio",
    "    def _do():",
    "        return requests.post(",
    '            "https://api.deepseek.com/chat/completions",',
    '            headers={"Authorization": "Bearer " + DEEPSEEK_API_KEY,',
    '                     "Content-Type": "application/json"},',
    '            json={"model": DEEPSEEK_MODEL,',
    '                  "messages": [{"role": "system", "content": system_text + _DEEPSEEK_DESIGNER_NUDGE},',
    '                               {"role": "user", "content": user_text}],',
    '                  "max_tokens": max_tokens, "temperature": 0.7,',
    '                  "response_format": {"type": "json_object"}},',
    "            timeout=1800)",
    "    _r = await _aio.to_thread(_do)",
    "    _j = _r.json()",
    '    if "choices" not in _j:',
    '        raise RuntimeError("DeepSeek error: " + str(_j)[:200])',
    '    _txt = _j["choices"][0]["message"]["content"].strip()',
    '    _u = _j.get("usage", {}) or {}',
    '    return _txt, _ShimResp(_u.get("prompt_tokens", 0), _u.get("completion_tokens", 0))',
    "",
    "",
    "def _check_anthropic_budget():",
])
HELPER_OLD = "def _check_anthropic_budget():"

# ── EDIT 3: main designer block (cell 14) ──
MAIN_OLD = (
    '            async with client_async.messages.stream(\n'
    '                model=_designer_model, max_tokens=16000, timeout=1800.0,\n'
    '                system=[{"type":"text","text":_designer_system,"cache_control":{"type":"ephemeral","ttl":"1h"}}],\n'
    '                messages=[{"role":"user","content":_designer_user}]) as _stream:\n'
    '                _parts = []\n'
    '                async for _chunk in _stream.text_stream:\n'
    '                    _parts.append(_chunk)\n'
    "                raw2 = ''.join(_parts).strip()\n"
    '                r2 = await _stream.get_final_message()\n'
    '            cost2 = r2.usage.input_tokens * 3 / 1e6 + r2.usage.output_tokens * 15 / 1e6  # Sonnet 4.6 pricing\n'
    '            _track_anthropic_response(r2, cost2)'
)
MAIN_NEW = (
    "            if DESIGNER_PROVIDER == 'deepseek':\n"
    '                raw2, r2 = await _deepseek_designer(_designer_system, _designer_user, 8192)\n'
    '                cost2 = r2.usage.input_tokens * 0.435 / 1e6 + r2.usage.output_tokens * 0.87 / 1e6  # DeepSeek V4 Pro\n'
    '            else:\n'
    '                async with client_async.messages.stream(\n'
    '                    model=_designer_model, max_tokens=16000, timeout=1800.0,\n'
    '                    system=[{"type":"text","text":_designer_system,"cache_control":{"type":"ephemeral","ttl":"1h"}}],\n'
    '                    messages=[{"role":"user","content":_designer_user}]) as _stream:\n'
    '                    _parts = []\n'
    '                    async for _chunk in _stream.text_stream:\n'
    '                        _parts.append(_chunk)\n'
    "                    raw2 = ''.join(_parts).strip()\n"
    '                    r2 = await _stream.get_final_message()\n'
    '                cost2 = r2.usage.input_tokens * 3 / 1e6 + r2.usage.output_tokens * 15 / 1e6  # Sonnet 4.6 pricing\n'
    '            _track_anthropic_response(r2, cost2)'
)

# ── EDIT 4: retry designer block (cell 14) ──
RETRY_OLD = (
    '                    async with client_async.messages.stream(\n'
    '                        model=_designer_model, max_tokens=16000, timeout=1800.0,\n'
    '                        system=[{"type":"text","text":_designer_system,"cache_control":{"type":"ephemeral","ttl":"1h"}}],\n'
    '                        messages=[{"role":"user","content":_retry_user}]) as _stream2:\n'
    '                        _parts2 = []\n'
    '                        async for _chunk2 in _stream2.text_stream:\n'
    '                            _parts2.append(_chunk2)\n'
    "                        _raw2_retry = ''.join(_parts2).strip()\n"
    '                        _r2_retry = await _stream2.get_final_message()\n'
    '                    if _raw2_retry.startswith("```"):\n'
    '                        _raw2_retry = _raw2_retry.split("\\n", 1)[-1].rsplit("\\n", 1)[0]\n'
    '                    _retry_cost_d = _r2_retry.usage.input_tokens * 3 / 1e6 + _r2_retry.usage.output_tokens * 15 / 1e6\n'
    '                    cost2 += _retry_cost_d\n'
    '                    _track_anthropic_response(_r2_retry, _retry_cost_d)'
)
RETRY_NEW = (
    "                    if DESIGNER_PROVIDER == 'deepseek':\n"
    '                        _raw2_retry, _r2_retry = await _deepseek_designer(_designer_system, _retry_user, 8192)\n'
    '                        _retry_cost_d = _r2_retry.usage.input_tokens * 0.435 / 1e6 + _r2_retry.usage.output_tokens * 0.87 / 1e6\n'
    '                    else:\n'
    '                        async with client_async.messages.stream(\n'
    '                            model=_designer_model, max_tokens=16000, timeout=1800.0,\n'
    '                            system=[{"type":"text","text":_designer_system,"cache_control":{"type":"ephemeral","ttl":"1h"}}],\n'
    '                            messages=[{"role":"user","content":_retry_user}]) as _stream2:\n'
    '                            _parts2 = []\n'
    '                            async for _chunk2 in _stream2.text_stream:\n'
    '                                _parts2.append(_chunk2)\n'
    "                            _raw2_retry = ''.join(_parts2).strip()\n"
    '                            _r2_retry = await _stream2.get_final_message()\n'
    '                        _retry_cost_d = _r2_retry.usage.input_tokens * 3 / 1e6 + _r2_retry.usage.output_tokens * 15 / 1e6\n'
    '                    if _raw2_retry.startswith("```"):\n'
    '                        _raw2_retry = _raw2_retry.split("\\n", 1)[-1].rsplit("\\n", 1)[0]\n'
    '                    cost2 += _retry_cost_d\n'
    '                    _track_anthropic_response(_r2_retry, _retry_cost_d)'
)

EDITS = [
    (2, CFG_OLD, CFG_NEW),
    (4, HELPER_OLD, HELPER),
    (14, MAIN_OLD, MAIN_NEW),
    (14, RETRY_OLD, RETRY_NEW),
]


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    for idx, (ci, old, new) in enumerate(EDITS):
        cell = nb.cells[ci]
        n = cell.source.count(old)
        if n != 1:
            print(f"FAIL edit #{idx} (cell {ci}): expected 1 match, found {n}")
            print(f"  old starts: {old[:70]!r}")
            return 1
        cell.source = cell.source.replace(old, new)
        print(f"OK edit #{idx} (cell {ci})")
    nbformat.validate(nb)
    nbformat.write(nb, NB)
    print("DeepSeek Designer wired in behind DESIGNER_PROVIDER flag.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
