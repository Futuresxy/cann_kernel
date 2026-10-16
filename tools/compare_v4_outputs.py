#!/usr/bin/env python3
"""Compare a candidate directly with V4; a new finite output bit is a failure.

Generate on CPU with --generate-only. Execute the comparison only inside a
bounded, single-device task-submit reservation. Both binaries use one runner.
NaN payloads may vary; finite numbers, infinities and signed zeros must match
bit for bit. Reference accuracy is reported separately and never relaxed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

import numpy as np

from suite import ROOT, compare, generate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', type=int, default=0)
    ap.add_argument('--baseline', default='build/rope_runner')
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--cases-file', required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--generate-only', action='store_true')
    args = ap.parse_args()
    cases = json.loads((ROOT / args.cases_file).read_text())
    folder = ROOT / 'build/output_comparisons' / args.label
    folder.mkdir(parents=True, exist_ok=True)
    # Generate both the input and its NumPy reference before reserving a card.
    if args.generate_only:
        for c in cases:
            dest = folder / c['name']
            _, _, golden = generate(c, dest, c['seed'])
            golden.tofile(dest / 'golden.bin')
        print(f'Prepared {len(cases)} comparisons in {folder}')
        return
    meta = {v: json.loads(Path(str(ROOT / getattr(args, v)) + '.meta.json').read_text())
            for v in ('baseline', 'candidate')}
    if meta['baseline']['runner_sha256'] != meta['candidate']['runner_sha256']:
        raise RuntimeError('Comparison requires identical runners')
    if meta['baseline']['source_sha256'] != '2acfbd5c205915280dfe6818d8217a78f08a9fb769ad3a1843b4f58a73eb3d58':
        raise RuntimeError('Baseline must be the exact platform-passing V4')
    timings = {}
    for variant in ('baseline', 'candidate'):
        binary = ROOT / getattr(args, variant)
        if sha(binary) != meta[variant]['binary_sha256']:
            raise RuntimeError('Binary changed after stamping')
        commands = []
        for c in cases:
            dest = folder / c['name']
            for name in ('x.bin', 'positions.bin', 'golden.bin'):
                if not (dest / name).exists():
                    raise RuntimeError('Run --generate-only before reserving a card')
            commands.append(shlex.join([
                '--shape', *map(str, c['shape']), '--dtype', c['dtype'],
                '--theta', str(c.get('theta', 10000)), '--input', str(dest),
                '--output', str(dest / (variant + '.bin')),
                '--warmup', '1', '--repeat', '1', '--batches', '1']))
        manifest = folder / (variant + '.txt')
        manifest.write_text('\n'.join(commands) + '\n')
        proc = subprocess.run([str(binary), '--device', str(args.device),
                               '--batch', str(manifest)], capture_output=True,
                              text=True, timeout=40)
        (folder / (variant + '.log')).write_text(proc.stdout + proc.stderr)
        proc.check_returncode()
        timings[variant] = [json.loads(line) for line in proc.stdout.splitlines()
                            if line.startswith('{')]
        if len(timings[variant]) != len(cases):
            raise RuntimeError('Incomplete batch')
    results = []
    for i, c in enumerate(cases):
        dest = folder / c['name']
        arrays = {v: np.fromfile(dest / (v + '.bin'), dtype=c['dtype'])
                  for v in ('baseline', 'candidate', 'golden')}
        if len({a.size for a in arrays.values()}) != 1:
            raise RuntimeError('Incomplete output')
        a, b = arrays['baseline'], arrays['candidate']
        bits = np.uint16 if a.dtype == np.float16 else np.uint32
        same = (a.view(bits) == b.view(bits)) | (np.isnan(a) & np.isnan(b))
        accuracy = {v: compare(arrays[v], arrays['golden'])
                    for v in ('baseline', 'candidate')}
        p = np.fromfile(dest / 'positions.bin', dtype=np.int32)
        x = np.fromfile(dest / 'x.bin', dtype=c['dtype']).reshape(p.size, -1)
        zero_ok = np.array_equal(b.reshape(p.size, -1)[p == 0].view(bits),
                                 x[p == 0].view(bits))
        result = dict(**c, output_bits_equal=bool(same.all()),
                      changed_elements=int((~same).sum()), elements=int(a.size),
                      reference_accuracy=accuracy, zero_identity_ok=bool(zero_ok),
                      input_sha256={n: sha(dest / n) for n in ('x.bin', 'positions.bin')},
                      guard_ok=all(timings[v][i]['guard_ok'] for v in timings))
        result['passed'] = (result['output_bits_equal'] and result['zero_identity_ok']
                            and result['guard_ok'] and all(r['passed'] for r in accuracy.values()))
        results.append(result)
        if not result['passed']:
            print(json.dumps(result), flush=True)
    report = dict(label=args.label, device=args.device,
                  acceptance='Exact V4 output bits (NaN payload excluded), unchanged contest reference thresholds',
                  source_sha256={v: m['source_sha256'] for v, m in meta.items()},
                  binary_sha256={v: m['binary_sha256'] for v, m in meta.items()},
                  runner_sha256=meta['baseline']['runner_sha256'], cases=results,
                  platform_hidden_cases_tested=False)
    (ROOT / 'benchmarks/results' / (args.label + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(f"V4 output comparison: {sum(r['passed'] for r in results)}/{len(results)} passed; "
          f"{sum(r['changed_elements'] for r in results)} changed elements")
    if not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
