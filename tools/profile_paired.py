#!/usr/bin/env python3
"""ABBA profiling in one context with identical allocations for both revisions.

Each case launches four blocks (A, B, B, A), each with five warmup and five
measured calls. One msprof process, no replay. Reserve a single device first.
"""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', type=int, default=0)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--cases-file', default='tests/performance_cases.json')
    args = ap.parse_args()
    binary = ROOT / args.binary
    meta = json.loads(Path(str(binary) + '.meta.json').read_text())
    if sha(binary) != meta['binary_sha256'] or sha(ROOT / 'tests/paired_runner.asc') != meta['runner_sha256']:
        raise RuntimeError('Paired binary or runner changed; rebuild and stamp')
    for name, path in meta['source_paths'].items():
        if sha(Path(path)) != meta['source_sha256'][name]:
            raise RuntimeError('A kernel changed after the paired build')
    cases = json.loads((ROOT / args.cases_file).read_text())
    folder = ROOT / 'build/paired_profiles' / args.label
    folder.mkdir(parents=True, exist_ok=True)
    commands = []
    for c in cases:
        data = ROOT / 'build/data' / c['name']
        if not (data / 'x.bin').exists():
            raise RuntimeError('Generate inputs on CPU before reserving a card')
        commands.append(shlex.join([
            '--shape', *map(str, c['shape']), '--dtype', c['dtype'],
            '--theta', str(c.get('theta', 10000)), '--input', str(data),
            '--output', str(folder / (c['name'] + '.bin')),
            '--warmup', '5', '--repeat', '5', '--batches', '4']))
    manifest = folder / 'cases.txt'
    manifest.write_text('\n'.join(commands) + '\n')
    command = ['msprof', '--output=' + str(folder), '--runtime-api=on',
               '--task-time=on', '--ai-core=off', '--aicpu=off', '--type=text',
               '--application=' + shlex.join([str(binary), '--device', str(args.device), '--batch', str(manifest)])]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
    (folder / 'collection.log').write_text(proc.stdout)
    if proc.returncode:
        raise RuntimeError(proc.stdout[-5000:])
    profiles = sorted(folder.glob('PROF_*'))
    summaries = list(profiles[-1].rglob('op_summary_*.csv')) if profiles else []
    if len(summaries) != 1:
        raise RuntimeError('Expected one single-device summary')
    rows = list(csv.DictReader(summaries[0].open()))
    rows.sort(key=lambda r: Decimal(r['Task Start Time(us)'].strip()))
    if len(rows) != 40 * len(cases):
        raise RuntimeError(f'Expected {40 * len(cases)} kernel tasks; got {len(rows)}')
    order = ['baseline', 'candidate', 'candidate', 'baseline']
    names = {'baseline': 'r5_base', 'candidate': 'r5_test'}
    results = []
    for i, case in enumerate(cases):
        blocks = []
        for b, variant in enumerate(order):
            group = rows[i * 40 + b * 10:i * 40 + (b + 1) * 10]
            if any(names[variant] not in r['Op Name'] or 'kernel' not in r['Op Name'] for r in group):
                raise RuntimeError('Task order differs from the expected ABBA kernel calls')
            samples = [float(r['Task Duration(us)']) for r in group[5:]]
            blocks.append(dict(variant=variant, task_us=statistics.median(samples), samples_us=samples))
        baseline = statistics.median(b['task_us'] for b in blocks if b['variant'] == 'baseline')
        candidate = statistics.median(b['task_us'] for b in blocks if b['variant'] == 'candidate')
        data = ROOT / 'build/data' / case['name']
        results.append(dict(**case, baseline_us=baseline, candidate_us=candidate,
                            speedup=baseline / candidate, blocks=blocks,
                            input_sha256={n: sha(data / n) for n in ('x.bin', 'positions.bin')}))
    target = ROOT / 'benchmarks/profiles' / args.label
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(summaries[0], target / 'op_summary.csv')
    report = dict(label=args.label, device=args.device, command=command, **meta,
                  order=order, shared_context_and_allocations=True,
                  per_block_warmup=5, per_block_samples=5,
                  actual_device_kernel_tasks=len(rows), run_kernel_calls=40 * len(cases),
                  platform_hidden_cases_tested=False, cases=results)
    (target / 'paired.json').write_text(json.dumps(report, indent=2) + '\n')
    (ROOT / 'benchmarks/results' / (args.label + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    for c in results:
        print(f"{c['name']}: {c['baseline_us']:.3f} -> {c['candidate_us']:.3f} us ({c['speedup']:.2f}x)")


if __name__ == '__main__':
    main()
