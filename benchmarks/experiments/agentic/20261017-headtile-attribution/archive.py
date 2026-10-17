"""CPU-only immutable evidence aggregation; no NPU or platform calls."""
import datetime,difflib,hashlib,json,math,re,shutil,statistics,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;B=R/'build/agentic_r6';REQ=H.name
sys.path.insert(0,str(R/'tools'));from suite import compare

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
protected=load(H/'protected_hashes.json')
for f,h in protected.items():assert sha(R/f)==h,(f,'changed')
parent=R/'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc';candidate=H/'kernel.asc';ps,cs=sha(parent),sha(candidate)
assert ps=='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556' and cs=='8d91182ab86ed3937f8127f3d427bb0777bbf94cffff83977b1bab580428eaea'
(H/'from_parent.patch').write_text(''.join(difflib.unified_diff(parent.read_text().splitlines(True),candidate.read_text().splitlines(True),fromfile='817f8364/kernel.asc',tofile='kernel.asc')))
correct=load(H/'correctness.json');assert correct['cases_total']==1765 and correct['all_bits_identical_count']==1765 and correct['original_reference_pass']==1764
for f in ['audit_normal_code.json','template_code.json']:assert load(H/f)['identical_count']==44
assert load(H/'device_code.json')['identical_count']==40
logs=H/'logs';logs.mkdir(exist_ok=True);tasks=[]
for p in sorted(B.glob('*task.log')):
 text=p.read_text();ids=re.findall(r'任务已提交: (task_\S+)',text);cards=re.findall(r'已获取设备 (\d+) 的锁',text)
 assert len(ids)==len(cards)==1 and '任务完成 (exit=0)' in text,p
 excluded=p.name=='fixed33_forward_task.log'
 tasks.append(dict(log=p.name,task_id=ids[0],device=int(cards[0]),max_time_seconds=60,completed=True,excluded_from_performance=excluded,exception='Submitted before previous task released; allocated device1. Native timings preserved but excluded; recollected device0 serially.' if excluded else None))
 shutil.copy2(p,logs/p.name)
for name in ['candidate_build.log','forward_build.log','reverse_build.log','normal_build.log','template_build.log','diag_build.log','assembly_build.log','assembly_S.log','normal_base.log']:
 shutil.copy2(B/name,H/name)
for variant in ['candidate','parent']:
 for f in B.glob(variant+'_*.log'):
  if f.name=='candidate_build.log':continue
  shutil.copy2(f,logs/f.name)
for name in ['candidate_normal','candidate_audit','diag_build']:
 shutil.copy2(B/name/'rope_runner.meta.json',H/(name+'_metadata.json'))
parent_rows=[json.loads(l) for l in (B/'parent_headtile_tails.log').read_text().splitlines() if l.startswith('{')]
assert len(parent_rows)==42 and all(r['guard_ok'] and r['launch_audit'] and r['one_kernel_per_iteration'] for r in parent_rows)
parent_new_audits=sum(r['iterations'] for r in parent_rows);assert parent_new_audits==126
# Recheck ordinary output identity and position-zero bits on frozen52, without generating inputs.
rs=[r for r in load(H/'validation_manifest.json') if r['group']=='base'];ts=[json.loads(l) for l in (B/'normal_base.log').read_text().splitlines() if l.startswith('{')];assert len(rs)==len(ts)==52
out=[]
for r,t in zip(rs,ts):
 c=r['case'];dt=c['dtype'];data=Path(r['directory']);a=np.fromfile(B/'output/normal/base'/(c['name']+'.bin'),dt).reshape(c['shape']);g=np.fromfile(r['golden'],dt).reshape(c['shape']);p=np.fromfile(r['parent_output'],dt).reshape(c['shape']);x=np.fromfile(data/'x.bin',dt).reshape(c['shape']);positions=np.fromfile(data/'positions.bin',np.int32).reshape(c['shape'][:2]);bits=np.uint16 if dt=='float16' else np.uint32
 assert np.array_equal(a.view(bits),p.view(bits));zero=bool(np.array_equal(a[positions==0].view(bits),x[positions==0].view(bits)));v=compare(a,g);assert v['passed'] and t['guard_ok'] and zero
 out.append(dict(**c,**t,**v,zero_identity_ok=zero,output_sha256=hashlib.sha256(a.tobytes()).hexdigest()))
