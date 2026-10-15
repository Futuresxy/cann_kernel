#!/usr/bin/env python3
"""Count device tasks with msprof, without operator-profiler kernel replay.

15 representative local cases x 5 calls = 75 expected AI Vector kernels.
Two cases have dim > 512, reproducing the former 85-launch failure. These
are local regression cases, not the platform's undisclosed 15 cases.
Run only inside a short, single-device task-submit reservation.
"""
import argparse
import csv
import hashlib
import json
import pathlib
import shlex
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = [
    'template', 'tiny', 'odd_stride_fp32', 'unaligned_half',
    'deepseek_half', 'deepseek_float', 'extreme_d1024', 'extreme_d64',
    'dim18', 'dim30', 'dim514', 'batch128', 'sequence8192', 'heads256',
    'aligned_d512_fp32',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--binary', default='build/rope_runner_single_launch_v3')
    parser.add_argument('--label', required=True)
    parser.add_argument('--expected-launches', type=int, default=75)
    args = parser.parse_args()
    cases = {c['name']: c for c in json.loads((ROOT/'tests/cases.json').read_text())}
    folder = ROOT/'build/launch_profiles'/args.label
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder/'cases.txt'
    lines = []
    for name in NAMES:
        case = cases[name]
        data = ROOT/'build/data'/name
        if not (data/'x.bin').exists():
            raise RuntimeError('Generate suite data before profiling')
        lines.append(shlex.join([
            '--shape', *map(str, case['shape']), '--dtype', case['dtype'],
            '--theta', str(case.get('theta', 10000)), '--input', str(data),
            '--output', str(folder/(name+'.bin')),
            '--warmup', '0', '--repeat', '5', '--batches', '1',
        ]))
    manifest.write_text('\n'.join(lines)+'\n')
    binary = ROOT/args.binary
    command = [
        'msprof', '--output='+str(folder), '--runtime-api=on', '--task-time=on',
        '--ai-core=off', '--aicpu=off', '--type=text',
        '--application='+shlex.join([
            str(binary), '--device', str(args.device), '--batch', str(manifest),
        ]),
    ]
    process = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=45)
    (folder/'collection.log').write_text(process.stdout)
    if process.returncode:
        raise RuntimeError(process.stdout[-8000:])
    profiles = sorted(folder.glob('PROF_*'))
    if not profiles:
        raise RuntimeError('msprof produced no profile directory')
    summaries = list(profiles[-1].rglob('op_summary_*.csv'))
    if len(summaries) != 1:
        raise RuntimeError('Expected one single-device operator summary: '+str(summaries))
    rows = list(csv.DictReader(summaries[0].open()))
    # op_summary contains operator/kernel tasks, excluding event records and DMA.
    if not rows or 'Op Name' not in rows[0]:
        raise RuntimeError('Unexpected operator summary schema')
    if any('kernel' not in row['Op Name'] for row in rows):
        raise RuntimeError('Unexpected non-RoPE operator in isolated profile')
    count = len(rows)
    destination = ROOT/'benchmarks/profiles'/args.label
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(summaries[0], destination/'op_summary.csv')
    metadata = json.loads(pathlib.Path(str(binary)+'.meta.json').read_text())
    summary = dict(
        label=args.label, source_sha256=metadata['source_sha256'],
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        local_cases=NAMES, case_count=len(NAMES), calls_per_case=5,
        run_kernel_calls=len(NAMES)*5, actual_device_kernel_tasks=count,
        expected_device_kernel_tasks=args.expected_launches,
        single_kernel_rule_passed=count==len(NAMES)*5,
        command=command, platform_hidden_cases_tested=False,
    )
    (destination/'launch_count.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))
    if count != args.expected_launches:
        raise SystemExit(f'Expected {args.expected_launches} kernel tasks, got {count}')


if __name__ == '__main__':
    main()
