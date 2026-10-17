"""Decode diagnostic-only timestamps; never a correctness/performance candidate."""
import json,hashlib
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[5];H=Path(__file__).resolve().parent;B=R/'build/agentic_r6'
names=['alloc','frequency','indices','post_init','dequeue_prefetch_position','trig','coeff_gather','load_cast','input_gather','rotation','output_gather','store_cast','enqueue_dma_free','final_drain','loop_control','empty_marker','zero_position'];out=[]
for c in json.loads((H/'cases.json').read_text()):
 n=c['shape'][0]*c['shape'][1];h,d=c['shape'][2:];pitch=(d//2+15)//16*16;tile=min(128,2048//pitch,h);g=(h+tile-1)//tile;jobs=n*g;e=2 if c['dtype']=='float16' else 4
 raw=B/(c['name']+'_trace.bin');data=raw.read_bytes();rows=[]
 for k in range(min(48,jobs)):
  begin=jobs*k//48;offset=((begin//g*h+(begin%g)*tile)*d*e+7)//8*8;t=np.frombuffer(data[offset:offset+160],np.uint64).tolist();assert t[18]==k and t[19]==0x444941474f4e4c59
  rows.append(dict(core=k,jobs=t[17],ticks=dict(zip(names,t[:17]))))
 out.append(dict(case=c,clock='SYS_CNT ticks, no assumed conversion to vector core cycles',trace_file_sha256=hashlib.sha256(data).hexdigest(),mean_core_ticks={name:float(np.mean([r['ticks'][name] for r in rows])) for name in names},cores=rows))
(H/'stages.json').write_text(json.dumps(dict(warning='PIPE_ALL instrumentation removes overlap. Stage sums are not original critical-path shares. Mark costs measured with empty_marker.',cases=out),indent=2)+'\n')
