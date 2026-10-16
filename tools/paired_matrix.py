#!/usr/bin/env python3
"""ABBA device-task profiles of the complete local performance matrix.

Run after generating the matrix data, inside one bounded one-card reservation.
No operator-profiler replay. Keep all raw CSVs and input/binary/source hashes.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device',type=int,default=0)
    ap.add_argument('--baseline',required=True)
    ap.add_argument('--candidate',default='build/rope_runner')
    ap.add_argument('--label',required=True)
    ap.add_argument('--cases-file',default='tests/performance_cases.json')
    args=ap.parse_args()
    samples={'baseline':[],'candidate':[]}
    for i,variant in enumerate(['baseline','candidate','candidate','baseline']):
        label=f'{args.label}_{i}_{variant}'
        subprocess.run([sys.executable,str(ROOT/'tools/profile_matrix.py'),
                        '--device',str(args.device),'--binary',getattr(args,variant),
                        '--cases-file',args.cases_file,'--label',label],check=True)
        report=json.loads((ROOT/'benchmarks/profiles'/label/'matrix.json').read_text())
        samples[variant].append(report)
    harnesses={r.get('runner_sha256') for rounds in samples.values() for r in rounds}
    if len(harnesses)!=1:
        raise RuntimeError('Baseline/candidate were built with different test runners')
    results=[]
    for i,c in enumerate(samples['baseline'][0]['cases']):
        raw={k:[r['cases'][i]['task_us'] for r in v] for k,v in samples.items()}
        hashes=[r['cases'][i]['input_sha256'] for v in samples.values() for r in v]
        if any(h!=hashes[0] for h in hashes):
            raise RuntimeError('Input changed during paired profiling')
        base=statistics.median(raw['baseline']);cand=statistics.median(raw['candidate'])
        results.append(dict(name=c['name'],shape=c['shape'],dtype=c['dtype'],
                            baseline_us=base,candidate_us=cand,speedup=base/cand,
                            samples_us=raw,input_sha256=hashes[0]))
    report=dict(label=args.label,runner_sha256=next(iter(harnesses)),device=args.device,order=['baseline','candidate','candidate','baseline'],
                metric='msprof Task Duration(us), median of two per-process medians',
                per_profile_warmup=5,per_profile_samples=5,
                platform_hidden_cases_tested=False,cases=results,
                source_sha256={k:v[0]['source_sha256'] for k,v in samples.items()},
                binary_sha256={k:v[0]['binary_sha256'] for k,v in samples.items()})
    target=ROOT/'benchmarks/results'/f'{args.label}.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    for c in results:
        print(f"{c['name']}: {c['baseline_us']:.3f} -> {c['candidate_us']:.3f} us ({c['speedup']:.2f}x)")


if __name__=='__main__':
    main()
