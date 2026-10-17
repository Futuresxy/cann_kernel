"""Source-derived V9 dispatch/UB/dataflow model. No device execution or tuning.

All byte counts are requested tensor payload, excluding compiler alignment and
runtime bookkeeping. UB movement is a logical operand model, NOT PMU traffic.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'operators/rotary_pos_emb/kernel.asc'
SHA='5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA


def ceildiv(a,b): return (a+b-1)//b
def align(a,b): return ceildiv(a,b)*b


def model(shape,dtype,theta=10000.,available=48):
    b,s,h,d=shape;t=b*s;w=d//2;byte=4 if dtype=='float32' else 2;pitch=align(w,16)
    scalar=(w<=32 or (theta!=1 and 1-2**-20<=theta<=1+2**-20)) and 2**-64<=theta<=2**64
    frequency='ScalarFrequencyConfig' if scalar else 'Frequencies'
    path=None;splits=0;tile_h=min(h,32);j=t*ceildiv(h,tile_h)
    if t<128 and t*h*d*byte<=2*1024*1024 and d<=256 and (h>1 or t<16) and 2**-64<=theta<=2**64:
        quantum=32//byte;splits=1
        if d%(2*quantum)==0:
            splits=min(w//quantum,8);part=align(ceildiv(w,splits),quantum);splits=ceildiv(w,part)
        elif d>64:splits=0
        if splits>1:
            splits=min(splits,max(1,min(available,2*available//j)))
            part=align(ceildiv(w,splits),quantum);splits=ceildiv(w,part)
            if part>32:splits=0
        if splits==1:splits=0
        if splits and j*4<=available:
            path='SmallRotary';cores=min(j,available//splits)*splits
            pitch=align(ceildiv(w,splits),quantum);cap=tile_h*pitch
            queues=4*cap*byte;work=max(5*cap,16)*4;trig=4*pitch*4;index=0;extra=0;scratch=max(5*cap,16)
            batch=1;tile=tile_h;groups=ceildiv(h,tile_h);frequency='ScalarFrequencyRange'
    if path is None:
        aligned=d%16==0;direct=aligned and byte==4 and not(h==1 and t>=16)
        elements=(8192 if byte==4 else 12288) if d>=512 else (4096 if byte==4 else 11264)
        if direct and t>=128:elements=8192
        tile_h=min(elements//d if aligned else 4096//pitch,192 if aligned else 32,h)
        if aligned:tile_h=ceildiv(h,ceildiv(h,tile_h))
        batched=aligned and h==1 and t>=16
        tile_t=min(64,2048//w)
        if batched and d>512:tile_t=min(64,(180*1024-2048)//(d*(34 if byte==4 else 26)))
        groups=ceildiv(h,tile_h);j=ceildiv(t,tile_t) if batched else t*groups
        if aligned and d<=128 and h==1 and t>=128:
            path='BulkPositionRotary';tile=max(8,tile_t//8*8);j=ceildiv(t,tile)
        elif not aligned and d<=64 and h>32 and t>=128:
            path='HeadTileRotary';tile=min(2048//pitch,128,h);groups=ceildiv(h,tile);j=t*groups
        elif d<=128 and h<=32 and t>=128 and (not aligned or(d==16 and 1<h<=8)):
            path='PackedRotary';tile=min(64,2048//(h*pitch));j=ceildiv(t,tile)
        elif batched:path='BatchedRotary';tile=tile_t
        elif direct:path='DirectFloatRotary';tile=tile_h
        elif aligned:path='LargeAlignedRotary' if d>=512 else 'AlignedRotary';tile=tile_h
        else:path='Rotary';tile=tile_h
        cores=min(j,available);extra=0;index=0;batch=1;full_cos=False
        freq=align(w,8)
        if path in ['AlignedRotary','LargeAlignedRotary','DirectFloatRotary']:
            size=max(tile*d,freq)
            if path=='DirectFloatRotary':
                queues=4*(size+8)*byte;work=0;scratch=size+8;initial=size//(2*freq)
            elif path=='LargeAlignedRotary':
                queues=3*size*byte;work=2*(size+8)*4;scratch=2*(size+8);initial=size//freq
            else:
                queues=4*size*byte;work=2*size*4;scratch=2*size;initial=size//freq
                full_cos=d<=64 and tile>=16
            cap=(188*1024-queues-work-freq*4)//((5 if full_cos else 3)*freq*4)
            batch=max(1,min(initial,16,cap));trig=(freq+(5 if full_cos else 3)*batch*freq)*4
        elif path in ['BatchedRotary','BulkPositionRotary']:
            size=tile*d;pair=size//2
            queues=4*size*byte;work=3*size*4;scratch=3*size
            trig=3*pair*4+(512 if w>256 else freq)*4
            if path=='BulkPositionRotary':queues+=2*tile*4;index=ceildiv(size,256)*32
        elif path in ['PackedRotary','HeadTileRotary']:
            rows=tile*h if path=='PackedRotary' else tile;capacity=rows*pitch
            queues=8*capacity*byte;work=6*capacity*4;scratch=6*capacity
            trig=pitch*4;index=5*capacity*4+ceildiv(2*capacity,256)*32;freq=pitch
        else:
            capacity=tile*pitch;queues=4*capacity*byte;work=5*capacity*4;scratch=5*capacity
            trig=(512 if w>256 else pitch)*4;freq=pitch
        if scalar:extra=64 if scratch<16 else 0
        else:
            full=17*max(32,freq)+64
            extra=0 if scratch>=full or scratch>6144 else full*4
    else:full_cos=False
    ub=queues+work+trig+index+extra
    return dict(shape=shape,dtype=dtype,theta=theta,path=path,frequency=frequency,
        device_kernels=1,tile_axis='tokens' if path in ['BatchedRotary','BulkPositionRotary','PackedRotary'] else 'heads',
        tile=tile,splits=splits if path=='SmallRotary' else 1,trig_token_cache=batch,
        full_cos=full_cos,jobs=j,cores=cores,jobs_per_logical_core_min=j//(cores//splits if path=='SmallRotary' else cores),
        jobs_per_logical_core_max=ceildiv(j,cores//splits if path=='SmallRotary' else cores),
        ub_requested=dict(queue_bytes=queues,work_bytes=work,trig_freq_bytes=trig,index_mask_bytes=index,frequency_fallback_bytes=extra,total_bytes=ub),
        gm_tensor_payload_bytes=2*t*h*d*byte,logical_positions_bytes=t*4,
        rotation_flops_all_nonzero=3*t*h*d,ideal_trig_pairs=t*w,
        rotation_mask_utilization=w/align(w,64),
        caveat='Requested UB payload excludes allocation rounding/bookkeeping; mask model excludes full-cos specialization and padding. This is not a timing prediction.')


examples=[
 ('tiny',[1,8,1,16]),('column_split',[1,1,8,128]),('deepseek',[2,512,128,64]),
 ('nonaligned_example',[2,16,3,24]),('packed',[1,256,3,24]),('head_tile',[1,256,128,24]),
 ('medium',[1,256,32,256]),('large512',[1,256,32,512]),
 ('wide1024',[1,256,32,1024]),('wide_nonalign',[1,256,3,1022]),
 ('wide_single',[1,256,1,1024]),('single128',[1,256,1,128]),
 ('single256',[1,256,1,256]),('stream',[4,8192,128,64]),('failed',[1,137,17,1024])]
samples=[dict(name=name,**model(shape,dtype)) for name,shape in examples for dtype in ['float16','float32']]
samples.append(dict(name='near_unity',**model([1,256,32,1024],'float16',1+2**-21)))
source=SOURCE.read_text();trig_source=source.split('__aicore__ inline void SinCosFp32')[1].split('__aicore__ inline void ScalarFrequencyRange')[0]
ops=dict(Counter(re.findall(r'\b(Muls|Adds|Mul|Sub|Cast|Sqrt)\(',trig_source)))
ub_per_angle=sum(ops[k]*v for k,v in dict(Muls=8,Adds=8,Mul=12,Sub=12,Cast=8,Sqrt=8).items())
profiles={}
for name in ['tiny','deepseek','wide','stream']:
    folder=ROOT/f'benchmarks/profiles/agentic_r1_v9_{name}'
    p=folder/'summary.json';r=json.loads(p.read_text());metadata=json.loads((folder/'metadata.json').read_text())
    profiles[name]=dict(summary_path=str(p.relative_to(ROOT)),summary_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        source_sha256=metadata['source_sha256'],case=metadata['case'],pipe=r['PipeUtilization'],
        replay_task_duration_us=r['OpBasicInfo']['Task Duration(us)'],
        caution='PMU/replay is bottleneck evidence only; do not compare replay Task Duration to native timings or sum overlapping pipeline ratios.')

report=dict(schema_version=1,source_sha256=SHA,device='Ascend910_9392 / dav-2201, 48 vector cores as reported by existing runs',
 scope='Source analysis and existing PMU/native evidence only. No optimization implemented or ready staged.',
 notation=dict(T='B*S',H='heads',D='rope_dim',W='D/2',M='T*H*D',q='dtype bytes (FP16=2, FP32=4)',C='active AIV cores'),
 complexity=dict(frequency='O(C*D) per invocation for fixed-degree Device math; frequency regenerated independently by each participating core.',
    angles_trig='Ideal O(T*D), shared across heads. Token/core boundary overlap adds at most C-1 repeated tokens for contiguous unsplit head jobs; batching can evaluate zero-position angles speculatively.',
    rotation='O(T*H*D): 4 multiplications + 2 additions per pair = 3*M FLOPs; casts/masks/indexing are additional.',
    minimum_gm='2*q*M + 4*T logical bytes; actual position load instructions and memory transactions exceed logical positions bytes.',
    arithmetic_intensity='Rotation alone: 3/(2*q) FLOP/GM-byte = 0.75 FP16, 0.375 FP32. This excludes trig/init and does not establish the critical pipeline.',
    time_lower_bound='Launch + unhidden startup + steady-state max(MTE2 demand, MTE3 demand, UB/VEC demand, scalar issue demand), plus dependency/tail effects. Frequency generation may overlap the first prefetch in aligned paths. Do not sum overlapping PMU percentages or treat this qualitative model as measured stage timing.'),
 precision_chain=dict(
    contract='e=round32(i/W); u=round32(theta**e); f=round32(1/u); a=round32(p*f); s/c=FP32 trig(a); products/addition rounded FP32; FP16 RINT cast last. Exact real inverse power is not the same rounding chain.',
    local_bounds='|delta_angle| <= |p|*|delta_freq| + product rounding. For normal finite values, |delta_sin| and |delta_cos| <= |delta_angle| plus trig evaluation error. |delta_y| <= |a_input|*|delta_c|+|b_input|*|delta_s| plus product/add rounding.',
    fp16_boundary='No amplitude-independent absolute-error bound survives a discontinuous FP16 cast unless the perturbed FP32 values remain in the same rounding bin. For |y| in [32768,65504], adjacent finite half values are 32 apart.',
    range='V9 reduces by nearest 2*pi quotient, three split constants, scales by 1/4, evaluates a degree-9 sine polynomial, derives quarter cosine using sqrt, then reconstructs full angle by double-angle identities.',
    limitation='For theta<1, angle can exceed 131072 because inv_freq>1; the position bound alone is not an angle bound. FP32 extremes, overflow and int32 quotient range require a separate domain audit before replacing trig globally.'),
 reuse=dict(allowed='Within invocation: frequency across local tokens, token sin/cos across heads and UB token batches. All values derived from current theta/positions on Device.',
    boundary='No portable global synchronization is present. Independent cores repeat init and boundary-token trig; sharing across cores requires a separately proven single-kernel synchronization/design, not an extra launch.',
    lut='A full runtime sin/cos table over p=0..131072 uses 2*131073*W*4 bytes: ~512 MiB at D1024, and O(131073*D) work each call. Precomputed/cross-invocation generated result tables are forbidden. Existing UB trig batching is already legal reuse.',
    alternatives='Rotate-half and complex multiply have the same 4 mul/2 add core. Gauss 3-multiply rearrangements add extra additions and alter rounding; no measured support. Recurrence depends on positions and accumulated error; arbitrary input positions provide no guaranteed recurrence.',
    no_hidden_shapes='Model dispatch uses public shape/dtype/theta only. No mapping from platform testcase number to shape is inferred.'),
 source_operation_model=dict(SinCosFp32_API_calls_per_vector=ops,total_calls=sum(ops.values()),
    logical_ub_bytes_per_trig_element=ub_per_angle,
    aligned_trig_with_angle_and_neg_s_bytes=ub_per_angle+16,
    logical_rotation_ub_bytes_per_pair_two_mul_two_mad=56,
    fp16_cast_load_store_ub_bytes_per_pair=24,
    note='Logical source operand bytes, excluding broadcasts/repeat-lane utilization and compiler/hardware effects. Both wide rotation variants have the same arithmetic FLOPs and nominal operand bytes; changed vmadd/vmla operand placement/throughput is supported by timing, not a proven reduction in GM traffic.'),
 pipeline_models=[
    dict(path='SmallRotary',types='FP16/FP32, very low occupancy only',flow='two strided half-column GM loads -> cast -> 5 work arrays -> 4mul/2add -> cast -> two strided stores',queues='in1/out1; PIPE_ALL per job; no inter-job DMA overlap',reuse='frequency range per core; one token sin/cos reused for local head jobs',risk='extra bursts, padded masks and replicated position loads offset added column parallelism'),
    dict(path='Rotary',types='FP16/FP32 unaligned fallback',flow='two strided half loads -> padded halves -> replicated cos/sin UB -> 4mul/2add; reload original first half in UB for second output -> two stores',queues='in1/out1; PIPE_ALL each job',reuse='one-token trig per core, copied over padded head rows',risk='noncontiguous DMA, padding, explicit UB copies and low queue overlap'),
    dict(path='AlignedRotary',types='reachable main branch FP16 D<512 many-head; FP32 uses DirectFloat',flow='contiguous whole-head load -> half cast into z -> 2Mul+2MulAddDst into r -> half cast -> whole-head store; D<=64 large head tile uses full-cos specialization',queues='in2/out2; prefetch next job before compute, final PIPE_ALL',reuse='batch<=16, capped by 188KiB; frequency scratch reuses work arrays',risk='cache growth competes with head-tile/queue space; full-cos changes mask utilization'),
    dict(path='LargeAlignedRotary',types='reachable FP16 aligned D>=512 many-head; FP32 uses DirectFloat',flow='same two-work-array rotation, work stride=size+8; D>512 wide entry selects same class',queues='in2/out1; next input prefetched; one output slot may serialize later store ownership',reuse='batch<=16 subject to UB; no cross-call results',risk='VEC-bound D1024 measured, not a demonstrated HBM limit'),
    dict(path='DirectFloatRotary',types='FP32 aligned, except H1 token-batched path',flow='GM load into input queue used directly as z -> output queue r -> GM; no separate cast or z/r work buffers',queues='in2/out2, output tensor temporarily supplies trig/frequency scratch; next-input prefetch',reuse='batch<=min(16, size/(2*freq_size)); trig scratch must finish before output overwrite',risk='cannot directly transplant half wide dataflow without rechecking UB liveness'),
    dict(path='BatchedRotary',types='FP16/FP32 aligned H1 T>=16, unless bulk-position',flow='multiple tokens -> per-row scalar position angles -> batched trig -> 3 FP32 work arrays, 4mul/2add -> cast -> GM',queues='in2/out2, prefetch, p0 rows copied back from original input',reuse='frequency across all local token tiles; no head reuse possible',risk='trig dominates at H1; per-row scalar GetValue and casts remain'),
    dict(path='BulkPositionRotary',types='FP16/FP32 aligned H1 D<=128 T>=128',flow='batched token/position DMA -> cast positions -> Brcb/Copy -> trig/rotation -> Select zero mask -> store',queues='in2/out2 plus positionIn2',reuse='frequency across tile; vector position expansion removes per-token scalar loads',risk='broadcast copies/zero masks add VEC/UB traffic'),
    dict(path='PackedRotary',types='FP16/FP32 narrow D, small H; token-batched',flow='contiguous GM -> device-generated Gather indices -> unpack halves/trig broadcast -> rotation -> Gather packing -> GM',queues='in2/out2 with explicit VEC barriers for Gather dependencies',reuse='frequency and indexes per core; token trig broadcast across heads',risk='6 FP32 capacity arrays + 5 index arrays + mask; index startup/Gather can outweigh saved DMA'),
    dict(path='HeadTileRotary',types='FP16/FP32 unaligned D<=64, H>32,T>=128',flow='contiguous head-tile load -> Gather pair packing -> broadcast trig -> rotation -> repack -> store',queues='in2/out2; explicit index/trig dependencies',reuse='one token trig per core and head jobs; indexes once',risk='same heavy index/UB footprint as Packed; tail rows need masks')],
 branch_samples=samples,existing_profiles=profiles,
 bottleneck_conclusions=[
    'Tiny: scalar ratio 76.46%, VEC 19.02%, eight blocks. Supports initialization/control/occupancy concern, but PMU does NOT isolate frequency initialization duration.',
    'DeepSeek FP16: VEC 70.98%, MTE2 61.07%, MTE3 28.78%. Mixed compute/input path, all overlap; target shared UB/compute changes only after numerical correctness is resolved.',
    'Wide FP16: VEC 86.32%, MTE2 25.07%, MTE3 13.94%. Existing isolated wide dataflow lowers VEC time 26.3444 -> 23.6691us and paired native 31.981 -> 29.2805us (~1.0922x). Preserve evidence; currently precision-blocked by V9-inherited failure.',
    'Stream: MTE2 93.72%, MTE3 63.88%, VEC 47.13%. Source reads/writes once; existing native 841.226us for 1GiB minimum tensor I/O implies ~1.276TB/s effective traffic, not an independently measured hardware bandwidth ceiling.',
    'Installed disassembler cannot decode HiIPU instructions; API-to-intrinsic mappings and measured rounding exist. Do not invent instruction counts, bank-conflict causes or I-cache bottlenecks (recorded I-cache misses are zero).',
    'Native fixed-input ABBA+BAAB decides performance; profiling replay durations above explain utilization only. No new performance tasks were run for this diagnostic.'
 ],
 evidence_paths=dict(wide='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/experiment.json',
    wide_pmu='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/pmu_comparison.json',
    assembly_and_semantics='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/sdk_semantics.json',
    stream_native='benchmarks/experiments/agentic/20261017T032204914387Z-5917d3aaeb69/score_analysis.json',
    rejected_attempts='benchmarks/experiments/agentic/history.json',precision='benchmarks/diagnostics/rope_v9_system/stage_report.json'))
(HERE/'system_model.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps([(v['name'],v['dtype'],v['path'],v['ub_requested']['total_bytes']) for v in samples],indent=2))
