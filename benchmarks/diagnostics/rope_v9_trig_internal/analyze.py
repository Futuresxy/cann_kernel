"""Attribute the new trace without rerunning any performance measurement."""
import csv
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import numpy as np
from models import LIBM, operation, replay, stats, numpy_226_model, rotate

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build/rope_v9_trig_internal'
T,H,D,W,CORES,SLOTS=137,17,1024,512,48,8
np.seterr(invalid='ignore',over='ignore')
schema=json.loads((HERE/'trace_schema.json').read_text())
trace=np.fromfile(BUILD/'stages.bin','f4').reshape(CORES,35,SLOTS,W)
x=np.fromfile(ROOT/'build/rope_v9_system/input/x.bin','f2').reshape(T,H,D)
p=np.fromfile(ROOT/'build/rope_v9_system/input/positions.bin','i4')
actual=np.fromfile(BUILD/'probe_half.bin','f2').reshape(x.shape)
original=np.fromfile(ROOT/'build/rope_v9_system/v9_baseline_half.bin','f2').reshape(x.shape)
assert np.array_equal(actual.view('u2'),original.view('u2'))
freq=np.float32(1)/np.power(np.float32(10000),np.arange(W,dtype='f4')/np.float32(W))
angle=p[:,None].astype('f4')*freq
active=p!=0;mask=active[:,None]
canonical=np.full((35,T,W),np.nan,'f4');valid=np.zeros((CORES,SLOTS),bool)
duplicates=0;duplicate_diffs=0;coverage=np.zeros(T,'i4');core_spans=[]
for core in range(CORES):
    begin=274*core//CORES;end=274*(core+1)//CORES;first=begin//2;limit=(end-1)//2+1
    cached=-1;count=0
    for job in range(begin,end):
        token=job//2
        if p[token] and (cached<0 or token>=cached+count):
            count=min(9,limit-token);cached=token;valid[core,token-first:token-first+count]=True
    for slot in np.flatnonzero(valid[core]):
        token=first+slot
        if coverage[token]:
            duplicates+=1;duplicate_diffs+=int(np.count_nonzero(trace[core,:,slot].view('u4')!=canonical[:,token].view('u4')))
        else:canonical[:,token]=trace[core,:,slot]
        coverage[token]+=1
    core_spans.append(dict(core=core,begin_job=begin,end_job=end,first_token=first,token_limit=limit,exported_slots=np.flatnonzero(valid[core]).tolist()))
assert np.all(coverage[active]>0)
assert duplicate_diffs==0
assert np.array_equal(canonical[0,active].view('u4'),angle[active].view('u4'))
prior_raw=np.fromfile(ROOT/'build/rope_v9_system/stages.bin','f4')
prior={};offset=48*512
for name in ['angle','reduced','quotient','cosine','sine']:
    prior[name]=prior_raw[offset:offset+T*W].reshape(T,W);offset+=T*W
prior_check={name:stats(canonical[index],prior[name],mask) for name,index in [('angle',0),('quotient',3),('reduced',9),('cosine',32),('sine',34)]}
assert all(v['bit_differences']==0 for v in prior_check.values())
expected=replay(angle,schema)
stage_results=[];first_global=np.zeros((T,W),'i4');first_local=np.zeros((T,W),'i4')
regs={'angle':angle.copy()}
for info in schema['stages']:
    i=info['index'];dev=canonical[i].view('i4') if info['dtype']=='int32' else canonical[i]
    global_stats=stats(dev,expected[i],mask)
    if i:
        dst,local=operation(info['operation'],regs)
        local_stats=stats(dev,local,mask);regs[dst]=dev
    else:local_stats=global_stats
    differ=(dev!=expected[i]) if info['dtype']=='int32' else dev.view('u4')!=expected[i].view('u4')
    first_global[(first_global==0)&differ&mask]=i
    if i:
        differ=(dev!=local) if info['dtype']=='int32' else dev.view('u4')!=local.view('u4')
        first_local[(first_local==0)&differ&mask]=i
    stage_results.append(dict(**info,vs_full_fp32_source_replay=global_stats,conditional_on_device_operands=local_stats))
np.savez(BUILD/'canonical_trace.npz',device=canonical,expected=np.stack([v.view('f4') if v.dtype=='i4' else v for v in expected]),first_global=first_global,first_local=first_local,coverage=coverage)
cc,ss=np.cos(angle),np.sin(angle);gold32=rotate(x,cc,ss);gold32[~active]=x[~active]
gold=gold32.astype('f2');gold[~active]=x[~active]
dc,ds=canonical[32],canonical[34]
conditional=rotate(x,dc,ds);conditional[~active]=x[~active]
assert np.array_equal(conditional.astype('f2')[active].view('u2'),actual[active].view('u2'))
spec=importlib.util.spec_from_file_location('unchanged_suite',ROOT/'tools/suite.py');suite=importlib.util.module_from_spec(spec);spec.loader.exec_module(suite)
spec=importlib.util.spec_from_file_location('original_template',ROOT/'templates/rotaryposemb_1743/scripts/RotaryPosEmb.py')
template=importlib.util.module_from_spec(spec);spec.loader.exec_module(template)
with np.errstate(invalid='ignore',over='ignore'):
    template_y=template.impl(x[None],p[None],10000.)[0]
