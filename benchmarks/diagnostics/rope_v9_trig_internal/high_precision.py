"""80-digit attribution of the fixed trace; no Device or acceptance changes."""
import csv
import json
from collections import Counter
from pathlib import Path
import mpmath as mp
import numpy as np
from models import arguments,reg_name,scalar,replay,rotate,stats

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build/rope_v9_trig_internal'
mp.mp.dps=80;np.seterr(invalid='ignore',over='ignore')
schema=json.loads((HERE/'trace_schema.json').read_text())
data=np.load(BUILD/'canonical_trace.npz');dev=data['device'];T,W=137,512
p=np.fromfile(ROOT/'build/rope_v9_system/input/positions.bin','i4');active=p!=0;mask=active[:,None]
high=np.full(dev.shape,np.nan,'f8')
targets={k:np.full((T,W),np.nan,'f8') for k in ['reduced','quarter','sin_quarter','cos_quarter','cos_half','sin_half','sin_full','cos_full','poly_exact_same_quarter','sqrt_same_argument','reconstructed_cos_exact_device_quarter','reconstructed_sin_exact_device_quarter','unit_circle_defect']}
ops=[]
for item in schema['stages'][1:]:
    op,a=arguments(item['operation']);ops.append((op,a,mp.mpf(float(scalar(a[2]))) if op in ['Muls','Adds'] else None))
for token in np.flatnonzero(active):
    for col in range(W):
        raw=mp.mpf(float(dev[0,token,col]));regs={'angle':raw};high[0,token,col]=float(raw)
        for idx,(op,a,constant) in enumerate(ops,1):
            dst=reg_name(a[0]);left=regs[reg_name(a[1])]
            if op=='Muls':value=left*constant
            elif op=='Adds':value=left+constant
            elif op=='Mul':value=left*regs[a[2]]
            elif op=='Sub':value=left-regs[a[2]]
            elif op=='Sqrt':value=mp.sqrt(left)
            elif op=='Cast':
                # Keep the period selection identical; this model studies
                # arithmetic error within that period, not a different branch.
                value=mp.mpf(int(dev[2].view('i4')[token,col])) if idx==2 else left
            else:raise ValueError(op)
            regs[dst]=value;high[idx,token,col]=float(value)
        quotient=int(dev[2].view('i4')[token,col]);reduced=raw-quotient*2*mp.pi;quarter=reduced/4
        same_q=mp.mpf(float(dev[10,token,col]));u=same_q*same_q
        poly=u*mp.mpf(float(np.float32(1)/np.float32(362880)))+mp.mpf(float(-np.float32(1)/np.float32(5040)))
        poly=poly*u+mp.mpf(float(np.float32(1)/np.float32(120)))
        poly=poly*u+mp.mpf(float(-np.float32(1)/np.float32(6)))
        poly=(poly*u+1)*same_q
        dq_s=mp.mpf(float(dev[20,token,col]));dq_c=mp.mpf(float(dev[24,token,col]));h=2*dq_s*dq_c
        values=dict(reduced=reduced,quarter=quarter,sin_quarter=mp.sin(quarter),cos_quarter=mp.cos(quarter),
            sin_half=mp.sin(reduced/2),cos_half=mp.cos(reduced/2),sin_full=mp.sin(raw),cos_full=mp.cos(raw),
            poly_exact_same_quarter=poly,sqrt_same_argument=mp.sqrt(mp.mpf(float(dev[23,token,col]))),
            reconstructed_cos_exact_device_quarter=1-2*h*h,
            reconstructed_sin_exact_device_quarter=2*h*(1-2*dq_s*dq_s),unit_circle_defect=dq_s*dq_s+dq_c*dq_c-1)
        for key,value in values.items():targets[key][token,col]=float(value)
    print(f'high-precision token {int(token)} complete',flush=True) if token%16==0 else None
np.savez(BUILD/'high_precision.npz',algorithm=high,**targets)


def oracle_stats(a,b):
    result=stats(a,b.astype('f4'),mask)
    aa,bb=np.asarray(a,'f8')[active],b[active];e=np.abs(aa-bb)
    result['max_abs_error_vs_unrounded_oracle']=float(e.max())
    result['mean_abs_error_vs_unrounded_oracle']=float(e.mean())
    result['oracle_note']='80-digit computation saved as FP64; bit/ULP metrics compare its FP32 rounding, unrounded absolute error is separate.'
    return result


stage_hp=[]
for info in schema['stages']:
    i=info['index'];a=dev[i].view('i4') if info['dtype']=='int32' else dev[i]
    if info['dtype']=='int32':r=stats(a,high[i].astype('i4'),mask)
    else:r=oracle_stats(a,high[i])
    stage_hp.append(dict(index=i,name=info['name'],vs_unrounded_original_algorithm=r))
comparisons={}
for name,i,oracle in [('range_reduction',9,'reduced'),('quarter_angle',10,'quarter'),('quarter_sine_poly',20,'sin_quarter'),
    ('quarter_cosine_sqrt',24,'cos_quarter'),('half_sine_reconstruction',26,'sin_half'),('half_cosine_reconstruction',29,'cos_half'),
    ('full_cosine_reconstruction',32,'cos_full'),('full_sine_reconstruction',34,'sin_full'),
    ('sqrt_conditional_on_exact_device_argument',24,'sqrt_same_argument'),
    ('cosine_conditional_on_exact_device_quarter',32,'reconstructed_cos_exact_device_quarter'),
    ('sine_conditional_on_exact_device_quarter',34,'reconstructed_sin_exact_device_quarter')]:
    comparisons[name]=oracle_stats(dev[i],targets[oracle])
