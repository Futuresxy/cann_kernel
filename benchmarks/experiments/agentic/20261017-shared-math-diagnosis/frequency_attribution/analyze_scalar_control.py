"""CPU-only bounded scalar-control validation. No additional NPU calls."""
import hashlib,json,re,statistics,sys
from pathlib import Path
import numpy as np
H=Path(__file__).resolve().parent;D=H/'scalar_control';R=H.parents[4];B=R/'build/agentic_r7_frequency_scalar'
sys.path.insert(0,str(R/'tools'));from suite import compare
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
m=json.loads((D/'metadata.json').read_text());assert sha(D/'instrumented.asc')==m['source_sha256'] and sha(D/'diagnostic_runner.asc')==m['runner_sha256'] and sha(B/'compile/frequency_probe')==m['binary_sha256']
log=(D/'task.log').read_text();assert '任务完成 (exit=0)' in log and '已释放设备 0 的锁' in log
rt=[json.loads(l) for l in log.splitlines() if l.startswith('{')];rec=[r for r in json.loads((H.parent/'input_manifest.json').read_text()) if r['case']['name'] in m['cases']];assert len(rt)==len(rec)==2
out=[]
for r,t in zip(rec,rt):
 c=r['case'];actual=B/'output'/(c['name']+'.bin');shape=c['shape'];dt=c['dtype'];bits=np.uint16 if dt=='float16' else np.uint32;data=Path(r['directory'])
 for file,h in r['input_sha256'].items():assert sha(data/file)==h
 assert sha(actual)==r['parent_output_sha256']==sha(r['parent_output'])
 a=np.fromfile(actual,dt).reshape(shape);g=np.fromfile(R/'build/agentic_r7/oracle'/c['name']/'golden.bin',dt).reshape(shape);cmp=compare(a,g);assert cmp['passed']
 x=np.fromfile(data/'x.bin',dt).reshape(shape);pos=np.fromfile(data/'positions.bin',np.int32).reshape(shape[:2]);assert np.array_equal(a[pos==0].view(bits),x[pos==0].view(bits))
 trace=Path(str(actual)+'.trace');rows=np.fromfile(trace,np.uint64).reshape(-1,96);active=[i for i,row in enumerate(rows) if row[86]==0x4652455144494137];assert active==list(range(8 if c['name']=='tiny' else 48))
 for i,row in enumerate(rows):
  if i in active:assert row[84]==i and row[85]==len(active) and row[87]==1 and np.all(row[88:]==0xa5a5a5a5a5a5a5a5) and row[26]==1 and row[27]==1 and row[45]==32
  else:assert np.all(row==0xa5a5a5a5a5a5a5a5)
 v={}
 for idx,name in [(0,'frequency_inclusive'),(2,'dependency_anchored_log53_setup'),(3,'remaining_scalar_loop_inclusive'),(21,'empty')]:
  ts=[int(rows[i,idx]) for i in active];cs=[int(rows[i,idx+24]) for i in active];v[name]=dict(mean_core_ticks=statistics.mean(ts),min_core_ticks=min(ts),max_core_ticks=max(ts),pooled_ticks_per_call=sum(ts)/sum(cs))
 assert t['guard_ok'] and t['one_kernel_per_iteration'] and t['kernel_launches']==t['iterations']==2
 metadata=[rows[i,72:84].tolist() for i in active];assert all(row==metadata[0] for row in metadata)
 out.append(dict(case=c,input_sha256=r['input_sha256'],output_sha256=sha(actual),trace_sha256=sha(trace),original_reference=cmp,bitwise817_and8d=True,position0_bits=True,trace_bounds_and_guards=True,active_cores=len(active),metadata_per_core=metadata[0],stages=v,runtime_diagnostic_only=t,cores=[dict(core=i,ticks=rows[i,:24].tolist(),calls=rows[i,24:48].tolist(),elements=rows[i,48:72].tolist(),metadata=rows[i,72:84].tolist()) for i in active]))
 print(c['name'],json.dumps(v))
save(D/'stages.json',dict(request_id='20261017-shared-math-diagnosis',diagnostic_only=True,metadata=m,cases=out,outputs_all_bitwise_parent=True,original_precision_pass=2,one_kernel_per_invocation=True,launch_api_checks=4,trace_bounds_output_guards=True,clock='SYS_CNT ticks, no conversion or original critical-path percentages'))
tid=re.search(r'任务已提交: (\S+)',log)[1];save(D/'task_record.json',dict(task_id=tid,device=0,max_time_seconds=60,exit_code=0,lock_released=True,no_overlap=True,predecessor_task_id=m['predecessor_task_id'],predecessor_terminal_and_release_verified=True,audited_invocations=4,one_kernel_per_invocation=True,raw_log_sha256=sha(D/'task.log')))
