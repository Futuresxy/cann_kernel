"""CPU-only source-bound decode and original-reference checks. No NPU calls."""
import argparse,hashlib,json,math,statistics,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;B=R/'build/agentic_r7'
sys.path.insert(0,str(R/'tools'));from suite import compare,generate

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')

def oracle():
 for r in json.loads((H/'input_manifest.json').read_text()):
  c=r['case'];data=B/'oracle'/c['name'];x,p,y=generate(c,data,c['seed'])
  for f,h in r['input_sha256'].items():assert sha(data/f)==h,(c['name'],f)
  y.tofile(data/'golden.bin')
 print('Original suite.generate replayed8 frozen inputs byte-identically in new diagnostic oracle directory')

def analyze(mode):
 metadata=json.loads((H/(mode+'_metadata.json')).read_text());binary=B/(mode+'_build/shared_probe');assert sha(binary)==metadata['binary_sha256'] and sha(H/'instrumented.asc')==metadata['source_sha256'] and sha(H/'diagnostic_runner.asc')==metadata['runner_sha256']
 tasklog=(B/(mode+'_task.log')).read_text();assert '任务完成 (exit=0)' in tasklog and '已释放设备' in tasklog
 runtime=[json.loads(l) for l in tasklog.splitlines() if l.startswith('{')];records=json.loads((H/'input_manifest.json').read_text());schema=json.loads((H/'trace_schema.json').read_text());assert len(runtime)==len(records)==8;out=[]
 for r,t in zip(records,runtime):
  c=r['case'];data=Path(r['directory']);shape=c['shape'];dt=c['dtype'];bits=np.uint16 if dt=='float16' else np.uint32
  for f,h in r['input_sha256'].items():assert sha(data/f)==h
  actual=B/mode/(c['name']+'.bin');a=np.fromfile(actual,dt).reshape(shape);p=np.fromfile(r['parent_output'],dt).reshape(shape);assert sha(r['parent_output'])==r['parent_output_sha256'];assert np.array_equal(a.view(bits),p.view(bits)),c['name']
  x=np.fromfile(data/'x.bin',dt).reshape(shape);pos=np.fromfile(data/'positions.bin',np.int32).reshape(shape[:2]);assert np.array_equal(a[pos==0].view(bits),x[pos==0].view(bits))
  g=np.fromfile(B/'oracle'/c['name']/'golden.bin',dt).reshape(shape);cmp=compare(a,g);assert cmp['passed']
  trace=Path(str(actual)+'.trace');rows=np.fromfile(trace,np.uint64).reshape(-1,96);active=[k for k,row in enumerate(rows) if row[86]==0x5348415245444d37];assert active and active==list(range(len(active)))
  stages={};cores=[]
  for k in active:
   row=rows[k];assert row[84]==k and row[85]==len(active) and row[87]==(mode=='detailed');assert row[24+19]==32
   cores.append(dict(core=k,metadata=row[72:84].tolist(),ticks=row[:24].tolist(),calls=row[24:48].tolist(),elements=row[48:72].tolist()))
  for i,name in enumerate(schema['slots']):
   ticks=[int(rows[k,i]) for k in active];calls=[int(rows[k,24+i]) for k in active];elements=[int(rows[k,48+i]) for k in active];totalcalls=sum(calls)
   stages[name]=dict(mean_core_ticks=statistics.mean(ticks),min_core_ticks=min(ticks),max_core_ticks=max(ticks),total_calls=totalcalls,per_core_calls_range=[min(calls),max(calls)],total_elements=sum(elements),pooled_ticks_per_call=sum(ticks)/totalcalls if totalcalls else None,pooled_ticks_per_processed_element=sum(ticks)/sum(elements) if sum(elements) else None,ticks_per_valid_output_element=sum(ticks)/math.prod(shape))
  assert t['guard_ok'] and t['launch_audit'] and t['one_kernel_per_iteration'];out.append(dict(case=c,actual_entry={'tiny':'DirectFloatRotary','deepseek_half':'AlignedRotary','deepseek_float':'DirectFloatRotary','prefill_h32_d1024_half':'LargeAlignedRotary','prefill_h32_d1024_float':'DirectFloatRotary','sequence8192':'BulkPositionRotary','sequence_d1024_half':'BatchedRotary','sequence_d1024_float':'BatchedRotary'}[c['name']],native_uninstrumented_baseline_us=r['native_baseline_us'],runtime_diagnostic_only=t,original_reference=cmp,parent_output_bit_differences=0,position0_bits=True,trace_guard_pass=True,active_cores=len(active),input_sha256=r['input_sha256'],trace_sha256=sha(trace),output_sha256=sha(actual),meta_first_core=cores[0]['metadata'],stages=stages,cores=cores))
  print(mode,c['name'],'cores',len(active),'freq',round(stages['frequency']['mean_core_ticks'],2),'trig',round(stages['trig_inclusive']['mean_core_ticks'],2),'rot',round(stages['rotation']['mean_core_ticks'],2),'empty/call',round(stages['empty']['pooled_ticks_per_call'],2))
 save(H/(mode+'_stages.json'),dict(mode=mode,diagnostic_only=True,metadata=metadata,all_outputs_bitwise_equal_parent=True,original_reference_pass=8,trace_and_output_guards_pass=True,audited_calls=sum(t['iterations'] for t in runtime),clock='SYS_CNT ticks; no core-cycle or microsecond conversion assumed',inclusive_stage_relations=dict(init_may_include_frequency=['BatchedRotary','BulkPositionRotary'],process_may_include_frequency=['AlignedRotary','LargeAlignedRotary','DirectFloatRotary'],trig_inclusive_contains_detailed_substages=True),cases=out))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['oracle','coarse','detailed']);args=ap.parse_args()
 if args.action=='oracle':oracle()
 else:analyze(args.action)
