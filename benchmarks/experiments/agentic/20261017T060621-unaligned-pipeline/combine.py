"""CPU-only combination of unchanged profile_paired.py source-order runs."""
import argparse
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[4]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--label',required=True);args=ap.parse_args()
    reports={v:json.loads((ROOT/'benchmarks/results'/f'{args.label}_{v}.json').read_text()) for v in ['forward','reverse']}
    a,b=reports['forward'],reports['reverse'];assert a['runner_sha256']==b['runner_sha256']
    assert a['source_sha256']['baseline']==b['source_sha256']['candidate']
    assert a['source_sha256']['candidate']==b['source_sha256']['baseline']
    cases=[]
    for x,y in zip(a['cases'],b['cases']):
        assert x['name']==y['name'] and x['input_sha256']==y['input_sha256']
        samples={v:[r['task_us'] for r in x['blocks'] if r['variant']==v]+[r['task_us'] for r in y['blocks'] if r['variant']!=v] for v in ['baseline','candidate']}
        old=statistics.median(samples['baseline']);new=statistics.median(samples['candidate'])
        cases.append(dict(name=x['name'],shape=x['shape'],dtype=x['dtype'],baseline_us=old,candidate_us=new,speedup=old/new,
            latency_change_percent=100*(new/old-1),block_medians_us=samples,input_sha256=x['input_sha256'],
            direction_adjusted_speedup=dict(forward=x['baseline_us']/x['candidate_us'],reverse=y['candidate_us']/y['baseline_us'])))
    report=dict(label=args.label,source_sha256=a['source_sha256'],runner_sha256=a['runner_sha256'],
        metric='Native non-replay Task Duration; median of four block medians from shared-allocation ABBA and BAAB',
        shared_context_and_addresses_within_each_process=True,source_orders_reversed=True,
        run_kernel_calls=sum(r['run_kernel_calls'] for r in reports.values()),actual_device_kernel_tasks=sum(r['actual_device_kernel_tasks'] for r in reports.values()),
        profile_labels={v:r['label'] for v,r in reports.items()},geometric_mean_speedup=math.exp(statistics.mean(math.log(r['speedup']) for r in cases)),cases=cases)
    (ROOT/'benchmarks/results'/f'{args.label}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(args.label,'geomean',report['geometric_mean_speedup'])
    for c in cases:
        if 'unaligned' in c['name'] or 'pipeperf' in c['name']:print(c['name'],c['baseline_us'],c['candidate_us'],c['speedup'],c['direction_adjusted_speedup'])


if __name__=='__main__': main()
