from pathlib import Path
import importlib.util, random, math
import numpy as np
from decimal import Decimal
spec=importlib.util.spec_from_file_location('old',str(Path(__file__).with_name('v7_scalar.py')));old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
C=[int((Decimal(float.fromhex(x))*(1<<31)).to_integral_value()) for x in ['0x1.c6af84b912394p-5','0x1.ebfce50fac4f3p-3','0x1.62e42ff0c52d6p-1']]
def fast(theta,width,i):
 log=old.lnQ(theta)
 # C++ signed division truncates toward zero.
 log31=(abs(log)>>22)*(1 if log>=0 else -1)
 x31=(log31*i)>>(width.bit_length()-1)
 k=old.rnd(abs(x31),1<<26)*(1 if x31>=0 else -1)
 r=x31-k*(1<<26)
 p=(1<<31)+((r*(C[2]+((r*(C[1]+((r*C[0])>>31)))>>31)))>>31)
 center=old.rnd(old.T[k&31],1<<30)
 v=(center*p)>>31;e=k>>5
 if v<1<<31:v<<=1;e-=1
 elif v>=1<<32:v>>=1;e+=1
 rem=v&255
 stable=abs(rem-128)>32
 pm=(v+128)>>8
 if pm>=1<<24:pm>>=1;e+=1
 if pm==1<<23:fm=1<<23;fe=-e
 else:fm=old.rnd(1<<47,pm);fe=-e-1
 if fm>=1<<24:fm>>=1;fe+=1
 bits=((fe+127)<<23)+(fm-(1<<23))
 return stable,bits
if __name__=='__main__':
 print('Q31 coefficients',C,flush=True)
 rng=random.Random(713);ts=[.5,.7,1,1.0001,2,100,1000,10000,500000,2**-64,2**64]+[2**rng.uniform(-64,64) for _ in range(256)]
 accepted=0;fallback=0;differences=0
 for theta in ts:
  theta=float(np.float32(theta))
  for w in [8,16,32,64,128,256,512]:
   exact=old.scalarFreq(theta,w).view(np.uint32)
   for i in range(w):
    ok,bits=fast(theta,w,i)
    if ok:
     accepted+=1
     if bits!=exact[i]:
      differences+=1;print('mismatch',theta,w,i,bits,int(exact[i]),flush=True)
    else:fallback+=1
 print('accepted',accepted,'fallback',fallback,'mismatches',differences,flush=True)
 assert differences==0
