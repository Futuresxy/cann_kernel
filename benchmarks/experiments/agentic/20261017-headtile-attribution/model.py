import json,hashlib,math
from pathlib import Path
R=Path.cwd();H=R/'benchmarks/experiments/agentic/20261017-headtile-attribution';records=[]
for d in range(18,65,2):
 if d%16==0:continue
 for h in range(33,257):
  pitch=(d//2+15)//16*16;tile=min(128,2048//pitch,h);cap=tile*pitch;period=8//math.gcd(d,8);u=period*d;length=(tile*d+7)//8*8
  assert u%8==0 and u<=2*cap and length<=2*cap
  assert (length-1)//d*d+((length-1)%d+d//2)%d<2*cap
  for rows in {tile,h%tile or tile,1}:
   n=(rows*d+7)//8*8;units,tail=divmod(n,u)
   assert max(0,units-1)<=255 and u//8<=4095
   # Map periodic copies to the mathematical cosine/sine column and half-rotation.
   for i in range(n):
    base=i%u;col=base%d
    rot=(i//u*u)+(base+d//2 if col<d//2 else base-d//2)
    assert rot<2*cap
    if i<rows*d:assert rot==i//d*d+(i%d+d//2)%d
  ub={str(e):4*cap*e+16*cap+24*cap+4*(2*cap+2*u)+4*pitch+((2*cap+255)//256*32) for e in [2,4]}
  assert max(ub.values())<188*1024
  records.append(dict(d=d,h=h,tile=tile,cap=cap,prefix=u,ub_bytes=ub))
model=dict(state='implementation_gate_supported',prior_negatives=[dict(name='round2/head_mask',reason='D64 aligned head packing and GatherMask+strided-copy regressed; this candidate changes the existing nonaligned HeadTile path, with independently measured layout costs'),dict(name='round3/layout_copy',reason='D64 strided per-head half copies and MulAddDst regressed; current proposed copies only replicate aligned coefficient prefixes, and retain separately rounded products'),dict(name='R4',reason='FP32 compact broadcast regressed6.07%; do not reuse it or generalize FP16 wins'),dict(name='R5',reason='local generic pipeline1.7x but platform48.44 versus81748.78; this is an independent measured HeadTile family')],
 stages='diagnostics/stages.json',instrumentation_caveat='SYS_CNT+PIPE_ALL serializes stages, empty-marker cost measured, not additive original critical-path fractions',
 hypothesis='Flat input rotation plus current-call generated alignment-period coefficient prefix copied with supported vector Copy repeats',
 API='dav_c220 Copy uses vcopy; count mask<=64,repeat<=255,32B-aligned bases and block/repeat units,srcRepeatSize0,dstRepeatSize=prefix/8<=31; disjoint immutable prefix and destination',
 numerical='FP32 numerical helper bodies unchanged; low output uses a*c+b*(-s), equivalent separately rounded normal/zero products under RN to a*c-b*s; full finite bitwise, signedzero and nonfinite gates mandatory before acceptance',
 liveness=['During frequency: original6cap float scratch unchanged','During trig: angle rotated[0:pitch],C z[0:pitch],S z[cap:cap+pitch],q c[0:pitch],temp c[cap:cap+pitch]','negS z[cap+pitch:cap+2pitch],then Gather coefficient prefixes to c[0:U] and output FP32[0:U]','Copy expands immutable aligned prefixes; load z overwrites dead compact coefficients','Gather rotated from z completes before z is overwritten;two Mul read original halves;Add c=products;Store from c overwrites dead output sine buffer','Output slot reuse waits via existing TQue MTE3_V;input ownership/prefetch and p0 protocol unchanged'],
 example_d30_h128=dict(parent_Gather_elements=12032,candidate_Gather_elements=4080,coefficient_Copy_elements=7440,rotation_arithmetic_parent=6*2048,rotation_arithmetic_candidate=3*3840,extra_neg_sine=16,parent_GM_bytes='2*N*H*D*sizeof(T) unchanged',note='Logical counts, not hardware instruction or bandwidth counts'),
 geometry_cases=len(records),max_ub_bytes={e:max(r['ub_bytes'][e] for r in records) for e in ['2','4']},geometries=records)
(H/'pre_implementation_model.json').write_text(json.dumps(model,indent=2)+'\n')
print('Checked',len(records),'geometries, UB maxima',model['max_ub_bytes'])