poly_round=np.abs(dev[20,active].astype('f8')-targets['poly_exact_same_quarter'][active])
same_q_sin=np.empty((int(active.sum()),W),'f8')
for index,token in enumerate(np.flatnonzero(active)):
    same_q_sin[index]=[float(mp.sin(mp.mpf(float(v)))) for v in dev[10,token]]
poly_approx=np.abs(targets['poly_exact_same_quarter'][active]-same_q_sin)
sqrt_rounded=targets['sqrt_same_argument'].astype('f4')
sqrt_ulp=dev[24,active].view('u4').astype('i8')-sqrt_rounded[active].view('u4').astype('i8')
assert set(np.unique(sqrt_ulp)) <= {-1,0,1}
sqrt_cpu=np.sqrt(dev[23]);assert np.array_equal(sqrt_cpu[active].view('u4'),sqrt_rounded[active].view('u4'))

x=np.fromfile(ROOT/'build/rope_v9_system/input/x.bin','f2').reshape(T,17,1024)
actual=np.fromfile(BUILD/'probe_half.bin','f2').reshape(x.shape)
angle=dev[0].copy();angle[~active]=0
cc,ss=np.cos(angle),np.sin(angle)
gold32=rotate(x,cc,ss);gold32[~active]=x[~active];gold=gold32.astype('f2');gold[~active]=x[~active]
fixed=replay(angle,schema,{24:sqrt_rounded});fixed32=rotate(x,fixed[32],fixed[34]);fixed32[~active]=x[~active]
fixed_half=fixed32.astype('f2');fixed_half[~active]=x[~active]

def bad(a):
    finite=np.isfinite(a)&np.isfinite(gold);result=np.zeros(a.shape,bool)
    result[finite]=np.abs(a[finite].astype('f4')-gold[finite].astype('f4'))>.1
    return result

old_bad,new_bad=bad(actual),bad(fixed_half)
old_rows=list(csv.DictReader((HERE.parent/'rope_v9_system/fp16_boundary_failures.csv').open()))
assert len(old_rows)==int(old_bad.sum())==817
rows=[]
for row in old_rows:
    t,h,c=map(int,[row['token'],row['head'],row['col']]);i=c%W;k=(t,h,c)
    row.update(first_device_rounding_divergence=int(data['first_local'][t,i]),
        sqrt_argument=float(dev[23,t,i]),device_sqrt=float(dev[24,t,i]),correctly_rounded_sqrt=float(sqrt_rounded[t,i]),
        sqrt_signed_ulp=int(dev[24,t,i].view('u4').astype('i8')-sqrt_rounded[t,i].view('u4').astype('i8')),
        quarter_poly=float(dev[20,t,i]),quarter_poly_abs_error=float(abs(float(dev[20,t,i])-targets['sin_quarter'][t,i])),
        sqrt_corrected_output=float(fixed_half[k]),sqrt_corrected_fp32=float(fixed32[k]),
        remains_above_point_one_after_sqrt_correction=bool(new_bad[k]))
    rows.append(row)
with (HERE/'boundary_attribution.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
result=dict(mp_decimal_digits=80,stage_comparisons=stage_hp,mathematical_function_comparisons=comparisons,
    polynomial_separation=dict(max_fp32_evaluation_abs_error_same_device_quarter=float(poly_round.max()),
        max_exact_polynomial_approximation_abs_error_same_device_quarter=float(poly_approx.max()),
        note='Exact polynomial retains original FP32 coefficient values; its error includes coefficient and truncation error.'),
    device_sqrt_signed_ulp_histogram={str(int(k)):int(v) for k,v in zip(*np.unique(sqrt_ulp,return_counts=True))},
    sqrt_cpu_vs_80_digit_rounding_bit_differences=0,
    unit_circle_defect_max_abs=float(np.max(np.abs(targets['unit_circle_defect'][active]))),
    fp16_boundary_attribution=dict(original_bad=int(old_bad.sum()),sqrt_corrected_bad=int(new_bad.sum()),
        original_bad_with_device_sqrt_divergence=sum(r['sqrt_signed_ulp']!=0 for r in rows),
        original_bad_without_device_sqrt_divergence=sum(r['sqrt_signed_ulp']==0 for r in rows),
        removed_by_sqrt_correction=int(np.count_nonzero(old_bad&~new_bad)),
        introduced_by_sqrt_correction=int(np.count_nonzero(new_bad&~old_bad)),
        common=int(np.count_nonzero(new_bad&old_bad)),
        instruction='CPU counterfactual only. Actual outputs, acceptance golden and thresholds remain unchanged.'),
    caveat='The unrounded-algorithm oracle fixes the Device integer quotient, retains original FP32 constants, and removes subsequent arithmetic rounding. Mathematical-function oracles separately use exact 2*pi and real sin/cos of the exported FP32 angle.')
(HERE/'high_precision_report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='stage_comparisons'},indent=2))
