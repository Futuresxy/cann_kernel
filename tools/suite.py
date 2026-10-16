#!/usr/bin/env python3
"""Deterministic correctness gate and bounded single-device measurement."""
import argparse, hashlib, json, os, pathlib, subprocess, time
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
def generate(case, dest, seed):
    rng=np.random.default_rng(seed)
    scale=case.get('scale',10)
    x=rng.uniform(-scale,scale,case['shape']).astype(case['dtype'])
    p=rng.integers(0,case['pmax'],case['shape'][:2],dtype=np.int32)
    if case.get('extreme'): p.flat[:min(4,p.size)]=[131072,131071,65536,0][:min(4,p.size)]
    if case.get('zero_every'): p.flat[::case['zero_every']]=0
    if case.get('special'): x.flat[:4]=[np.nan,np.inf,-np.inf,-0.0]
    d=x.shape[-1]
    exponent=np.arange(0,d,2,dtype=np.float32)/np.float32(d)
    freq=np.float32(1)/np.power(np.float32(case.get('theta',10000)),exponent)
    angle=p.astype(np.float32)[...,None]*freq
    c=np.cos(angle)[...,None,:]; s=np.sin(angle)[...,None,:]
    a=x[...,:d//2].astype(np.float32);b=x[...,d//2:].astype(np.float32)
    with np.errstate(invalid='ignore',over='ignore'):
        y=np.concatenate((a*c-b*s,b*c+a*s),axis=-1).astype(x.dtype)
    y[p==0]=x[p==0] # Explicit position-zero identity required by the specification.
    dest.mkdir(parents=True,exist_ok=True)
    x.tofile(dest/'x.bin');p.tofile(dest/'positions.bin')
    return x,p,y

def compare(actual,golden):
    a=actual.astype(np.float32);g=golden.astype(np.float32)
    atol,rtol,limit=(9.77e-4,1.53e-5,1e-2) if golden.dtype==np.float32 else (1.95e-3,1.95e-3,1e-1)
    finite=np.isfinite(g)&np.isfinite(a)
    diff=np.abs(a[finite]-g[finite]);match=np.zeros(a.shape,dtype=bool)
    match[finite]=diff<=atol+rtol*np.abs(g[finite])
    match|=(np.isnan(a)&np.isnan(g))|(np.isposinf(a)&np.isposinf(g))|(np.isneginf(a)&np.isneginf(g))
    maxerr=float(diff.max(initial=0))
    if np.any(np.isfinite(a)!=np.isfinite(g)):maxerr=float('inf')
    ratio=float(match.mean())
    return dict(passed=ratio>=.99 and maxerr<=limit,matched_ratio=ratio,max_abs_error=maxerr)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--device',type=int,default=0)
    ap.add_argument('--label',default='current');ap.add_argument('--cases',default='all')
    ap.add_argument('--binary',default='build/rope_runner');ap.add_argument('--generate-only',action='store_true')
    ap.add_argument('--repeat',type=int,default=30);ap.add_argument('--batches',type=int,default=3)
    ap.add_argument('--sweep',action='store_true');ap.add_argument('--warmup',type=int,default=5)
    ap.add_argument('--packed-sweep',action='store_true')
    ap.add_argument('--cases-file',default='tests/cases.json')
    args=ap.parse_args();all_cases=json.loads((ROOT/args.cases_file).read_text())
    if args.sweep:
        all_cases=[dict(name=f'sweep_{d}_{dt}',shape=[1,4,3,d],dtype=dt,pmax=131073,extreme=True)
                   for d in range(16,1025,2) for dt in ['float16','float32']]
    if args.packed_sweep:
        all_cases=[dict(name=f'packed_sweep_{d}_{dt}_h{h}',shape=[1,137,h,d],dtype=dt,
                        pmax=131073,extreme=True,special=True,zero_every=7)
                   for d in range(16,129,2) for dt in ['float16','float32'] for h in [1,3,7,32]]
    cases=all_cases
    if args.cases!='all':
        requested=set(args.cases.split(','));known={c['name'] for c in cases}
        if requested-known:ap.error('Unknown cases: '+','.join(sorted(requested-known)))
        cases=[c for c in cases if c['name'] in requested]
    results=[];start=time.time()
    meta_path=pathlib.Path(str(ROOT/args.binary)+'.meta.json')
    meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
    source_sha=meta.get('source_sha256',hashlib.sha256((ROOT/'operators/rotary_pos_emb/kernel.asc').read_bytes()).hexdigest())
    binary_sha=None if args.generate_only else hashlib.sha256((ROOT/args.binary).read_bytes()).hexdigest()
    prepared=[];commands=[]
    for case in cases:
        dest=ROOT/'build/data'/case['name']
        x,p,y=generate(case,dest,case.get('seed',42+all_cases.index(case)))
        if args.generate_only:continue
        prepared.append((case,dest,y))
        cmd=['--shape',*map(str,case['shape']),'--dtype',case['dtype'],
             '--theta',str(case.get('theta',10000)),'--input',str(dest),
             '--output',str(dest/'actual.bin'),'--repeat',str(args.repeat),
             '--batches',str(args.batches),'--warmup',str(args.warmup)]
        commands.append(' '.join(cmd))
    if not args.generate_only:
        manifest=ROOT/'build'/f'batch_{args.label}.txt'
        manifest.write_text('\n'.join(commands)+'\n')
        cmd=[str(ROOT/args.binary),'--device',str(args.device),'--batch',str(manifest)]
        proc=subprocess.run(cmd,text=True,capture_output=True,timeout=85)
        if proc.returncode:
            print(proc.stdout[-6000:],proc.stderr[-6000:],flush=True);raise RuntimeError('batch runner failed')
        timings=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
        if len(timings)!=len(prepared):raise RuntimeError('runner result count mismatch')
        for (case,dest,y),timing in zip(prepared,timings):
            actual=np.fromfile(dest/'actual.bin',dtype=case['dtype']).reshape(y.shape)
            result={**case,**timing,**compare(actual,y)}
            zero=np.fromfile(dest/'positions.bin',dtype=np.int32).reshape(case['shape'][:2])==0
            x=np.fromfile(dest/'x.bin',dtype=case['dtype']).reshape(y.shape)
            bits=np.uint32 if x.dtype==np.float32 else np.uint16
            result['zero_identity_ok']=bool(np.array_equal(actual[zero].view(bits),x[zero].view(bits)))
            result['passed'] &= result['zero_identity_ok']
            results.append(result)
            if not (args.sweep or args.packed_sweep) or not result['passed']:print(json.dumps(result),flush=True)
        if args.sweep or args.packed_sweep:print(f"Sweep: {sum(c['passed'] for c in results)}/{len(results)} passed",flush=True)
    if not args.generate_only:
        path=ROOT/'benchmarks/results'/f'{args.label}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(label=args.label,seconds=time.time()-start,
            source_sha256=source_sha,binary_sha256=binary_sha,
            cases=results),indent=2)+'\n')
        if not all(c['passed'] for c in results):raise SystemExit(1)
if __name__=='__main__':main()