same_class=(np.isfinite(template_y)==np.isfinite(gold))&(np.isnan(template_y)==np.isnan(gold))
template_comparison=dict(active_position_half_bit_differences=int(np.count_nonzero(template_y[active].view('u2')!=gold[active].view('u2'))),
    zero_position_nonfinite_class_differences=int(np.count_nonzero(~same_class[~active])),
    note='Original template has no explicit p=0 identity override, so nonfinite values can propagate through multiplication by zero. The user specification requires bit-preserving identity; the existing suite override and production behavior are unchanged. The analyzed 817 failures are all nonzero-position values.')
assert template_comparison['active_position_half_bit_differences']==0

def output_check(c,s):
    y=rotate(x,c,s);y[~active]=x[~active];y=y.astype('f2');y[~active]=x[~active]
    finite=np.isfinite(y)&np.isfinite(gold)
    err=np.zeros(y.shape,'f4');err[finite]=np.abs(y[finite].astype('f4')-gold[finite].astype('f4'))
    return dict(**suite.compare(y,gold),finite_elements_above_point_one=int(np.count_nonzero(err>.1)))

ablation={}
for label,c,s in [('full_fp32_source_replay',expected[32],expected[34]),('device',dc,ds)]:
    ablation[label]=output_check(c,s)
# CPU counterfactuals are attribution only. Never become acceptance golden.
sqrt_correct=np.sqrt(canonical[23])
fixed=replay(angle,schema,{24:sqrt_correct})
ablation['device_trig_with_only_sqrt_correctly_rounded']=output_check(fixed[32],fixed[34])
before_sqrt=replay(angle,schema,{23:canonical[23]})
assert np.array_equal(before_sqrt[32][active].view('u4'),fixed[32][active].view('u4'))
nm_c,nm_s=numpy_226_model(angle)
fused_q_c,fused_q_s=numpy_226_model(angle,quadrant_fused=True)
numpy_model=dict(cos=stats(nm_c,cc,mask),sin=stats(nm_s,ss,mask),output=output_check(nm_c,nm_s),
    fused_quadrant_model=dict(cos=stats(fused_q_c,cc,mask),sin=stats(fused_q_s,ss,mask),output=output_check(fused_q_c,fused_q_s),
        interpretation='CPU diagnostic of possible multiply/add contraction in quadrant rounding; matches alone do not prove the compiled NumPy instruction sequence.'),
    true_fmaf_cpu_probe=float(LIBM.fmaf(float(np.float32(1+2**-23)),float(np.float32(1-2**-23)),-1.)),
    cosine_scalar_fallback_elements=int(np.count_nonzero((angle>np.float32(71476.0625))&mask)),
    sine_scalar_fallback_elements=int(np.count_nonzero((angle>np.float32(117435.992))&mask)))
assert numpy_model['true_fmaf_cpu_probe']==-2**-46
runtime={k:{'ff':v['ff']} for k,v in np.lib.introspect.opt_func_info(func_name='^(sin|cos)$').items()}
result=dict(update_id=schema['update_id'],diagnostic_only=True,
    stage_comparisons=stage_results,first_global_divergence={str(int(k)):int(v) for k,v in zip(*np.unique(first_global[active],return_counts=True))},
    first_local_rounding_divergence={str(int(k)):int(v) for k,v in zip(*np.unique(first_local[active],return_counts=True))},
    duplicate_token_exports=duplicates,duplicate_stage_bit_differences=duplicate_diffs,
    coverage_nonzero_tokens=int(np.count_nonzero(coverage[active])),exported_tokens_per_core=core_spans,
    vs_prior_calibrated_export=prior_check,
    original_template_comparison=template_comparison,
    ablations_cpu_only=ablation,numpy_226_cpu_model=numpy_model,
    local_runtime=dict(numpy_version=np.__version__,machine=platform.machine(),glibc=platform.libc_ver(),sin_cos_dispatch=runtime),
    interpretation='A conditional comparison substitutes only current Device operands into one FP32 operation. CPU ablations do not modify Device code, the reference, thresholds, or acceptance.')
(HERE/'arithmetic_report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['stage_comparisons','exported_tokens_per_core']},indent=2))
