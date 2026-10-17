"""CPU binary32 schedule/alias model for the narrowly scoped wide rotation."""
import hashlib
import json
from pathlib import Path
import numpy as np

rng=np.random.default_rng(174322)
checks=[];elements=0;finite_bit_differences=0;special_class_differences=0
with np.errstate(invalid='ignore',over='ignore',under='ignore'):
    for dim in [528,544,576,640,768,896,1008,1024]:
        width=dim//2
        for rows in [1,2,3,7,9,11]:
            for dtype in ['float16','float32']:
                for scale in [1,32,4096,60000]:
                    x=rng.uniform(-scale,scale,(rows,dim)).astype(dtype)
                    x.flat[:4]=[np.nan,np.inf,-np.inf,-0.0]
                    if rows>1:x[1,:4]=[np.nan,np.inf,-np.inf,-0.0]
                    angle=rng.uniform(0,131072,width).astype(np.float32)
                    c=np.cos(angle).astype(np.float32);s=np.sin(angle).astype(np.float32);negs=-s
                    z=x.astype(np.float32)
                    old=np.empty_like(z)
                    old[:,:width]=np.float32(np.float32(z[:,:width]*c)+np.float32(z[:,width:]*negs))
                    old[:,width:]=np.float32(np.float32(z[:,width:]*c)+np.float32(z[:,:width]*s))
                    # Compute both cross halves before any in-place z update.
                    cross=np.empty_like(z)
                    cross[:,:width]=np.float32(z[:,width:]*negs)
                    cross[:,width:]=np.float32(z[:,:width]*s)
                    z[:,:width]=np.float32(np.float32(z[:,:width]*c)+cross[:,:width])
                    z[:,width:]=np.float32(np.float32(z[:,width:]*c)+cross[:,width:])
                    old=old.astype(dtype);new=z.astype(dtype)
                    # Position-zero path copies input bytes before rotation, unchanged.
                    old[::5]=x[::5];new[::5]=x[::5]
                    bits=np.uint16 if dtype=='float16' else np.uint32
                    finite=np.isfinite(old)&np.isfinite(new)
                    changed=int(np.count_nonzero((old.view(bits)!=new.view(bits))&finite))
                    same_class=(np.isfinite(old)&np.isfinite(new))|(np.isnan(old)&np.isnan(new))|(np.isposinf(old)&np.isposinf(new))|(np.isneginf(old)&np.isneginf(new))
                    special=int(np.count_nonzero(~same_class))
                    identity=np.array_equal(new[::5].view(bits),x[::5].view(bits))
                    assert changed==special==0 and identity
                    elements+=new.size;finite_bit_differences+=changed;special_class_differences+=special
                    checks.append(dict(dim=dim,rows=rows,dtype=dtype,scale=scale,elements=new.size,finite_bit_differences=changed,special_class_differences=special,zero_identity_bits_equal=identity))
report=dict(seed=174322,case_count=len(checks),elements=elements,finite_bit_differences=finite_bit_differences,special_class_differences=special_class_differences,model='Each multiplication and each addition explicitly rounded to binary32, then cast to output dtype. vmadd semantics are independently tested on device, not inferred from its name.',generic_device_semantics='../fma_semantics_v2.json',caveat='CPU schedule proof and samples supplement, not replace, device reference/stride/tail/launch checks.',cases=checks)
Path(__file__).with_name('rotation_model.json').write_text(json.dumps(report,indent=2)+'\n')
print({k:v for k,v in report.items() if k!='cases'})
