"""Offline preparation/comparison; run collection only through task-submit.

Imports the unchanged local golden and thresholds. Neither belongs to payload.
The parent and experiment read exactly the same frozen input files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
WORK = ROOT / 'build/agentic_r4/validation'
sys.path.insert(0, str(ROOT / 'tools'))
from suite import generate, compare


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare():
    groups = {'base': json.loads((ROOT / 'tests/cases.json').read_text()),
              'math': json.loads((ROOT / 'tests/round6_math_cases.json').read_text()),
              'dispatch': json.loads((ROOT / 'tests/round8_dispatch_precision_cases.json').read_text())}
    sweep = [dict(name=f'even_{d}_{dt}', shape=[1, 4, 3, d], dtype=dt,
                  pmax=131073, extreme=True, special=True, zero_every=3)
             for d in range(16, 1025, 2) for dt in ['float16', 'float32']]
    for i in range(0, len(sweep), 260):
        groups[f'sweep{i // 260}'] = sweep[i:i+260]
    groups['tails'] = [dict(name=f'tail_{d}_{h}_{dt}', shape=[1, 137, h, d],
                           dtype=dt, pmax=131073, extreme=True, special=True, zero_every=7)
                       for d in [66, 126, 130, 254, 258, 510, 514, 770, 1022]
                       for h in [1, 3, 33] for dt in ['float16', 'float32']]
    # Exercise scalar frequency dispatch, near-unity conditioning, cancellation.
    groups['conditioning'] = [dict(name=f'cond_{d}_{j}_{dt}', shape=[1, 17, 3, d],
                                  dtype=dt, theta=t, pmax=131073, extreme=True,
                                  zero_every=7, distribution='cancellation')
                              for d in [66, 126, 254, 514, 1022]
                              for j, t in enumerate([0.5, 1, 0.99999994, 1.000000119, 1000, 500000])
                              for dt in ['float16', 'float32']]
    records = []
    for group, cases in groups.items():
        for index, case in enumerate(cases):
            dest = WORK / 'data' / group / case['name']
            x, p, golden = generate(case, dest, case.get('seed', 42+index))
            golden.tofile(dest / 'golden.bin')
            records.append(dict(group=group, case=case, directory=str(dest),
                                hashes={n: sha(dest/n) for n in ['x.bin', 'positions.bin', 'golden.bin']}))
    # Do not regenerate the already diagnosed failure or its inputs.
    case = dict(name='frozen_amplitude', shape=[1,137,17,1024], dtype='float16', theta=10000)
    dest = ROOT / 'build/rope_v9_system/input'
    x = np.fromfile(dest/'x.bin', np.float16).reshape(case['shape'])
    p = np.fromfile(dest/'positions.bin', np.int32).reshape(case['shape'][:2])
    d = case['shape'][-1]
    freq = np.float32(1) / np.power(np.float32(10000), np.arange(0,d,2,dtype=np.float32)/np.float32(d))
    angle = p.astype(np.float32)[...,None] * freq
    c = np.cos(angle)[...,None,:]; s = np.sin(angle)[...,None,:]
    a=x[...,:d//2].astype(np.float32); b=x[...,d//2:].astype(np.float32)
    with np.errstate(invalid='ignore', over='ignore'):
        y=np.concatenate((a*c-b*s, b*c+a*s),axis=-1).astype(x.dtype)
    y[p==0] = x[p==0]
    frozen = WORK/'frozen_golden.bin'; y.tofile(frozen)
    records.append(dict(group='amplitude', case=case, directory=str(dest), golden=str(frozen),
                        hashes={n:sha(dest/n) for n in ['x.bin','positions.bin']}))
    (HERE/'validation_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    for group in sorted(set(r['group'] for r in records)):
        for variant in ['parent','candidate']:
            output = WORK/'output'/variant/group; output.mkdir(parents=True,exist_ok=True)
            lines=[]
            for r in records:
                if r['group'] != group: continue
                c=r['case']
                lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],
                    '--theta',str(c.get('theta',10000)),'--input',r['directory'],
                    '--output',str(output/(c['name']+'.bin')),'--warmup','0','--repeat','1','--batches','1']))
            (WORK/f'{group}_{variant}.txt').write_text('\n'.join(lines)+'\n')
    print('Prepared',len(records),'frozen cases:',{g:sum(r['group']==g for r in records) for g in sorted(groups)} )


def collect(group, variant, device):
    binary = ROOT/('build/agentic_r2wide/candidate_audit_runner' if variant=='parent' else 'build/agentic_r4/audit/rope_runner')
    meta=json.loads(Path(str(binary)+'.meta.json').read_text())
    assert sha(binary)==meta['binary_sha256']
    proc=subprocess.run([str(binary),'--device',str(device),'--batch',str(WORK/f'{group}_{variant}.txt')],
                        capture_output=True,text=True,timeout=50)
    (WORK/f'{group}_{variant}.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode: raise RuntimeError(proc.stdout[-2000:]+proc.stderr[-2000:])
    print(group,variant,'collected',sum(x.startswith('{') for x in proc.stdout.splitlines()))


def analyze():
    records=json.loads((HERE/'validation_manifest.json').read_text()); results=[]
    for group in sorted(set(r['group'] for r in records)):
        timings={v:[json.loads(line) for line in (WORK/f'{group}_{v}.log').read_text().splitlines() if line.startswith('{')]
                 for v in ['parent','candidate']}
        subset=[r for r in records if r['group']==group]
        assert all(len(t)==len(subset) for t in timings.values())
        for i,r in enumerate(subset):
            c=r['case']; data=Path(r['directory']); golden=np.fromfile(r.get('golden',str(data/'golden.bin')),dtype=c['dtype']).reshape(c['shape'])
            outputs={v:np.fromfile(WORK/'output'/v/group/(c['name']+'.bin'),dtype=c['dtype']).reshape(c['shape']) for v in timings}
            bits=np.uint16 if c['dtype']=='float16' else np.uint32
            p=np.fromfile(data/'positions.bin',np.int32).reshape(c['shape'][:2]); x=np.fromfile(data/'x.bin',dtype=c['dtype']).reshape(c['shape'])
            assert all(sha(data/n)==h for n,h in r['hashes'].items())
            entries={v:dict(**compare(a,golden),**timings[v][i],zero_identity_ok=bool(np.array_equal(a[p==0].view(bits),x[p==0].view(bits)))) for v,a in outputs.items()}
            results.append(dict(group=group,case=c,output_bit_differences=int(np.count_nonzero(outputs['parent'].view(bits)!=outputs['candidate'].view(bits))),
                                output_sha256={v:sha(WORK/'output'/v/group/(c['name']+'.bin')) for v in timings},variants=entries))
    summary=dict(total=len(results),bit_identical_cases=sum(r['output_bit_differences']==0 for r in results),
                 parent_passed=sum(r['variants']['parent']['passed'] for r in results),candidate_passed=sum(r['variants']['candidate']['passed'] for r in results),
                 failures=[dict(group=r['group'],case=r['case'],variants=r['variants']) for r in results if not all(v['passed'] for v in r['variants'].values())],
                 all_zero_identity_guards_launches_passed=all(v['guard_ok'] and v['zero_identity_ok'] and v['one_kernel_per_iteration'] and v['kernel_launches']==v['iterations']==1 for r in results for v in r['variants'].values()),
                 cases=results)
    (HERE/'correctness.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'},indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','collect','analyze']);ap.add_argument('--group');ap.add_argument('--variant',choices=['parent','candidate']);ap.add_argument('--device',type=int,default=0)
    args=ap.parse_args()
    if args.action=='prepare': prepare()
    elif args.action=='collect': collect(args.group,args.variant,args.device)
    else: analyze()
