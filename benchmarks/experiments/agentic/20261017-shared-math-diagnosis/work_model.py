"""CPU-only model for the actual selected public paths. No hidden-case inference."""
import json,math
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent
rows=[]
for r in json.loads((H/'input_manifest.json').read_text()):
 c=r['case'];b,s,h,d=c['shape'];N=b*s;K=d//2;e=2 if c['dtype']=='float16' else 4;pos=np.fromfile(Path(r['directory'])/'positions.bin',np.int32);P=48
 if h==1 and N>=16:
  bulk=d<=128;tile=min(64,2048//K) if bulk else (180*1024-2048)//(d*(34 if e==4 else 26));size=tile*d;pair=size//2;freq=(K+7)//8*8;batch=tile;groups=1;jobs=(N+tile-1)//tile;entry='BulkPositionRotary' if bulk else 'BatchedRotary'
  ub=4*size*e+3*size*4+3*pair*4+(512 if K>256 else freq)*4+(2*tile*4+(size+255)//256*32 if bulk else 0);scratch=3*size;stride=min(freq,((scratch-64)//17)//8*8);freq_chunks=(freq+max(32,stride)-1)//max(32,stride)
 else:
  tileEl=(8192 if e==4 else 12288) if d>=512 else (8192 if e==4 and N>=128 else (4096 if e==4 else 11264));tile=min(192,h,tileEl//d);groups=(h+tile-1)//tile;tile=(h+groups-1)//groups;size=max(tile*d,(K+7)//8*8);freq=(K+7)//8*8;large=e==2 and d>=512;entry='DirectFloatRotary' if e==4 else ('LargeAlignedRotary' if large else 'AlignedRotary');fullcos=e==2 and not large and d<=64 and tile>=16
  base=4*(size+8)*4 if e==4 else ((3*size*e+2*(size+8)*4) if large else (4*size*e+2*size*4));factor=5 if fullcos else 3;batch=min(16,size//((2 if e==4 else 1)*freq),(188*1024-base-freq*4)//(factor*freq*4));batch=max(batch,1);ub=base+(freq+factor*batch*freq)*4;scratch=size+8 if e==4 else (2*(size+8) if large else 2*size);stride=max(32,min(512,freq,((scratch-64)//17)//8*8));freq_chunks=(freq+stride-1)//stride;jobs=N*groups
 P=min(P,jobs);trigAngles=cacheCalls=tokenVisits=rotationOutputs=0;percore=[]
 for core in range(P):
  first=jobs*core//P;last=jobs*(core+1)//P
  if h==1 and N>=16:
   tokens=sum(min(tile,N-j*tile) for j in range(first,last));calls=last-first;angles=tokens*K;rot=tokens*d;visits=tokens
  else:
   cacheStart=-1;cacheEnd=-1;calls=angles=rot=0;visited=set()
   for j in range(first,last):
    token=j//groups;visited.add(token);heads=min(tile,h-(j%groups)*tile)
    if pos[token]==0:continue
    rot+=heads*d
    if cacheStart<0 or token>=cacheEnd:
     count=min(batch,(last-1)//groups+1-token);calls+=1;angles+=count*freq;cacheStart=token;cacheEnd=token+count
   visits=len(visited);tokens=visits
  trigAngles+=angles;cacheCalls+=calls;tokenVisits+=visits;rotationOutputs+=rot;percore.append(dict(core=core,jobs=last-first,token_visits=visits,trig_calls=calls,trig_elements=angles,rotation_elements=rot))
 rows.append(dict(case=c,actual_entry=entry,cores=P,N=N,H=h,D=d,K=K,element_bytes=e,tile=tile,groups=groups,jobs=jobs,trig_batch=batch,frequency_pitch=freq,frequency_scratch_floats=scratch,frequency_math_stride_vector_mode=stride,frequency_math_chunks_vector_mode=freq_chunks,selected_frequency_mode='scalarQ53' if K<=32 else 'vectorFP32_compensated',allocated_UB_bytes=ub,logical_XY_GM_bytes=2*N*h*d*e,logical_positions_bytes=4*N,rotation_FLOPs=3*N*h*d,frequency_valid_elements_total=P*K,trig_elements_total=trigAngles,trig_call_count_total=cacheCalls,token_visits_total=tokenVisits,rotation_valid_processed_elements=rotationOutputs,trig_logical_UB_bytes_34ops=trigAngles*324,per_core=percore))
report=dict(source_sha256='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556',cases=rows,trig_source_calls_by_group=dict(range_reduction=10,sin_polynomial=10,sqrt_input=3,sqrt=1,double_angle1=5,double_angle2=5),trig_logical_UB_bytes_per_angle=324,limitations=['Source-level API/element/byte model, not decoded ISA or measured UB/DRAM transactions','UB allocations omit unknown compiler scalar spills and control metadata; diagnostic trace adds independent GM and private scalar state','Frequency scratch stride describes the vector mode; K<=32 selects scalarQ53 and does not execute these vector chunks','Process/Init timing inclusions vary by class; no additive original-time fractions implied'])
(H/'work_model.json').write_text(json.dumps(report,indent=2)+'\n')
for r in rows:print(r['case']['name'],r['actual_entry'],'tile',r['tile'],'groups',r['groups'],'batch',r['trig_batch'],'UB',r['allocated_UB_bytes'],'trig',r['trig_elements_total'],'calls',r['trig_call_count_total'])
