from pathlib import Path
import importlib.util,random,json,functools
import numpy as np
from pathlib import Path
spec=importlib.util.spec_from_file_location('m',str(Path(__file__).with_name('adaptive_binary.py')));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.old.lnQ=functools.lru_cache(None)(m.old.lnQ)
def fast(theta,w,i):
 log=m.old.lnQ(theta);log31=(abs(log)>>22)*(1 if log>=0 else -1)
 shift=0
 while i<<shift<w:shift+=1
 mant=m.old.rnd(i<<(23+shift),w)
 x=(log31*mant)>>(23+shift)
 k=m.old.rnd(abs(x),1<<26)*(1 if x>=0 else -1);r=x-k*(1<<26)
 p=(1<<31)+((r*(m.C[2]+((r*(m.C[1]+((r*m.C[0])>>31)))>>31)))>>31)
 v=(m.old.rnd(m.old.T[k&31],1<<30)*p)>>31;e=k>>5
 if v<1<<31:v<<=1;e-=1
 elif v>=1<<32:v>>=1;e+=1
 stable=abs((v&255)-128)>32;pm=(v+128)>>8
 if pm>=1<<24:pm>>=1;e+=1
 if pm==1<<23:fm=1<<23;fe=-e
 else:fm=m.old.rnd(1<<47,pm);fe=-e-1
 if fm>=1<<24:fm>>=1;fe+=1
 return stable,((fe+127)<<23)+(fm-(1<<23))
rng=random.Random(714);thetas=[.5,.7,1,1.0001,2,100,1000,10000,500000,2**-64,2**64]+[2**rng.uniform(-64,64) for _ in range(64)]
accepted=fallback=bad=0
for theta in thetas:
 theta=float(np.float32(theta))
 for w in range(8,129):
  g=m.old.scalarFreq(theta,w).view(np.uint32)
  for i in range(1,w):
   ok,v=fast(theta,w,i)
   if ok:
    accepted+=1
    if v!=g[i]:bad+=1;print('mismatch',theta,w,i,v,int(g[i]),flush=True)
   else:fallback+=1
r=dict(scope='CPU scalar numerical model, not device validation',theta_count=len(thetas),widths=[8,128],accepted=accepted,fallback=fallback,mismatches=bad)
Path('build/round7_numerical_check.json').write_text(json.dumps(r,indent=2)+'\n');print(r,flush=True);assert bad==0
