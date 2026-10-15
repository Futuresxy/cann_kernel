#!/usr/bin/env python3
"""Compare native timings and keep profiler evidence separate from event timings."""
import argparse,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('baseline');ap.add_argument('candidate');args=ap.parse_args()
def load(name):return json.loads((root/'benchmarks/results'/f'{name}.json').read_text())
b=load(args.baseline);c=load(args.candidate);base={r['name']:r for r in b['cases']}
print('| 用例 | 基线 us | 候选 us | 加速比 | 精度 |')
print('|---|---:|---:|---:|---|')
for r in c['cases']:
    if r['name'] not in base:continue
    v=base[r['name']]['event_us']
    print(f"| {r['name']} | {v:.3f} | {r['event_us']:.3f} | {v/r['event_us']:.2f}× | {'PASS' if r['passed'] else 'FAIL'} |")
if not all(r['passed'] for r in c['cases']):raise SystemExit(1)
