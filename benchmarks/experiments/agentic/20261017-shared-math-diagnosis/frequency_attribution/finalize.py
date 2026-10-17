"""Archive the bounded frequency refinement; never changes a kernel, golden or ready pointer."""
import datetime,hashlib,json,re
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;R=H.parents[4]
def read(p):return json.loads(Path(p).read_text())
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
fine=read(H/'stages.json');control=read(H/'scalar_control/stages.json');tasks=[read(H/'task_record.json'),read(H/'scalar_control/task_record.json')]
assert sum(t['audited_invocations'] for t in tasks)==20 and all(t['exit_code']==0 and t['lock_released'] and t['no_overlap'] for t in tasks)
protected=read(P/'protected_hashes.json');assert all(sha(R/f)==s for f,s in protected.items())
save(H/'protected_hashes_rechecked.json',dict(all_equal=True,sha256=protected,canonical_runner_sha256=sha(R/'tests/runner.asc'),judge_or_reference_changed=False,environment_changed=False))
limitations=[
 'One eight-case fine frequency task plus one bounded two-case scalar control; two invocations per case but only last-call trace exported. No independent repeated statistical trial/CI.',
 'Fine per-column scalar instrumentation expands total frequency times1.823x/3.196–3.324x relative to prior coarse, so individual Q31/reciprocal/store numbers are descriptive of the instrumented image, not original time shares.',
 'Installed GetSystemCycle asm has only its SYS_CNT operand, no theta/log result dependency or memory clobber; PIPE_ALL is a core-local hardware barrier, not a proof of compiler ordering for pure integer arithmetic. Unanchored scalar log11/1.6–2.0tick is not accepted as isolated log latency.',
 'One bounded scalar control anchors start with an opaque read-write theta operand and end with both log/log31 result operands, plus memory clobbers. The MOV leaves numerical operands unchanged; output bit checks pass. Compiler allocation/scheduling, fetch/context and quantified timer overhead still differ from the original.',
 'Anchored tinylog47.75tick versus Aligned D64log6.33tick shows context sensitivity. No decoded ISA explains this discrepancy; do not claim either is an architecture-independent scalar log latency or infer the cause.',
 'Vector LogTheta is still an unanchored pure scalar subspan. Report its observed ticks, but do not claim exact log cost, avoidable fraction or lazy-log speedup from that value.',
 'All vector cases here use binary width512, theta10000 and no frequency fallback allocation; nonbinary ratio compensation, near-unity wide scalar dispatch, extreme theta, subnormal/overflow and allocated fallback behavior are not newly timed.',
 'Nested fallback includes root-build. Nested chunk includes its five subspans. Do not add overlapping stages; bookkeeping/synchronization lies outside subspans. Empty-marker calibration is not a universal correction.',
 'SYS_CNT ticks are not AIV cycles/us. Old coarse/fine were device1; refinement is device0. No native performance comparison, platform score prediction, new PMU replay, decoded instruction count or lane-utilization inference.',
 'Prior short init_wide PMU is a whole1x7x17x1024 operator, not a frequency-only microbenchmark. It is only qualitative evidence despite exact helper identity.',
 'Eight public theta10000 inputs and the two-case control are not universal validation. Inherited frozen amplitude failure max32 remains; no golden/threshold edit or production-ready claim.',
 'Axpy header existence is acknowledged from coordinator; no Axpy rounding test, IEEE single-rounding assumption, SinCos replacement or candidate authorization follows.'
]
conclusions=[
 dict(rank=1,family='Tiny FP32 K8 scalar initialization',evidence='Device confirms7Q31 attempts/core,0fallback,0root build. Dependency-anchored log47.75[min40,max53]tick versus remaining loop45.0[min40,max49]; inclusive102.375. Old unanchored fine log11 not a reliable isolated latency.',decision='A cheaper same-result log setup / delayed high-precision-log hypothesis is worth CPU numerical-bound investigation for small work only, not implementation in this task. Root/fallback optimization cannot help this frozen case.',expected_metric_direction='If legally/equivalently achieved, anchored setup and independent native tiny duration should decrease without added loop cost. Must preserve Q31 guard guarantees and all legal theta; no score or percentage forecast.'),
 dict(rank=2,family='K32 scalar DeepSeek/H1D64',evidence='31Q31 attempts,2ambiguity fallbacks and1root build/core,0power reuse. Fine Q31 totals33.6–34.6, reciprocal/pack31.1–32.1, fallback inclusive12.6–13.5 with nestedroots2.2–2.4ticks. Severe instrumentation amplification prevents original fractions. Anchored Aligned control log6.33 and remaining105.44,inclusive116.77.',decision='Do not prioritize root table: it is already built lazily once. Remaining per-column power/reciprocal/store/control is a stronger family target than uniform log pruning. No interpretation that2/31fallbacks dominate the entire initialization.',expected_metric_direction='Reduce validated scalar per-column/control/store work without changing the rounded pow-then-reciprocal semantics; require native small controls because prior frequency folding/tail pruning failed.'),
 dict(rank=3,family='K512 vector frequency initialization',evidence='Full512 chunk234.8–235.0ticks;472+40chunks380.08. Largest subchain is polynomial+compensation+2Gather+power reconstruction143.0–143.1 vs230.63. Log-product/range41.9/68.7; reciprocal24API25.3/39.8; destination copy1.0/1.88. Exp2Table22.1–24.6. Mode is vector: scalar Q31/root fallback counters are0 because that algorithm is not selected.',decision='The vector compensated exponential/table/power chain and scratch-caused extra chunk deserve higher priority than an isolated root-table/reciprocal/copy substitution. A lazy per-lane high-precision fallback would be a new algorithm requiring proof and measurement, not justified by scalar guard incidence.',expected_metric_direction='Future resource/layout hypothesis should reduce chunk count/dependent VEC/UB work while keeping frequency bits, fixed-input native controls and original UB limit; unchanged math API folding alone has already failed.' )
]
summary=dict(request_id='20261017-shared-math-diagnosis',scope='Coordinator frequency attribution refinement, diagnostic-only, same request/no new candidate',state='diagnosis_complete',parent_source_sha256='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556',fine_source_sha256=fine['metadata']['source_sha256'],scalar_control_source_sha256=control['metadata']['source_sha256'],new_tasks=tasks,new_NPU_tasks=2,new_actual_launch_audits=20,all_outputs_bitwise817_and8d=True,original_precision_checks_pass=10,trace_output_guards_and_disjoint_rows=True,full_inherited_failure='../known_failure.json (unchanged,max_abs_error32)',reused_source_bound_evidence='reused_evidence_and_math_proof.json',conclusions=conclusions,limitations=limitations,candidate_created=False,production_ready=False,latest_changed=False,canonical_changed=False,environment_changed=False,Axpy_or_SinCos_changes=False,decision='Bounded refinement complete. Preserve all evidence and stop for coordinator review; no further probing or implementation.',completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
save(H/'summary.json',summary)
lines=['# 频率初始化细分诊断（同一任务补充）','',
'本补充响应主控对`20261017-shared-math-diagnosis`的频率归因要求。仅诊断，父源码仍为官方883390/48.78的817f8364；未生成性能候选、未改canonical/ready/latest/正式runner/golden/阈值，也没有Axpy或SinCos改动。继承幅值FP16最大误差32完整保留。','',
'## 测量与边界','',
'只新增两项串行单卡任务，各max-time60。第一项8个已有冻结输入、16次启动；第二项仅tiny和DeepSeek FP16两项、4次启动，用于检查纯标量计时的编译器边界。每项均明确等待terminal及卡释放后才进入下一项，均exit0。全20次审计均每调用1kernel，10份输出与817/8d逐位相同，原精度、position0、y与独立trace首尾guard、每核行尾8格和未用核区域全部通过。所有原输入/父输出SHA重新核对。','',
'每核独立96uint64 trace行，实际写88格；GM单独分配并经诊断ABI传入，不占用tiny的64B输出，也不覆盖其他核。仅本核PIPE_ALL，无跨核全局同步。原频率helper保留；诊断克隆按原运算顺序执行，五个选中类移除计时包装后与父版逐字一致。','',
'原始[阶段数据](stages.json)、[标量对照](scalar_control/stages.json)、[任务记录](summary.json)、[源码同一性/旧证据范围](reused_evidence_and_math_proof.json)与[编译/二进制绑定](metadata.json)均归档。','',
'旧`agentic_r2_v9_init_wide`的helper与817逐字一致，可复用其短任务初始化摊薄现象，但其PMU测的是1×7×17×1024完整算子，不能视作独立frequency-only时间。没有重复采这组PMU。','',
'## 标量模式：实际分支与计时控制','',
'所有本次输入theta=10000。K8每核7次Q31，0次歧义回退、0次root构建；K32每核31次Q31，2次回退、1次root构建、0次相同power复用。CPU已有模型列出K32回退列1/10，Device只记录计数2，没有导出列号，因此不声称Device逐列验证了这两个编号。root表原本已按需延迟一次生成；K512向量模式根本不调用该标量回退。','',
'逐列细分后，scalar频率总tick相对旧粗测增为1.823倍（tiny）及3.196–3.324倍（K32）。Q31/reciprocal/store记录的是被强插桩程序；不能将其相加或换算原kernel占比。检查SDK发现GetSystemCycle的asm仅绑定SYS_CNT输出，无theta/log数据依赖；PIPE_ALL不证明纯整数指令不会跨边界移动。原细分log11/1.6–2.0tick因此不能作为孤立log延时。','',
'为此只加一个有上限的标量对照：同一已有MOV SYS_CNT语法，在开始绑定read-write theta位值（指令保持它不变），结束消费log/log31；有memory clobber，强制纯函数位于两个时点之间。剩余循环整体计时，移除逐列探针。编译成功且输出逐位一致；没有新安装/不支持接口重试。','',
'| 对照 | log53与log31设置/核ticks | 剩余标量循环/核ticks | frequency含包装/核ticks |','|---|---:|---:|---:|']
for c in control['cases']:
 t=c['stages'];lines.append(f"| {c['case']['name']} | {t['dependency_anchored_log53_setup']['mean_core_ticks']:.3f} | {t['remaining_scalar_loop_inclusive']['mean_core_ticks']:.3f} | {t['frequency_inclusive']['mean_core_ticks']:.3f} |")
lines+=['',
'同一log算法在tiny与Aligned上下文中的结果差异明显：tiny范围40–53tick，Aligned为6–14tick。寄存器锚定、编译上下文、取指/调度均可能影响，但没有解码ISA证据可作因果确认。只能分别报告；不能将47.75或6.33外推为统一硬件log延时，也不能把两个独立span当原始关键路径精确占比。','',
'K32细分的Q31约33.6–34.6、reciprocal/pack约31.1–32.1、fallback含root约12.6–13.5、nested root约2.2–2.4tick。它们有明显插桩扰动和纯标量调度边界限制，仅用于结合操作计数判断后续方向，不能宣称root只需某个百分比。','',
'**判断**：tiny中log设置与剩余循环同量级，值得未来先CPU研究精度界和更廉价的同结果log设置；改root/fallback对该输入无收益。K32则逐列工作更重，不支持一律优先log剪枝。已否定的Q53尾项剪枝/累加折叠不因此复活。原Q31守卫16单位覆盖log截断及求值误差，低精度log不能直接沿用该保证；本任务没有实现lazy log或任何数值近似。','',
'## 向量模式：chunk与恢复','',
'以下为每核累计SYS_CNT tick，仅诊断图像，nested span不可相加为原始总耗时。`poly/table/power`包含补偿链、两次Gather、pow结果指数重建和缩放；`dst copy`仅最后DataCopy/drain，不含前面的指数恢复。','',
'| 场景 | chunk几何 | log观察值* | Exp2表 | chunk含子阶段 | log乘积/range | poly/table/power | reciprocal/round | dst copy |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
for c in fine['cases']:
 m=c['metadata_per_core'];t=c['phases']
 if m['mode_1scalar_2vector']!=2:continue
 keys=['vector_logtheta_setup','vector_exp2table','vector_chunk_inclusive','vector_logproduct_range','vector_polynomial_table_power','vector_reciprocal_round','vector_restore_copy']
 geom='472+40' if m['vector_stride']==472 else '512'
 lines.append('| '+c['case']['name']+' | '+geom+' | '+' | '.join(f'{t[k]["mean_core_ticks"]:.2f}' for k in keys)+' |')
lines+=['',
'*LogTheta为未加寄存器依赖的纯标量span，存在同样的编译器移动风险；6.5–6.9tick仅观察值，不用于宣称其真实成本低。向量子链由有副作用的UB向量API和本核流水边界组成；仍没有解码ISA/真实UB事务和精确原始占比。','',
'已选binary-width分支共211次源级API：ratio2，log乘积/range43，poly/table/power141，reciprocal24（含两次Div及补偿），dst copy1。一般非二次幂分支多38次，本轮未测。它们不是211条ISA。源级最多工作量与测量的poly/table/power较重相符；之前仅将部分Mul/Add折为vmla并未降低实测VEC且原生收益不可靠，故不能再次仅靠API计数提候选。','',
'FP32多head的scratch8200float实际分为472+40两chunk，累计chunk380tick，另外三个512完整chunk约235tick。总频率细分相对旧粗测变化约−9%到+10%；跨card/图像不能把差值当改进。若未来研究workspace换取单chunk，需要覆盖全几何UB/liveness与native对照；本次不改tiling、scratch或算法。向量chunk主链优先于孤立的root表/最终copy。','',
'## 后续排序与停止条件','',
'1. tiny：先精度模型证明更廉价log与Q31守卫，关注设置摊薄；没有fallback可删。','2. K32：逐列Q31/reciprocal/UB写与控制，root已经lazy；不能根据未锚定短span宣称精确节省。','3. K512：补偿多项式/查表/pow恢复链、extra chunk与UB资源，比原本很小的末端copy更有证据。H1长序列中freq一次性设置仍远小于先前测到的重复trig，不能被本报告挤掉优先级。','',
'上述只是主控后续选择方向的依据，不授权开发/新近似。Axpy头文件存在不代表IEEE FMA，本轮未测试其舍入，也没有替换SinCos。大幅值FP16继承失败max32未解决，原reference/阈值未动。停止新增NPU探针、候选与平台提交，等待主控审阅。','',
'完整限制见[summary.json](summary.json)，包括量化、未解码ISA、仅最后一次trace、无CI、近unity/非对齐/极端theta未覆盖等；没有将这些probe event_us作为native收益。']
(H/'README.md').write_text('\n'.join(lines)+'\n')
# Augment, do not rewrite old closed outcomes or their data.
root=R/'benchmarks/experiments/agentic/20261017-shared-math-diagnosis.json';d=read(root);d['frequency_attribution_refinement']=dict(report=str((H/'summary.json').relative_to(R)),state='diagnosis_complete',new_NPU_tasks=2,additional_launch_audits=20,all_outputs_bitwise=True,candidate_created=False)
d['bottleneck_evidence'].append(str((H/'stages.json').relative_to(R))) if str((H/'stages.json').relative_to(R)) not in d['bottleneck_evidence'] else None
d['decision']='Shared-math and bounded frequency refinements complete; preserve inherited failure, canonical/latest/environment and stop for coordinator review.';save(root,d)
resp=R/'tuning_responses/rotary_pos_emb/20261017-shared-math-diagnosis.json';d=read(resp);d['frequency_refinement']=dict(report=str((H/'README.md').relative_to(R)),new_NPU_tasks=2,launch_audits=20,outputs_bitwise_equal=True,production_ready=False);d['reason']='Eight coarse/fine public cases plus frequency refinement complete;52 total single-launch audits. All diagnostic outputs bit-identical to817/8d and guard/precision gates pass on frozen ordinary inputs. Tiny log/control are context-sensitive; vector compensation/table/power chain and extra chunk have evidence. Inherited max32 failure retained; no candidate or approximation.';save(resp,d)
hist=R/'benchmarks/experiments/agentic/history.json';d=read(hist);entry=next(x for x in d['diagnostics'] if x.get('request_id')=='20261017-shared-math-diagnosis');entry['frequency_refinement']=dict(report=str((H/'summary.json').relative_to(R)),NPU_tasks=2,launch_audits=20,diagnostic_only=True);save(hist,d)
# Preserve old task records but make the whole-request totals unambiguous.
p=P/'tasks.json';d=read(p)
for t in tasks:
 if t['task_id'] not in [x['task_id'] for x in d['tasks']]:d['tasks'].append(dict(mode='frequency_refinement' if t['audited_invocations']==16 else 'anchored_scalar_control',**t))
d.update(new_NPU_tasks=4,actual_launch_api_calls=52,frequency_refinement_tasks=2,all_tasks_terminal_and_released=True);save(p,d)
notice='''\n## 频率归因补充（同一任务，已完成）\n\n主控要求的[频率细分及有依赖标量对照](frequency_attribution/README.md)已追加。新增两项有上限的串行单卡诊断，全20次启动审计及10份输出/trace guard通过，输出与817/8d逐位相同；本任务累计4项诊断任务、52次单启动审计。tiny确认0回退/0root；K32为2回退/1root，表已lazy。受控标量计时表明tiny log与剩余循环同量级，而D64为循环较重；数值强烈依赖编译上下文，不能用未锚定的纯标量span作原始占比。K512向量频率主要工作在补偿多项式/查表/pow恢复，472+40双chunk成本更高。未实现近似、Axpy、候选或新平台提交；继承max32失败不变。先前粗/细trig证据保持原样，更多计量限制见补充报告。\n'''
p=P/'README.md';text=p.read_text();assert '## 频率归因补充' not in text;p.write_text(text+notice)
p=R/'docs/rope_bottleneck_review.md';text=p.read_text();text+='\n共用数学链诊断另追加[频率归因](../benchmarks/experiments/agentic/20261017-shared-math-diagnosis/frequency_attribution/README.md)：tiny默认参数无Q31回退/root，K32回退2次且root已lazy；带依赖计时的log/剩余循环在tiny约47.8/45.0tick、D64约6.3/105.4tick，纯标量边界和编译上下文差异必须保留。K512向量频率的补偿多项式/查表/pow恢复子链比最终copy更重，FP32的472+40双chunk有可观察额外工作。新增两项单卡诊断均结束并释放，共20次单启动审计、输出/guard逐位检查通过，没有近似或候选。频率只初始化一次；H1长序列的重复trig仍是先前的主要方向。\n';p.write_text(text)
print('Frequency refinement report complete;2 new serial tasks/20 audits, original report evidence preserved, no candidate/latest')