normal=dict(label='agentic_r6_normal52',**load(B/'candidate_normal/rope_runner.meta.json'),cases=out,frozen_manifest=str(H.relative_to(R)/'validation_manifest.json'),all_bits_identical_parent=True,original_golden_thresholds_unchanged=True)
save(R/'benchmarks/results/agentic_r6_normal52.json',normal)
launch=load(R/'benchmarks/profiles/agentic_r6_launch75/launch_count.json');assert launch['single_kernel_rule_passed'] and launch['actual_device_kernel_tasks']==75 and launch['source_sha256']==cs
save(H/'tasks.json',dict(constraint='One card serially, max60s per task',exception='One scheduling mistake: excluded forward timing overlapped the end of the previous task and was allocated device1; all subsequent measurements waited for predecessor release and used device0. No sample from that run used for decisions.',tasks=tasks))
f=load(R/'benchmarks/results/agentic_r6_fixed33.json');b=load(R/'benchmarks/results/agentic_r6_family.json');controls=[c for c in f['cases'] if not(c['shape'][0]*c['shape'][1]>=128 and c['shape'][2]>32 and c['shape'][3]<=64 and c['shape'][3]%16)]
target=[c for c in f['cases'] if c not in controls];assert len(target)==2
assert all(min(c['direction_adjusted_speedup'].values())>1 for c in target+b['cases'])
known=correct['failures'][0];assert known['candidate']['max_abs_error']==known['parent']['max_abs_error']==32 and known['all_bit_differences']==0
perf=dict(fixed33_geomean=f['geometric_mean_speedup'],target=target,family12_geomean=b['geometric_mean_speedup'],family12_range=[min(c['speedup'] for c in b['cases']),max(c['speedup'] for c in b['cases'])],family_all_positive_both_orders=True,unchanged_controls_count=len(controls),unchanged_controls_geomean=math.exp(statistics.mean(math.log(c['speedup']) for c in controls)),regressions=[c for c in controls if c['speedup']<1],native_calls=f['run_kernel_calls']+b['run_kernel_calls'],native_device_tasks=f['actual_device_kernel_tasks']+b['actual_device_kernel_tasks'],uncertainty='Four block medians per source, ABBA+BAAB, both orders. Raw samples retained; no formal independent-repeat confidence interval claimed. Unchanged entry controls are reported, not attributed as implementation gains.')
manifest=dict(schema_version=1,request_id=REQ,tuning_request_id=REQ,state='experimental_archive_for_coordinator_review',parent_kernel_sha256=ps,kernel_sha256=cs,source_path=str(candidate.relative_to(R)),patch_from_parent=str((H/'from_parent.patch').relative_to(R)),production_ready=False,latest_changed=False,platform_submission_performed=False,known_precision_failure=known,performance=perf,validation=dict(total=1765,all_output_bits_identical=1765,original_reference_pass=1764,candidate_audited_calls=correct['audited_calls'],new_parent_audited_calls=parent_new_audits,normal52_pass=52,launch_count=launch,original_template_compiles=True,original_template_device_verify_pass=True,only_HeadTile_entries_changed=True),review='One measured general HeadTile alignment-period/flat-rotation candidate. Local evidence supports review; no platform score predicted, no ready publication.')
save(H/'experimental_candidate.json',manifest)
exp=dict(request_id=REQ,state='experimental_archive_complete',parent_source_sha256=ps,candidate_source_sha256=cs,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),algorithm_work_model='N=B*S,K=D/2; rotation6*N*H*K FP32 operations, same int32 positions, Device frequency and sin/cos. One sin/cos tuple per HeadTile job as parent; no new token cache.',numerical_chain='FP32 frequency -> FP32 angle -> unchanged SinCosFp32 -> separately rounded FP32 products -> output T rounding. Low subtraction expressed by exact sine sign inversion; device1765 full-bit identity plus CPU random/signedzero model. Inherited trig/library/FP16 rounding issue remains.',dataflow_model=str((H/'pre_implementation_model.json').relative_to(R)),dtype_shape_family='Existing nonaligned evenD18..62 excluding multiples16,H>32,N>=128,FP16/FP32; public geometry only',prior_attempts_reviewed=['round2/head_mask/head_packed/head_striped negatives','round3/layout_copy negative','R4 compact FP16 benefit/FP32 regression; no broad broadcast retrial','R5 generic pipeline local1.7x but official88558448.44 vs88339048.78; not continued'],hypothesis='Short32B-aligned coefficient-period Gather then regular Copy; one flat rotate-half Gather replaces padded split/repack. Same math helpers/GM transactions/tiling/dispatch.',expected_metric_changes='Fewer irregular Gather elements and padded arithmetic; lower VEC critical work/UB traffic. GM byte count unchanged. Scalar setup and Copy-mask control can grow, especially short/tail jobs.',bottleneck_evidence=['docs/rope_bottleneck_review.md',str((H/'diagnostics/stages.json').relative_to(R)),str((H/'sdk_audit.json').relative_to(R)),str((H/'pmu_comparison.json').relative_to(R))],changes=['Only HeadTileRotary class versus817; other40/44 device entries byte-identical','Dense flat coefficients use immutable period8/gcd(D,8); srcRepeatSize0 Copy, disjoint destination, explicit tail masks','Output slots hold FP32 sine scratch before output cast;work6capacity and numerical scratch sizing unchanged','Same input/output depth2,prefetch,GM copy parameters,p0/final-drain protocol'],validation=manifest['validation'],known_failure=known,local_performance=perf,diagnostic_source_sha256=sha(H/'diagnostics/instrumented.asc'),diagnostic_never_submitted=True,assembly_limits=load(H/'sdk_audit.json')['assembly_limit'],execution_exception='See tasks.json: excluded device1 timing; recollected serially on0. Recorded rather than hidden.',protected_hashes=protected,decision='Retain exactly one experimental archive for coordinator review; production-ready blocked by inherited amplitude failure; never changed latest',next_steps='Stop. Mac coordinator decides any real platform trial; no further implementation or guarded-trig task authorized.')
save(R/'benchmarks/experiments/agentic'/f'{REQ}.json',exp)
response=dict(request_id=REQ,state='blocked',completion='experimental_archive_complete',blocker_scope='production_ready_only',reason='Measured HeadTile gain archived for review. All1765 outputs identical to parent, but inherited valid-input FP16 max32 failure persists; no production-ready/latest publication.',parent_kernel_sha256=ps,kernel_sha256=cs,evidence_paths=[str((H/'README.md').relative_to(R)),str((H/'experimental_candidate.json').relative_to(R)),str((H/'correctness.json').relative_to(R)),str((H/'tasks.json').relative_to(R))],platform_submit_by_server=False)
save(R/'tuning_responses/rotary_pos_emb'/f'{REQ}.json',response)
hp=R/'benchmarks/experiments/agentic/history.json';history=load(hp)
entry=dict(request_id=REQ,parent_source_sha256=ps,candidate_source_sha256=cs,decision='experimental_archive; no production ready',hypothesis=exp['hypothesis'],evidence=str(H.relative_to(R)),fixed33_geomean=perf['fixed33_geomean'],family12_geomean=perf['family12_geomean'],all_bits_identical_cases=1765,known_failure_preserved=True)
key='experiments' if 'experiments' in history else 'requests';assert not any(x.get('request_id')==REQ for x in history.get(key,[]));history.setdefault(key,[]).append(entry);save(hp,history)
print('Archived',cs,'tasks',len(tasks),'nativecalls',perf['native_calls'],'candidateaudit',correct['audited_calls'])
