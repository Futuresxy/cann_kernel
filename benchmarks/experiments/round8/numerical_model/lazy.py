import importlib.util,json,random,functools
from pathlib import Path
import numpy as np
sp=importlib.util.spec_from_file_location('m',str(Path(__file__).with_name('tablefree.py')));m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
Q=1<<53;B=1<<61
root=m.old.T[1];roots=[root]
for _ in range(4):roots.append(roots[-1]*roots[-1]//B)
centers=[]
for i in range(32):
 value=B
 for j in range(5):
  if i>>j&1:value=value*roots[j]//B
 centers.append(value)

def guarded(t,w,i):
 ok,a,_=m.calc(t,w,i)
 if ok:return a,True
 log=m.old.lnQ(t);shift=0
 while i<<shift<w:shift+=1
 ratio=m.old.rnd(i<<(23+shift),w)<<(30-shift)
 x=m.mul53(log,ratio);k=m.old.rnd(abs(x),1<<48)*(1 if x>=0 else -1);r=x-k*(1<<48)
 c=m.old.C;p=Q+m.mul53(r,c[2]+m.mul53(r,c[1]+m.mul53(r,c[0])))
 power=m.mul53(m.old.rnd(centers[k&31],256),p);e=k>>5
 if power<Q:power<<=1;e-=1
 elif power>=2*Q:power>>=1;e+=1
 pm=m.old.rnd(power,1<<30)
 if pm>=1<<24:pm>>=1;e+=1
 if pm==1<<23:fm=1<<23;fe=-e
 else:fm=m.old.rnd(1<<47,pm);fe=-e-1
 if fm>=1<<24:fm>>=1;fe+=1
 return ((fe+127)<<23)+(fm-(1<<23)),False
if __name__=='__main__':
 rng=random.Random(902);ts=[.01,.5,.7,1,1.0001,2,100,1000,10000,500000,2**-64,2**64]+[2**rng.uniform(-64,64) for _ in range(64)]
 checked=accepted=bad=0
 for t in ts:
  t=float(np.float32(t))
  for w in range(8,129):
   g=m.old.scalarFreq(t,w).view(np.uint32)
   for i in range(w):
    a,ok=guarded(t,w,i);checked+=1;accepted+=ok
    if a!=int(g[i]):bad+=1;print('mismatch',t,w,i,a,int(g[i]),flush=True)
 r=dict(checked=checked,accepted=accepted,mismatches_from_v8_scalar=bad,maximum_center_q61_difference=max(abs(a-b) for a,b in zip(centers,m.old.T)),scope='CPU model; all integer widths 8..128')
 Path('build/round8_lazy_model.json').write_text(json.dumps(r,indent=2)+'\n');print(r,flush=True);assert bad==0
