#!/usr/bin/env python3
"""Profile complete shape/dtype matrices without operator-profiler replay.

One ACL process, one device, sequential cases, ten launches per case. The
first five are warmup; medians of the next five are device task durations.
Must run through a bounded single-card task-submit reservation.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', type=int, default=0)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--cases-file', default='tests/performance_cases.json')
    args = ap.parse_args()
    cases = json.loads((ROOT/args.cases_file).read_text())
    folder = ROOT/'build/matrix_profiles'/args.label
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder/'cases.txt'
    commands = []
    for c in cases:
        data = ROOT/'build/data'/c['name']
        if not (data/'x.bin').exists():
            raise RuntimeError('Generate inputs before reserving a device')
        commands.append(shlex.join([
            '--shape', *map(str, c['shape']), '--dtype', c['dtype'],
            '--theta', str(c.get('theta', 10000)), '--input', str(data),
            '--output', str(folder/(c['name']+'.bin')),
            '--warmup', '5', '--repeat', '5', '--batches', '1',
        ]))
    manifest.write_text('\n'.join(commands)+'\n')
    binary = ROOT/args.binary
    command = ['msprof', '--output='+str(folder), '--runtime-api=on',
               '--task-time=on', '--ai-core=off', '--aicpu=off', '--type=text',
               '--application='+shlex.join([
                   str(binary), '--device', str(args.device), '--batch', str(manifest)])]
    run = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=45)
    (folder/'collection.log').write_text(run.stdout)
    if run.returncode:
        raise RuntimeError(run.stdout[-6000:])
    profiles = sorted(folder.glob('PROF_*'))
    if not profiles:
        raise RuntimeError('No profiling output')
    summaries = list(profiles[-1].rglob('op_summary_*.csv'))
    if len(summaries) != 1:
        raise RuntimeError('Expected one single-device operator summary')
    rows = list(csv.DictReader(summaries[0].open()))
    if len(rows) != len(cases)*10 or any('kernel' not in r['Op Name'] for r in rows):
        raise RuntimeError('Each invocation must generate exactly one RoPE device task')
    rows.sort(key=lambda r: float(r['Task Start Time(us)']))
    results = []
    for i, c in enumerate(cases):
        group = rows[i*10:(i+1)*10]
        samples = [float(r['Task Duration(us)']) for r in group[5:]]
        duration = statistics.median(samples)
        elements = 1
        for d in c['shape']:
            elements *= d
        minimum_bytes = 2*elements*(2 if c['dtype']=='float16' else 4)
        data=ROOT/'build/data'/c['name']
        input_hashes={name:hashlib.sha256((data/name).read_bytes()).hexdigest()
                      for name in ['x.bin','positions.bin']}
        results.append(dict(**c, input_sha256=input_hashes, task_us=duration, samples_us=samples,
                            kernel=group[0]['Op Name'],
                            minimum_io_gbs=minimum_bytes/(duration*1000)))
    dest = ROOT/'benchmarks/profiles'/args.label
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(summaries[0], dest/'op_summary.csv')
    meta = json.loads(Path(str(binary)+'.meta.json').read_text())
    report = dict(label=args.label, source_sha256=meta['source_sha256'],
                  binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  command=command, run_kernel_calls=len(cases)*10,
                  actual_device_kernel_tasks=len(rows), cases=results,
                  platform_hidden_cases_tested=False)
    (dest/'matrix.json').write_text(json.dumps(report, indent=2)+'\n')
    for r in results:
        print(f"{r['name']}: {r['task_us']:.3f} us, IO >= {r['minimum_io_gbs']:.1f} GB/s")


if __name__ == '__main__':
    main()
