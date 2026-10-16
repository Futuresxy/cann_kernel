import math,struct,decimal,ctypes
import numpy as np
Q=1<<53;B=1<<61
D=decimal.Decimal;decimal.getcontext().prec=70
ln2=(D(2).ln());LN2_53=int((ln2*Q).to_integral_value());LN2_61=int((ln2*B).to_integral_value());INV_LN2_53=int((Q/ln2).to_integral_value())
C=[int((D(float.fromhex(x))*Q).to_integral_value()) for x in ['0x1.c6af84b912394p-5','0x1.ebfce50fac4f3p-3','0x1.62e42ff0c52d6p-1']]
def rnd(n,d):
 q,r=divmod(n,d);return q+(r*2>d or r*2==d and q&1)
def lnQ(theta):
 m,e=math.frexp(theta)
 if m<2**-.5:m*=2;e-=1
 n,d=(m-1).as_integer_ratio();n0,d0=(m+1).as_integer_ratio();z=abs(n)*d0*Q//(d*abs(n0));sg=-1 if m<1 else 1
 zz=z*z//Q;term=z;total=z
 for odd in range(3,22,2):term=term*zz//Q;total+=term//odd
 return sg*((2*total*INV_LN2_53)//Q)+e*Q

def table():
 w=LN2_61//32;term=B;s=B
 for j in range(1,10):term=term*w//B//j;s+=term
 result=[B]
 for j in range(31):result.append(result[-1]*s//B)
 return result
T=table()
def scalarFreq(theta,width):
 log=lnQ(theta);result=[]
 for i in range(width):
  if not i:result.append(0x3f800000);continue
  shift=0
  while (i<<shift)<width:shift+=1
  mant=rnd(i<<(23+shift),width);exponent=mant<<(30-shift)
  t=(abs(log)*exponent//Q)*(1 if log>=0 else -1)
  k=rnd(t,1<<48);r=t-k*(1<<48)
  def mul(a,b):return (abs(a)*abs(b)//Q)*(1 if a*b>=0 else -1)
  poly=Q+mul(r,C[2]+mul(r,C[1]+mul(r,C[0])))
  v=mul(rnd(T[k&31],1<<8),poly);e=k>>5
  if v<Q:v<<=1;e-=1
  elif v>=2*Q:v>>=1;e+=1
  pm=rnd(v,1<<30)
  if pm>=1<<24:pm>>=1;e+=1
  if pm==1<<23:fm=1<<23;fe=-e
  else:fm=rnd(1<<47,pm);fe=-e-1
  if fm>=1<<24:fm>>=1;fe+=1
  result.append(((fe+127)<<23)+(fm-(1<<23)))
 return np.array(result,np.uint32).view(np.float32)
if __name__=='__main__':
 print('constants',LN2_61,INV_LN2_53,C,flush=True)
 for theta in [.5,1,1.0001,100,1000,10000,500000]:
  theta=float(np.float32(theta));bad=0
  for w in range(8,513):
   f=scalarFreq(theta,w);e=np.arange(w,dtype=np.float32)/np.float32(w);gold=np.float32(1)/np.power(np.float32(theta),e);bad+=np.sum(f.view('i4')!=gold.view('i4'))
  print(theta,bad,flush=True)
