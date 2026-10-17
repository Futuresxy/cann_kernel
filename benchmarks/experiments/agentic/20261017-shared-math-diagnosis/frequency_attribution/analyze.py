"""CPU-only validation/decode of the single bounded frequency refinement."""
import hashlib,json,statistics,sys
from pathlib import Path
import numpy as np
H=Path(__file__).resolve().parent;P=H.parent;R=H.parents[4];B=R/'build/agentic_r7_frequency'
sys.path.insert(0,str(R/'tools'));from suite import compare

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
def analyze():
 meta=json.loads((H/'metadata.json').read_text());audit=json.loads((H/'source_audit.json').read_text());schema=json.loads((H/'trace_schema.json').read_text())
 assert sha(H/'instrumented.asc')==meta['source_sha256']==audit['source_sha256']
 assert sha(H/'diagnostic_runner.asc')==meta['runner_sha256']==audit['runner_sha256']
 assert sha(B/'compile/frequency_probe')==meta['binary_sha256']
 log=(H/'task.log').read_text();assert '任务完成 (exit=0)' in log and '已释放设备' in log
 runtime=[json.loads(l) for l in log.splitlines() if l.startswith('{')];records=json.loads((P/'input_manifest.json').read_text());old={c['case']['name']:c for c in json.loads((P/'coarse_stages.json').read_text())['cases']};assert len(runtime)==len(records)==8
 rowsout=[]
 for rec,rt in zip(records,runtime):
  c=rec['case'];name=c['name'];data=Path(rec['directory']);actual=B/'output'/(name+'.bin');shape=c['shape'];dt=c['dtype'];bits=np.uint16 if dt=='float16' else np.uint32
  for file,h in rec['input_sha256'].items():assert sha(data/file)==h,(name,file)
  assert sha(rec['parent_output'])==rec['parent_output_sha256']==sha(actual),name
  a=np.fromfile(actual,dt).reshape(shape);x=np.fromfile(data/'x.bin',dt).reshape(shape);pos=np.fromfile(data/'positions.bin',np.int32).reshape(shape[:2]);assert np.array_equal(a[pos==0].view(bits),x[pos==0].view(bits))
  g=np.fromfile(R/'build/agentic_r7/oracle'/name/'golden.bin',dt).reshape(shape);cmp=compare(a,g);assert cmp['passed']
  trace=Path(str(actual)+'.trace');raw=np.fromfile(trace,np.uint64).reshape(-1,96);active=[i for i,row in enumerate(raw) if row[86]==0x4652455144494137];assert active==list(range(old[name]['active_cores']))
  for k in range(len(raw)):
   row=raw[k]
   if k in active:assert row[84]==k and row[85]==len(active) and row[87]==1 and np.all(row[88:]==0xa5a5a5a5a5a5a5a5) and row[24+21]==32
   else:assert np.all(row==0xa5a5a5a5a5a5a5a5)
  phases={}
  for j,slot in enumerate(schema['slots']):
   ticks=[int(raw[k,j]) for k in active];calls=[int(raw[k,24+j]) for k in active];elems=[int(raw[k,48+j]) for k in active]
   phases[slot]=dict(mean_core_ticks=statistics.mean(ticks),min_core_ticks=min(ticks),max_core_ticks=max(ticks),calls_per_core=[min(calls),max(calls)],mean_core_calls=statistics.mean(calls),mean_core_elements=statistics.mean(elems),pooled_ticks_per_call=sum(ticks)/sum(calls) if sum(calls) else None)
  metadata=[dict(zip(schema['metadata'],map(int,raw[k,72:84]))) for k in active]
  assert all(m==metadata[0] for m in metadata)
  m=metadata[0];assert m['width']==shape[3]//2
  if m['mode_1scalar_2vector']==1:
   expected=[] if m['width']==8 else [1,10];assert m['width'] in [8,32] and m['Q31_fallback_count']==len(expected) and m['root_build_count']==int(bool(expected)) and m['Q31_attempt_count']==m['width']-1
   assert phases['scalar_try_q31']['calls_per_core']==[m['width']-1]*2 and phases['scalar_root_build_nested']['calls_per_core']==[int(bool(expected))]*2
   assert not m['chunk_count']
  else:
   assert not m['Q31_attempt_count'] and not m['Q31_fallback_count'] and not m['root_build_count']
   assert m['vector_stride'] in [472,512] and m['chunk_count']==(m['pitch']+m['vector_stride']-1)//m['vector_stride']
  assert rt['guard_ok'] and rt['launch_audit'] and rt['one_kernel_per_iteration'] and rt['kernel_launches']==rt['iterations']==2
  # Global spans contain counter-bookkeeping and nested markers. Not additive critical-path fractions.
  unmarked=old[name]['stages']['frequency']['mean_core_ticks'];freq=phases['frequency_inclusive']['mean_core_ticks']
  rowsout.append(dict(case=c,active_cores=len(active),metadata_per_core=m,phases=phases,original_reference=cmp,bitwise_parent_and_8d=True,position0_bits=True,trace_row_padding_and_inactive_rows_untouched=True,output_and_trace_guards=True,runtime_diagnostic_only=rt,prior_coarse_frequency_ticks=unmarked,new_nested_to_old_coarse_ratio=freq/unmarked,input_sha256=rec['input_sha256'],output_sha256=sha(actual),trace_sha256=sha(trace),cores=[dict(core=k,ticks=raw[k,:24].tolist(),calls=raw[k,24:48].tolist(),elements=raw[k,48:72].tolist(),metadata=raw[k,72:84].tolist()) for k in active]))
  if m['mode_1scalar_2vector']==1:print(name,'freq',round(freq,2),'log',round(phases['scalar_log53_setup']['mean_core_ticks'],2),'Q31',round(phases['scalar_try_q31']['mean_core_ticks'],2),'fall',round(phases['scalar_q53_fallback_inclusive']['mean_core_ticks'],2),'roots',round(phases['scalar_root_build_nested']['mean_core_ticks'],2),'recip',round(phases['scalar_reciprocal_pack']['mean_core_ticks'],2))
  else:print(name,'freq',round(freq,2),'log',round(phases['vector_logtheta_setup']['mean_core_ticks'],2),'table',round(phases['vector_exp2table']['mean_core_ticks'],2),'chunks',round(phases['vector_chunk_inclusive']['mean_core_ticks'],2),'recip',round(phases['vector_reciprocal_round']['mean_core_ticks'],2),'copy',round(phases['vector_restore_copy']['mean_core_ticks'],2))
 save(H/'stages.json',dict(request_id='20261017-shared-math-diagnosis',diagnostic_only=True,metadata=meta,clock='SYS_CNT ticks; no conversion to cycles/us',new_NPU_tasks=1,audited_invocations=16,all_outputs_bitwise_equal817_and8d=True,original_precision_8_of_8=True,guards_and_trace_bounds_pass=True,cases=rowsout))
if __name__=='__main__':analyze()
