"""CPU-only numerical models for attribution, not acceptance replacements."""
import ctypes
import re
import numpy as np

LIBM=ctypes.CDLL('libm.so.6')
for name,nargs in [('fmaf',3),('sinf',1),('cosf',1)]:
    fn=getattr(LIBM,name);fn.argtypes=[ctypes.c_float]*nargs;fn.restype=ctypes.c_float


def fma(a,b,c):
    arrays=np.broadcast_arrays(np.asarray(a,'f4'),np.asarray(b,'f4'),np.asarray(c,'f4'))
    return np.fromiter((LIBM.fmaf(float(x),float(y),float(z)) for x,y,z in zip(*(a.ravel() for a in arrays))),dtype='f4',count=arrays[0].size).reshape(arrays[0].shape)


def scalar(text):
    # Constants only from the source-hash-bound trig body.
    values=text.replace('f','').split('/')
    return np.float32(values[0]) if len(values)==1 else np.float32(values[0])/np.float32(values[1])


def arguments(statement):
    name,rest=statement.split('(',1)
    return name,[s.strip() for s in rest[:-2].split(',')]


def reg_name(argument): return argument.split('.',1)[0]


def operation(statement,regs):
    op,a=arguments(statement);dst=reg_name(a[0])
    left=regs[reg_name(a[1])]
    if op=='Cast':
        value=np.rint(left).astype('i4') if 'ReinterpretCast<int32_t>' in a[0] else left.astype('f4')
    elif op=='Sqrt':value=np.sqrt(left)
    elif op=='Muls':value=left*scalar(a[2])
    elif op=='Adds':value=left+scalar(a[2])
    elif op=='Mul':value=left*regs[a[2]]
    elif op=='Sub':value=left-regs[a[2]]
    else:raise ValueError(op)
    return dst,value


def replay(angle,schema,overrides=None):
    regs={'angle':angle.copy()};stages=[angle.copy()]
    for info in schema['stages'][1:]:
        dst,value=operation(info['operation'],regs)
        if overrides and info['index'] in overrides:value=overrides[info['index']]
        regs[dst]=value;stages.append(value.copy())
    return stages


def ordered(a):
    u=np.asarray(a,'f4').view('u4').astype('i8')
    return np.where(u&0x80000000,0x80000000-(u&0x7fffffff),u+0x80000000)


def stats(actual,reference,mask=None):
    aa,bb=np.broadcast_arrays(actual,reference)
    mask=np.ones(aa.shape,bool) if mask is None else np.broadcast_to(mask,aa.shape)
    finite=mask&np.isfinite(aa)&np.isfinite(bb)
    errors=np.abs(aa[finite].astype('f8')-bb[finite].astype('f8'))
    integer=aa.dtype.kind in 'iu' and bb.dtype.kind in 'iu'
    bits=aa!=bb if integer else aa.astype('f4').view('u4')!=bb.astype('f4').view('u4')
    result=dict(elements=int(mask.sum()),bit_differences=int(np.count_nonzero(bits&mask)),
        max_abs_error=float(errors.max(initial=0)),mean_abs_error=float(errors.mean()) if len(errors) else 0)
    if not integer:
        ulp=np.abs(ordered(aa[finite])-ordered(bb[finite]))
        result.update(max_ulp=int(ulp.max(initial=0)),p99_ulp=float(np.quantile(ulp,.99)) if len(ulp) else 0)
        result['ulp_caveat']='Ordered FP32 bit distance; interpret near-zero ULP together with absolute error.'
    return result


def numpy_226_model(angle,quadrant_fused=False):
    """Pinned upstream algorithm: CPU true fmaf, no use of Device vmadd/vmla."""
    x=np.asarray(angle,'f4');scale=np.float32(float.fromhex('0x1.45f306p-1'));magic=np.float32(float.fromhex('0x1.800000p+23'))
    if quadrant_fused:q=fma(x,scale,magic)-magic
    else:q=(x*scale+magic)-magic
    r=fma(q,np.float32(float.fromhex('-0x1.921fb0p+00')),x)
    r=fma(q,np.float32(float.fromhex('-0x1.5110b4p-22')),r)
    r=fma(q,np.float32(float.fromhex('-0x1.846988p-48')),r)
    u=r*r
    c=fma(np.float32(float.fromhex('0x1.98e616p-16')),u,np.float32(float.fromhex('-0x1.6c06dcp-10')))
    for k in ['0x1.55553cp-05','-0x1.000000p-01','0x1.000000p+00']:c=fma(c,u,np.float32(float.fromhex(k)))
    s=fma(np.float32(float.fromhex('0x1.7d3bbcp-19')),u,np.float32(float.fromhex('-0x1.a06bbap-13')))
    for k in ['0x1.11119ap-07','-0x1.555556p-03','0x0p+00']:s=fma(s,u,np.float32(float.fromhex(k)))
    s=fma(s,r,r)
    qi=q.astype('i4');outputs=[]
    for cosine,limit,fn in [(True,np.float32(71476.0625),LIBM.cosf),(False,np.float32(117435.992),LIBM.sinf)]:
        quadrant=qi+int(cosine)
        y=np.where((quadrant&1)==0,s,c);y=np.where((quadrant&2)==2,-y,y)
        fallback=np.abs(x)>limit
        y[fallback]=np.fromiter((fn(float(v)) for v in x[fallback]),dtype='f4',count=int(fallback.sum()))
        outputs.append(y)
    return tuple(outputs)


def rotate(x,c,s):
    width=x.shape[-1]//2;a=x[...,:width].astype('f4');b=x[...,width:].astype('f4')
    with np.errstate(invalid='ignore',over='ignore'):
        return np.concatenate((a*c[:,None,:]-b*s[:,None,:],b*c[:,None,:]+a*s[:,None,:]),axis=-1)
