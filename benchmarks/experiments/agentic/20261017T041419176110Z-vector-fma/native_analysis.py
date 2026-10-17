"""Summarize the two prespecified native paired timing runs; CPU-only."""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
LABELS=['agentic_r2_accum_balanced','agentic_r2_accum_confirm']
reports=[json.loads((ROOT/'benchmarks/results'/f'{label}.json').read_text()) for label in LABELS]
assert all(r['run_kernel_calls']==r['actual_device_kernel_tasks']==2640 for r in reports)
assert all(r['source_sha256']==reports[0]['source_sha256'] for r in reports)
for a,b in zip(reports[0]['cases'],reports[1]['cases']):
    assert a['name']==b['name'] and a['input_sha256']==b['input_sha256']
baseline=np.array([sum([r['cases'][i]['block_medians_us']['baseline'] for r in reports],[]) for i in range(33)])
candidate=np.array([sum([r['cases'][i]['block_medians_us']['candidate'] for r in reports],[]) for i in range(33)])
def geomean(values):return float(np.exp(np.mean(np.log(values))))
rng=np.random.default_rng(174317)
# Corresponding entries pair adjacent A/B blocks in each direction. Resample
# the eight observed block pairs separately within each fixed local shape.
indices=rng.integers(0,8,(20000,33,8))
b=np.median(np.take_along_axis(baseline[None,:,:],indices,axis=2),axis=2)
c=np.median(np.take_along_axis(candidate[None,:,:],indices,axis=2),axis=2)
samples=np.exp(np.mean(np.log(b/c),axis=1))
rows=[]
for i,case in enumerate(reports[0]['cases']):
    old=float(np.median(baseline[i]));new=float(np.median(candidate[i]))
    rows.append(dict(name=case['name'],shape=case['shape'],dtype=case['dtype'],baseline_us=old,candidate_us=new,speedup=old/new,per_run_speedups=[r['cases'][i]['speedup'] for r in reports],input_sha256=case['input_sha256']))
result=dict(source_sha256=reports[0]['source_sha256'],metric='Native non-replay Task Duration, fixed inputs, shared-context/allocation ABBA+BAAB, two repetitions',report_paths=[f'benchmarks/results/{label}.json' for label in LABELS],report_sha256={label:hashlib.sha256((ROOT/'benchmarks/results'/f'{label}.json').read_bytes()).hexdigest() for label in LABELS},run_kernel_calls=5280,actual_device_kernel_tasks=5280,per_run_geometric_speedups=[geomean([case['speedup'] for case in r['cases']]) for r in reports],pooled_eight_block_median_geometric_speedup=geomean([case['speedup'] for case in rows]),bootstrap=dict(method='20,000 paired-within-shape block resamples; median per variant then geometric mean across fixed33',seed=174317,percentile_95_interval=np.quantile(samples,[.025,.975]).tolist(),resamples_with_speedup_above_one=float(np.mean(samples>1)),caveat='Descriptive uncertainty of the observed blocks only, not a guarantee of independent samples or coverage of systematic/address/layout effects.'),cases=rows,decision='no_improvement',reason='The small overall positive estimates are not a robust improvement: the descriptive interval includes one, several small/control cases regress in both repetitions, and wide FP16 vector activity is essentially unchanged. No new candidate is published.')
path=Path(__file__).with_name('native_analysis.json');path.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['cases','report_sha256']},indent=2))
