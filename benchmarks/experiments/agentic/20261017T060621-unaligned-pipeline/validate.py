"""Frozen-input collection; collect must run through single-card task-submit.

Reuses all previous1625 inputs, original golden, thresholds, and source-bound
817f8364 outputs. Adds queue-reuse/tail cases without altering earlier files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
WORK=ROOT/'build/agentic_r5/validation'
PRIOR=ROOT/'benchmarks/experiments/agentic/20261017T053637875276Z-817f8364de18'
sys.path.insert(0,str(ROOT/'tools'))
from suite import generate,compare


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()


def prepare():
    old=json.loads((PRIOR/'validation_manifest.json').read_text())
    checks=json.loads((PRIOR/'correctness.json').read_text())['cases']
    by_name={(x['group'],x['case']['name']):x for x in checks}
    records=[]
    for r in old:
        r=dict(r);directory=Path(r['directory'])
        for name,h in r['hashes'].items(): assert sha(directory/name)==h
        r['parent_output']=str(ROOT/'build/agentic_r4/validation/output/parent'/r['group']/(r['case']['name']+'.bin'))
        r['parent_output_sha256']=by_name[r['group'],r['case']['name']]['output_sha256']['parent']
        assert sha(r['parent_output'])==r['parent_output_sha256']
        r['golden']=r.get('golden',str(directory/'golden.bin'))
        r['golden_sha256']=sha(r['golden']);r['reused_source_sha256']='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556'
        records.append(r)
    new=[]
    for d in [66,126,254,514,1022]:
        for dt in ['float16','float32']:
            for n in [1,49,257]:
                for h in [1,33,65]:
                    i=len(new);mode=i%4
                    new.append(dict(name=f'pipe_d{d}_{dt}_n{n}_h{h}',shape=[1,n,h,d],dtype=dt,
                                    pmax=1 if mode==0 else 131073,zero_every=2 if mode==1 else (48 if mode==2 else 0),
                                    extreme=True,special=True,seed=31000+i))
    for d in [126,254]:
        for dt in ['float16','float32']:
            for h in [3,65]:
                new.append(dict(name=f'long_d{d}_{dt}_h{h}',shape=[1,1025,h,d],dtype=dt,pmax=2,
                                zero_every=7,special=True,seed=32000+len(new)))
    for c in new:
        folder=WORK/'data'/c['name'];x,p,y=generate(c,folder,c['seed']);y.tofile(folder/'golden.bin')
        records.append(dict(group='pipeline_tails',case=c,directory=str(folder),golden=str(folder/'golden.bin'),
                            golden_sha256=sha(folder/'golden.bin'),hashes={n:sha(folder/n) for n in ['x.bin','positions.bin']},
                            parent_output=str(WORK/'output/parent/pipeline_tails'/(c['name']+'.bin'))))
    (HERE/'validation_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    groups=sorted(set(r['group'] for r in records))
    for variant in ['parent','direct','compact','pipeline']:
        for group in groups:
            if variant=='parent' and group!='pipeline_tails':continue
            output=WORK/'output'/variant/group;output.mkdir(parents=True,exist_ok=True);lines=[]
            for r in records:
                if r['group']!=group:continue
                c=r['case'];warmup,repeat=(1,2) if group=='pipeline_tails' else (0,1)
                lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],
                    '--theta',str(c.get('theta',10000)),'--input',r['directory'],'--output',str(output/(c['name']+'.bin')),
                    '--warmup',str(warmup),'--repeat',str(repeat),'--batches','1']))
            (WORK/f'{group}_{variant}.txt').write_text('\n'.join(lines)+'\n')
    print('Prepared',len(records),'cases; reused1625, new',len(new))


def collect(variant,group,device):
    binary=ROOT/('build/agentic_r2wide/candidate_audit_runner' if variant=='parent' else f'build/agentic_r5/{variant}_audit/rope_runner')
    meta=json.loads(Path(str(binary)+'.meta.json').read_text());assert sha(binary)==meta['binary_sha256']
    p=subprocess.run([str(binary),'--device',str(device),'--batch',str(WORK/f'{group}_{variant}.txt')],capture_output=True,text=True,timeout=50)
    (WORK/f'{group}_{variant}.log').write_text(p.stdout+p.stderr)
    if p.returncode:raise RuntimeError(p.stdout[-3000:]+p.stderr[-3000:])
    print(variant,group,'collected',sum(l.startswith('{') for l in p.stdout.splitlines()),flush=True)


def analyze(variant):
    records=json.loads((HERE/'validation_manifest.json').read_text());results=[];groups=sorted(set(r['group'] for r in records))
    for group in groups:
        rows=[json.loads(l) for l in (WORK/f'{group}_{variant}.log').read_text().splitlines() if l.startswith('{')]
        records_group=[r for r in records if r['group']==group];assert len(rows)==len(records_group)
        for r,timing in zip(records_group,rows):
            c=r['case'];data=Path(r['directory']);dt=c['dtype'];bits=np.uint16 if dt=='float16' else np.uint32
            for n,h in r['hashes'].items():assert sha(data/n)==h
            assert sha(r['golden'])==r['golden_sha256']
            actual_path=WORK/'output'/variant/group/(c['name']+'.bin');parent_path=Path(r['parent_output'])
            if 'parent_output_sha256' in r: assert sha(parent_path)==r['parent_output_sha256']
            a=np.fromfile(actual_path,dt).reshape(c['shape']);b=np.fromfile(parent_path,dt).reshape(c['shape']);g=np.fromfile(r['golden'],dt).reshape(c['shape'])
            p=np.fromfile(data/'positions.bin',np.int32).reshape(c['shape'][:2]);x=np.fromfile(data/'x.bin',dt).reshape(c['shape'])
            results.append(dict(group=group,case=c,output_bit_differences=int(np.count_nonzero(a.view(bits)!=b.view(bits))),
                output_sha256=sha(actual_path),parent_output_sha256=sha(parent_path),candidate=compare(a,g),parent=compare(b,g),
                zero_identity_ok=bool(np.array_equal(a[p==0].view(bits),x[p==0].view(bits))),timing=timing))
    meta=json.loads((ROOT/f'build/agentic_r5/{variant}_audit/rope_runner.meta.json').read_text())
    report=dict(variant=variant,**meta,total=len(results),bit_identical=sum(r['output_bit_differences']==0 for r in results),
                candidate_passed=sum(r['candidate']['passed'] for r in results),parent_passed=sum(r['parent']['passed'] for r in results),
                all_guard_identity_launch_checks_passed=all(r['timing']['guard_ok'] and r['zero_identity_ok'] and r['timing']['one_kernel_per_iteration'] and r['timing']['kernel_launches']==r['timing']['iterations'] for r in results),
                audited_calls=sum(r['timing']['iterations'] for r in results),failures=[r for r in results if not r['candidate']['passed'] or not r['parent']['passed']],cases=results)
    (HERE/f'{variant}_correctness.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['cases','failures']},indent=2))
    print('Failures:',[(x['case']['name'],x['parent'],x['candidate']) for x in report['failures']])
    if report['bit_identical']!=report['total'] or not report['all_guard_identity_launch_checks_passed']:raise SystemExit(1)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','collect','analyze']);ap.add_argument('--variant',choices=['parent','direct','compact','pipeline']);ap.add_argument('--group');ap.add_argument('--device',type=int,default=0);a=ap.parse_args()
    if a.action=='prepare':prepare()
    elif a.action=='collect':collect(a.variant,a.group,a.device)
    else:analyze(a.variant)
