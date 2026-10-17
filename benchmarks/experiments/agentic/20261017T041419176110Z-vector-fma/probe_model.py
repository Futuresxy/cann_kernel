"""CPU binary32 product/residual model; generated data is development-only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

def prepare(path):
    rng=np.random.default_rng(174310)
    groups=[]
    def add(name,a,b):
        groups.append((name,np.asarray(a,dtype=np.float32),np.asarray(b,dtype=np.float32)))
    add('normal_frequency_operands',rng.uniform(-.5,.5,4096),rng.uniform(.125,1.875,4096))
    add('normal_broad_exponents',np.ldexp(rng.uniform(.5,1,4096),rng.integers(-60,61,4096)),np.ldexp(rng.uniform(.5,1,4096),rng.integers(-60,61,4096)))
    a=(np.uint32(0x3f800000)+np.arange(1024,dtype=np.uint32)).view(np.float32)
    b=(np.uint32(0x3f800000)-np.arange(1024,dtype=np.uint32)).view(np.float32)
    add('near_rounding_and_cancellation',a,b)
    add('normal_inputs_subnormal_product',np.ldexp(rng.uniform(.5,1,1024),-70),np.ldexp(rng.uniform(.5,1,1024),-60))
    add('subnormal_inputs',(np.arange(1,1025,dtype=np.uint32)*8191).view(np.float32),rng.uniform(.5,2,1024))
    add('underflow_residual',np.ldexp(rng.uniform(.5,1,1024),-55),np.ldexp(rng.uniform(.5,1,1024),-55))
    add('distinguishing_example',np.full(64,np.float32(1+2**-23)),np.full(64,np.float32(1-2**-23)))
    a,b=[np.concatenate([g[i] for g in groups]) for i in [1,2]]
    with np.errstate(under='ignore',over='ignore'):
        p=(a*b).astype(np.float32)
    c=np.ldexp(rng.uniform(-1,1,len(a)),rng.integers(-100,101,len(a))).astype(np.float32)
    c[::2]=-p[::2]
    c[1::4]=np.nextafter(-p[1::4],np.float32(np.inf))
    x=np.stack([a,b,c])
    path.parent.mkdir(parents=True,exist_ok=True);x.tofile(path)
    offset=0;index=[]
    for name,a,b in groups:
        index.append(dict(name=name,start=offset,count=len(a)));offset+=len(a)
    info=dict(count=offset,input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),groups=index)
    path.with_suffix('.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info,indent=2))

def analyze(path,output,report):
    info=json.loads(path.with_suffix('.json').read_text());n=info['count'];a,b,c=np.fromfile(path,np.float32).reshape(3,n)
    y=np.fromfile(output,np.float32).reshape(8,n)
    with np.errstate(under='ignore',over='ignore',invalid='ignore'):
        p=(a*b).astype(np.float32);sp=(a*a).astype(np.float32)
        # The cancellation of an exact <=48-bit product and rounded binary32
        # product is exactly representable in binary64 before final binary32 rounding.
        residual=(a.astype(np.float64)*b.astype(np.float64)-p.astype(np.float64)).astype(np.float32)
        square=(a.astype(np.float64)*a.astype(np.float64)-sp.astype(np.float64)).astype(np.float32)
        separate=(p+c).astype(np.float32)
    def mismatch(x,z):
        return int(np.count_nonzero((x!=z)&~(np.isnan(x)&np.isnan(z))))
    groups=[]
    for g in info['groups']:
        s=slice(g['start'],g['start']+g['count']);q=dict(g)
        q.update(product_mismatches=mismatch(y[0,s],p[s]),vmadd_residual_mismatches=mismatch(y[1,s],residual[s]),vmla_residual_mismatches=mismatch(y[2,s],residual[s]),square_product_mismatches=mismatch(y[3,s],sp[s]),vmadd_square_alias_mismatches=mismatch(y[4,s],square[s]),expected_nonzero_residuals=int(np.count_nonzero(residual[s])),observed_vmadd_nonzero_residuals=int(np.count_nonzero(y[1,s])))
        q.update(vmadd_vs_separate_mismatches=mismatch(y[5,s],y[7,s]),vmla_vs_separate_mismatches=mismatch(y[6,s],y[7,s]),device_separate_vs_cpu_mismatches=mismatch(y[7,s],separate[s]))
        groups.append(q)
    i=n-1
    result=dict(cpu_model='binary64 exact binary32 product and cancellation, then binary32 rounding; signed zero equivalence allowed',input_sha256=info['input_sha256'],output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),groups=groups,distinguishing_example=dict(a=float(a[i]),b=float(b[i]),expected=float(residual[i]),vmadd=float(y[1,i]),vmla=float(y[2,i]),expected_bits=hex(int(residual.view(np.uint32)[i])),vmadd_bits=hex(int(y[1].view(np.uint32)[i])),vmla_bits=hex(int(y[2].view(np.uint32)[i]))))
    report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','analyze']);ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path);ap.add_argument('--report',type=Path);args=ap.parse_args()
    if args.mode=='prepare':prepare(args.input)
    else:analyze(args.input,args.output,args.report)
