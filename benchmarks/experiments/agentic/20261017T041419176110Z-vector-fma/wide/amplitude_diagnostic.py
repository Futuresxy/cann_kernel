"""Read-only CPU diagnostic of the inherited high-amplitude precision failure.

The official/local acceptance golden is not changed. A libm frequency variant
is reported solely to distinguish possible power-library and trig effects.
"""
import ctypes
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[5]
folder=ROOT/'build/data/r2wide_amplitude_float16'
x=np.fromfile(folder/'x.bin',np.float16).reshape(1,137,17,1024)
p=np.fromfile(folder/'positions.bin',np.int32).reshape(1,137)
actual=np.fromfile(ROOT/'build/agentic_r2wide/amplitude_candidate_half.bin',np.float16).reshape(x.shape)
e=np.arange(512,dtype=np.float32)/np.float32(512)
freq=np.float32(1)/np.power(np.float32(10000),e)
libm=ctypes.CDLL('libm.so.6');libm.powf.argtypes=[ctypes.c_float,ctypes.c_float];libm.powf.restype=ctypes.c_float
other=np.array([np.float32(1)/np.float32(libm.powf(10000,float(v))) for v in e],np.float32)
def golden(f):
    angle=p.astype(np.float32)[...,None]*f
    c=np.cos(angle)[...,None,:];s=np.sin(angle)[...,None,:]
    a=x[...,:512].astype(np.float32);b=x[...,512:].astype(np.float32)
    with np.errstate(invalid='ignore',over='ignore'):
        y=np.concatenate((a*c-b*s,b*c+a*s),axis=-1).astype(np.float16)
    y[p==0]=x[p==0]
    return y
g=golden(freq);alternate=golden(other)
finite=np.isfinite(g)&np.isfinite(actual)
error=np.zeros(x.shape,np.float32);error[finite]=np.abs(actual[finite].astype(np.float32)-g[finite].astype(np.float32))
bad=np.argwhere(error>.1)
rows=[]
for index in bad[:16]:
    k=tuple(map(int,index));i=k[-1]%512
    rows.append(dict(index=list(k),position=int(p[k[:2]]),actual=float(actual[k]),original_golden=float(g[k]),alternate_libm_frequency_golden=float(alternate[k]),abs_error=float(error[k]),frequency_column=i,numpy_frequency_bits=hex(int(freq.view(np.uint32)[i])),libm_frequency_bits=hex(int(other.view(np.uint32)[i]))))
af=np.isfinite(alternate)&np.isfinite(actual)
with np.errstate(invalid='ignore'):
    ae=np.abs(actual[af].astype(np.float32)-alternate[af].astype(np.float32))
result=dict(original_golden_max_abs_error=float(error.max()),elements_above_max_abs_limit=len(bad),numpy_vs_libm_frequency_bit_differences=int(np.count_nonzero(freq.view(np.uint32)!=other.view(np.uint32))),alternate_libm_frequency_max_abs_error=float(ae.max()),failures=rows,interpretation='Diagnostic only. Neither the golden, precision limits nor acceptance decision is changed. The device frequency vector itself was not instrumented, so library differences alone do not establish the full error cause.')
Path(__file__).with_name('amplitude_diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')
print({k:v for k,v in result.items() if k!='failures'})
