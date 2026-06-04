#!/usr/bin/env python3
"""anthropic_usage_report.py — read the Anthropic usage sidecar(s) and print a
job-wide cache-hit + spend report, per model. Restart-safe: the notebook tracker
persists cumulative totals to `{run}/anthropic_usage.json`, so this shows the
WHOLE job regardless of how many times the babysitter restarted it.

USAGE
  python pipeline/tools/anthropic_usage_report.py            # all runs/*/anthropic_usage.json
  python pipeline/tools/anthropic_usage_report.py --run health-care-chunk2-2026-06-01
"""
from __future__ import annotations
import argparse, json, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = ('spent_usd', 'cache_read_in', 'cache_create_in', 'fresh_in', 'output_tokens', 'calls')


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return None


def fmt_ratio(read, create, fresh):
    tot = read + create + fresh
    return (read / tot * 100) if tot else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="single run name (else all runs)")
    args = ap.parse_args()

    if args.run:
        paths = [ROOT / "runs" / args.run / "anthropic_usage.json"]
    else:
        paths = [Path(p) for p in glob.glob(str(ROOT / "runs" / "*" / "anthropic_usage.json"))]
    paths = [p for p in paths if Path(p).exists()]
    if not paths:
        print("Нет сайдкаров anthropic_usage.json (трекер запишет их при следующем прогоне).")
        return 0

    agg = {k: 0 for k in KEYS}
    by_model = {}
    print(f"{'='*70}\nANTHROPIC USAGE (job-wide, из сайдкаров)\n{'='*70}")
    for p in sorted(paths):
        d = load(p)
        if not d:
            print(f"  ⚠ не прочитан: {p}"); continue
        run = Path(p).parent.name
        r = d.get('cache_read_in', 0); c = d.get('cache_create_in', 0); f = d.get('fresh_in', 0)
        print(f"  {run:<40} calls={d.get('calls',0):<5} cache={fmt_ratio(r,c,f):4.1f}% "
              f"spent=${d.get('spent_usd',0):.2f}")
        for k in KEYS:
            agg[k] += d.get(k, 0) or 0
        for m, mv in (d.get('by_model') or {}).items():
            cur = by_model.setdefault(m, {'fresh': 0, 'read': 0, 'create': 0, 'output': 0, 'calls': 0, 'spent': 0.0})
            for kk in cur:
                cur[kk] += mv.get(kk, 0) or 0

    tot_in = agg['fresh_in'] + agg['cache_read_in'] + agg['cache_create_in']
    ratio = (agg['cache_read_in'] / tot_in * 100) if tot_in else 0.0
    print(f"\n  ИТОГО: {agg['calls']:,} вызовов | ${agg['spent_usd']:.2f} | input {tot_in:,} ток")
    print(f"  blended cache hit: {ratio:.1f}%  "
          f"({agg['cache_read_in']:,} read / {agg['cache_create_in']:,} write / {agg['fresh_in']:,} fresh)")

    if by_model:
        print(f"\n  ПО МОДЕЛЯМ (дорогие должны кэшироваться хорошо; низкий blended обычно = дешёвый Haiku с картинками):")
        for m, mv in sorted(by_model.items(), key=lambda kv: -kv[1]['spent']):
            mt = mv['fresh'] + mv['read'] + mv['create']
            print(f"     {m:<26} {mv['calls']:>5} calls | cache {fmt_ratio(mv['read'],mv['create'],mv['fresh']):4.1f}% "
                  f"({mv['read']:,}r/{mv['create']:,}w/{mv['fresh']:,}f) | ${mv['spent']:.2f}")
    print(f"\n  Памятка: картинки физически не кэшируются → blended-потолок ~30%. "
          f"Смотри на per-model: дорогой Opus должен быть высоким.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
