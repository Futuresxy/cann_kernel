import importlib.util,functools,random,json
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('old',str(Path(__file__).resolve().parents[2]/'round7/numerical_model/v7_scalar.py'));old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
old.lnQ=functools.lru_cache(None)(old.lnQ)
C31=[32864,332210,2863343,20654553,119194167,515882507,1488522236,2147483648]
C53=[4013444,63718678,916757882,11903403409,137384412890,1387426681132,12009801499936,86632405329863,499936566200844,2163768014451052,6243314768165359,9007199254740992]
def mul53(a,b):return (abs(a)*abs(b)//(1<<53))*(1 if a*b>=0 else -1)
def calc(theta,w,i):
 if i==0:return True,0x3f800000,0x3f800000
 log=old.lnQ(theta);log31=(abs(log)>>22)*(1 if log>=0 else -1)
 if w&(w-1)==0:num=i;sh=w.bit_length()-1;ex=i<<(53-sh)
 else:
  s=0
  while i<<s<w:s+=1
  num=old.rnd(i<<(23+s),w);sh=23+s;ex=num<<(30-s)
 x=(log31*num)>>sh;k=old.rnd(abs(x),1<<31)*(1 if x>=0 else -1);r=x-k*(1<<31)
 if abs(r)<=4096:p=(1<<31)+((r*1488522236)>>31)
 else:
  p=C31[0]
  for c in C31[1:]:p=c+((r*p)>>31)
 e=k
 if p<1<<31:p<<=1;e-=1
 elif p>=1<<32:p>>=1;e+=1
 ok=abs((p&255)-128)>16
 def finish(pm,e):
  if pm>=1<<24:pm>>=1;e+=1
  if pm==1<<23:fm=1<<23;fe=-e
  else:fm=old.rnd(1<<47,pm);fe=-e-1
  if fm>=1<<24:fm>>=1;fe+=1
  return ((fe+127)<<23)+(fm-(1<<23))
 fast=finish((p+128)>>8,e)
 x=mul53(log,ex);k=old.rnd(abs(x),1<<53)*(1 if x>=0 else -1);r=x-k*(1<<53)
 p=C53[0]
 for c in C53[1:]:p=c+mul53(r,p)
 e=k
 if p<1<<53:p<<=1;e-=1
 elif p>=1<<54:p>>=1;e+=1
 accurate=finish(old.rnd(p,1<<30),e)
 return ok,fast,accurate
if __name__=='__main__':
 rng=random.Random(901)
 ts=[.01,.5,.7,1,1.0001,2,100,1000,10000,500000,2**-64,2**64]+[2**rng.uniform(-64,64) for _ in range(120)]
 checked=accepted=bad=diff=0
 for t in ts:
  t=float(np.float32(t))
  for w in [8,9,12,15,16,24,25,32,33,40,48,64,65,72,96,128]:
   gold=np.float32(1)/np.power(np.float32(t),np.arange(w,dtype=np.float32)/np.float32(w))
   for i in range(w):
    ok,a,b=calc(t,w,i);checked+=1;accepted+=ok
    if ok and a!=b:bad+=1;print('unsafe',t,w,i,a,b,flush=True)
    if (a if ok else b)!=int(gold.view(np.uint32)[i]):diff+=1
 r=dict(checked=checked,accepted=accepted,unsafe_fast_acceptances=bad,differences_from_numpy=diff,reference='NumPy FP32 power+reciprocal; CPU model only')
 Path('build/round8_tablefree_model.json').write_text(json.dumps(r,indent=2)+'\n');print(r,flush=True);assert bad==0
