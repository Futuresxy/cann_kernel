#!/usr/bin/env python3
"""Combine shared-allocation ABBA and BAAB profiles to balance order effects."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', type=int, default=0)
    ap.add_argument('--forward-binary', required=True)
    ap.add_argument('--reverse-binary', required=True)
    ap.add_argument('--cases-file', default='tests/round3_performance_cases.json')
    ap.add_argument('--label', required=True)
    args = ap.parse_args()
    reports = {}
    for direction in ('forward', 'reverse'):
        label = args.label + '_' + direction
        subprocess.run([sys.executable, str(ROOT/'tools/profile_paired.py'),
                        '--device', str(args.device), '--binary', getattr(args, direction+'_binary'),
                        '--cases-file', args.cases_file, '--label', label], check=True)
        reports[direction] = json.loads((ROOT/'benchmarks/results'/f'{label}.json').read_text())
    forward, reverse = reports['forward'], reports['reverse']
    if forward['runner_sha256'] != reverse['runner_sha256']:
        raise RuntimeError('Forward/reverse runs use different harnesses')
    if any(forward['source_sha256'][v] != reverse['source_sha256'][other]
           for v, other in [('baseline', 'candidate'), ('candidate', 'baseline')]):
        raise RuntimeError('The reverse build must swap the two kernel sources')
    cases = []
    for a, b in zip(forward['cases'], reverse['cases']):
        if a['name'] != b['name'] or a['input_sha256'] != b['input_sha256']:
            raise RuntimeError('The inputs or case order changed between runs')
        samples = {v: [block['task_us'] for block in a['blocks'] if block['variant']==v] +
                      [block['task_us'] for block in b['blocks'] if block['variant']!=v]
                   for v in ('baseline', 'candidate')}
        baseline = statistics.median(samples['baseline'])
        candidate = statistics.median(samples['candidate'])
        cases.append(dict(name=a['name'], shape=a['shape'], dtype=a['dtype'],
                          baseline_us=baseline, candidate_us=candidate, speedup=baseline/candidate,
                          block_medians_us=samples, input_sha256=a['input_sha256']))
    report = dict(label=args.label, device=args.device, source_sha256=forward['source_sha256'],
                  runner_sha256=forward['runner_sha256'],
                  metric='Median of four block medians from shared-allocation ABBA and BAAB',
                  order=['baseline','candidate','candidate','baseline','candidate','baseline','baseline','candidate'],
                  shared_context_and_allocations_within_each_process=True,
                  run_kernel_calls=sum(r['run_kernel_calls'] for r in reports.values()),
                  actual_device_kernel_tasks=sum(r['actual_device_kernel_tasks'] for r in reports.values()),
                  profile_labels={k:r['label'] for k,r in reports.items()}, cases=cases,
                  platform_hidden_cases_tested=False)
    (ROOT/'benchmarks/results'/f'{args.label}.json').write_text(json.dumps(report, indent=2)+'\n')
    for c in cases:
        print(f"{c['name']}: {c['baseline_us']:.3f} -> {c['candidate_us']:.3f} us ({c['speedup']:.2f}x)")


if __name__ == '__main__':
    main()
