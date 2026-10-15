#!/usr/bin/env python3
"""Deterministic correctness gate and bounded single-device measurement."""
import argparse, hashlib, json, os, pathlib, subprocess, time
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
def generate(case, dest, seed):
    rng=np.random.default_rng(seed)
    x=rng.uniform(-10,10,case['shape']).astype(case['dtype'])
    p=rng.integers(0,case['pmax'],case['shape'][:2],dtype=np.int32)
    if case.get('extreme'): p.flat[:min(4,p.size)]=[131072,131071,65536,0][:min(4,p.size)]
    if case.get('special'): x.flat[:4]=[np.nan,np.inf,-np.inf,-0.0]
    d=x.shape[-1]
    exponent=np.arange(0,d,2,dtype=np.float32)/np.float32(d)
    freq=np.float32(1)/np.power(np.float32(case.get('theta',10000)),exponent)
    angle=p.astype(np.float32)[...,None]*freq
    c=np.cos(angle)[...,None,:]; s=np.sin(angle)[...,None,:]
    a=x[...,:d//2].astype(np.float32);b=x[...,d//2:].astype(np.float32)
    with np.errstate(invalid='ignore'):
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
    args=ap.parse_args();cases=json.loads((ROOT/'tests/cases.json').read_text())
    if args.cases!='all':cases=[c for c in cases if c['name'] in args.cases.split(',')]
    results=[];start=time.time()
    source_sha=hashlib.sha256((ROOT/'operators/rotary_pos_emb/kernel.asc').read_bytes()).hexdigest()
    binary_sha=None if args.generate_only else hashlib.sha256((ROOT/args.binary).read_bytes()).hexdigest()
    for i,case in enumerate(cases):
        dest=ROOT/'build/data'/case['name']
        seed=42+json.loads((ROOT/'tests/cases.json').read_text()).index(case)
        x,p,y=generate(case,dest,seed)
        if args.generate_only:continue
        cmd=[str(ROOT/args.binary),'--device',str(args.device),'--shape',*map(str,case['shape']),
             '--dtype',case['dtype'],'--theta',str(case.get('theta',10000)),'--input',str(dest),
             '--output',str(dest/'actual.bin'),'--repeat',str(args.repeat),'--batches',str(args.batches)]
        proc=subprocess.run(cmd,text=True,capture_output=True,timeout=45)
        if proc.returncode:
            print(proc.stdout,proc.stderr,flush=True);raise RuntimeError(case['name'])
        actual=np.fromfile(dest/'actual.bin',dtype=case['dtype']).reshape(y.shape)
        timing=json.loads(proc.stdout.strip().splitlines()[-1]);metrics=compare(actual,y)
        result={**case,**timing,**metrics};results.append(result)
        print(json.dumps(result),flush=True)
    if not args.generate_only:
        path=ROOT/'benchmarks/results'/f'{args.label}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(label=args.label,seconds=time.time()-start,
            source_sha256=source_sha,binary_sha256=binary_sha,
            cases=results),indent=2)+'\n')
        if not all(c['passed'] for c in results):raise SystemExit(1)
if __name__=='__main__':main()
