"""Publish only source-bound numerical diagnosis and a proposal for review."""
import hashlib
import json
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build/rope_v9_trig_internal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
schema=json.loads((HERE/'trace_schema.json').read_text())
ar=json.loads((HERE/'arithmetic_report.json').read_text())
hp=json.loads((HERE/'high_precision_report.json').read_text())
runtime=json.loads((HERE/'reference_runtime.json').read_text())
assert sha(ROOT/'operators/rotary_pos_emb/kernel.asc')==schema['source_sha256']
assert sha(BUILD/'probe_half.bin')==schema['baseline_output_sha256']
assert schema['math_statement_identity']
shutil.copyfile(BUILD/'task.log',HERE/'task.log')
log=(HERE/'task.log').read_text();metadata=json.loads(next(line for line in log.splitlines() if line.startswith('{"device":')))
assert metadata['device_kernel_launches']==1 and '已释放设备' in log and '任务完成 (exit=0)' in log
task_id=next(v for v in log.split() if v.startswith('task_'))
workload=ROOT/'benchmarks/analysis/v9_workload_model.json'
assert workload.read_bytes()==(BUILD/'workload_model.json').read_bytes()
assert ar['numpy_226_cpu_model']['fused_quadrant_model']['cos']['bit_differences']==0
assert ar['numpy_226_cpu_model']['fused_quadrant_model']['sin']['bit_differences']==0
assert hp['sqrt_cpu_vs_80_digit_rounding_bit_differences']==0
report=dict(schema_version=1,update_id=schema['update_id'],state='diagnosis_complete_awaiting_review',diagnostic_only=True,
 source_and_input_hashes=dict(kernel=schema['source_sha256'],input=schema['input_sha256'],trace_math=schema['traced_math_sha256'],
    raw_internal_trace=sha(BUILD/'stages.bin'),baseline_and_probe_output=schema['baseline_output_sha256'],
    probe_binary=sha(BUILD/'probe_build/trig_internal_probe'),
    original_template=sha(ROOT/'templates/rotaryposemb_1743/scripts/RotaryPosEmb.py'),
    unchanged_suite=sha(ROOT/'tools/suite.py'),
    user_rules={name:sha(ROOT/name) for name in ['AGENTIC.md','kernel_requirement.md','forbidden.md']},
    strategy=sha(ROOT/'docs/rope_optimization_strategy.md'),workload_model=sha(workload)),
 probe_output_identity=dict(elements=2384896,bit_differences=0,nonzero_tokens=116,active_angle_elements=59392,
    duplicated_token_exports=ar['duplicate_token_exports'],duplicate_stage_bit_differences=0,
    trace_layout='[48 cores,35 stages,8 token slots,512 columns], disjoint per core; absent slots explicitly initialized to NaN, excluded by independently reconstructed call coverage.',
    layout='Same work/trig allocations and offsets as the previously calibrated probe, same V9 tileHeads9/trigBatch9 and contiguous job partition; diagnostic input/output TBuf slots. Timing is not used.',
    vs_prior_calibrated_export=ar['vs_prior_calibrated_export'],
    operation_audit='All 34 original SinCos operation statements are identical and in identical order; only barriers and GM exports are inserted.'),
 stage_comparisons=dict(arithmetic_report='benchmarks/diagnostics/rope_v9_trig_internal/arithmetic_report.json',
    high_precision_report='benchmarks/diagnostics/rope_v9_trig_internal/high_precision_report.json',
    first_device_arithmetic_divergence='Stage24 Sqrt(c,c,n); all other operations agree with separate-rounding FP32 conditional on actual Device operands for this input.',
    sqrt_comparison=ar['stage_comparisons'][24]['conditional_on_device_operands'],
    sqrt_signed_ulp=hp['device_sqrt_signed_ulp_histogram'],
    mathematical_function_comparisons=hp['mathematical_function_comparisons'],
    polynomial_error_separation=hp['polynomial_separation'],
    unit_circle_defect_max_abs=hp['unit_circle_defect_max_abs']),
 fp16_boundary_attribution=hp['fp16_boundary_attribution'],
 conclusions_zh=[
    '本轮只补充已有三角求值内部的缺失阶段，不重新计时、调参或发布候选。新增探针输出2384896个半精度元素与V9逐位相同，35个阶段均已导出。',
    '与逐条FP32重放相比，第一处设备运算差异确定为第24步Sqrt：59392个有效元素中5224个相差1ULP；其中1293个偏低、3931个偏高。其余基本运算在使用设备操作数条件下均一致。',
    '不能把817个最终超限都归咎于sqrt：729个超限元素对应的sqrt没有这种舍入差异。CPU仅改成正确舍入sqrt会消除52个、引入37个超限，仍有802个超限，max_abs_error仍32。',
    '原多项式在同一四分之一角上，精确求值的系数/截断误差最大1.14247e-9，FP32求值舍入误差最大5.92514e-8；单纯增加多项式项数不针对当前主要误差。',
    '相对80位数学计算，范围缩减最大误差1.46013e-7，四分之一角为3.65032e-8；最终倍角恢复后cos/sin误差为5.30248e-7/4.35518e-7。即使后续基本运算逐条正确舍入，算法仍与参考的浮点求值路径不同。',
    '已从本机NumPy2.2.6的ARM汇编核实象限舍入处及多项式使用真实FMLA。按实际融合顺序的CPU模型复现全部59392个有效cos和sin，且本冻结输入最终输出与当前参考零差异；此为模型验证，不是Device修复。',
    '参考模型表明需要复现明确的浮点语义，而非仅追求更接近实数函数。NPU vmadd/vmla已证实不具备所需single-rounding语义，不能移植CPU FMA名称来假定等价。',
    '原模板非零位置输出与当前suite逐位一致；零位置非有限值有3个类别差异，来源是模板没有规格要求的身份分支。现有suite和Device身份行为未改，这与本次817个非零位置失败独立。'],
 reference_model=dict(runtime_report='benchmarks/diagnostics/rope_v9_trig_internal/reference_runtime.json',
    primary_source=runtime['pinned_upstream_source'],
    decoded_local_host_assembly=runtime['decoded_host_evidence'],
    cpu_model_result=ar['numpy_226_cpu_model'],
    original_template_comparison=ar['original_template_comparison'],
    acceptance_note='The original template, current local golden/thresholds and official judge are unchanged. High-precision and software libm models are diagnostic, never substitute golden.'),
 repair_proposal=dict(name='Reference-compatible quadrant reduction and direct sin/cos, using a proven software RN-FMA primitive',
    state='proposal_only_not_implemented_not_ready',
    evidence='The fused-quadrant CPU model is bit-identical to the local reference trig on the fixed active input. Increasing V9 degree or correcting sqrt alone is unsupported by the attribution.',
    algorithm='Generate frequencies and FP32 angle as V9. Reduce by pi/2 with compensated split constants, evaluate direct sine/cosine on [-pi/4,pi/4], select quadrant/sign. All math would execute on Device, one invocation/one kernel, current-call UB only.',
    payload_dependency_contract='Any future implementation must be self-contained in kernel.asc, compile with the original template C++/CANN settings and existing dav-2201 APIs, and require no packages, generated headers, libraries or link/build changes. NumPy/mpmath/libm models and standalone CMake here are development-only.',
    installed_api_constraints='Read benchmarks/analysis/cann9_api_compatibility.json: joint SDK SinCos and SqrtConfig overloads are not exposed for dav-2201. Do not try these as drop-in repairs or modify the environment; the proposal uses no unsupported API.',
    rounding_argument='Matching the local model requires each genuine fused operation to produce RN32(a*b+c), including contracted quadrant rounding. A Device implementation must first prove a software FP32 high/low product and sum with a rounding-boundary guard; ordinary compensated accumulation alone is not a proof. Final FP32 products/addition and FP16 RINT must retain the reference order.',
    full_domain='For angles outside the reference fast range, derive and validate a general Device reduction/function path equivalent to the scalar reference behavior; no Host/libm calls or stored generated results. Theta<1 can produce angles above the position bound; exceptional/subnormal/overflow cases need explicit treatment.',
    estimated_source_operation_cost=dict(current_trig_API_calls=34,modeled_true_fma_sites=13,
        nontrivial_fused_sites_after_fma_with_zero_as_mul=12,
        illustrative_unoptimized_software_fma_ops='~17 for split TwoProd + ~6 for TwoSum + ~2 for tail folding = ~25 basic FP32 operations, before correct-rounding guard/exception handling.',
        illustrative_total='~300 basic operations for 12 sites, plus ordinary multiply, masks/casts/selects and full-domain fallback; not a measured machine instruction count or timing forecast.',
        implication='A direct port can be much slower than V9. Mathematical/rounding proof and branch PMU are needed before spending an optimization or platform round.'),
    estimated_UB='A preliminary design needs roughly 8 FP32 temporary vectors per chunk in addition to live angle/results; liveness is not proven. D1024/H32 FP16 work region 90176B fits 8*2560*4=81920B for trig batch5, but H17 batch9 and DirectFloat output scratch cannot assume that capacity. Chunking or new liveness proof is mandatory; do not increase allocations blindly.',
    old_negative_difference='round8 cos_poly only replaced sqrt with a quarter-angle Taylor cosine and retained V9 double-angle structure; it failed 51/52 with half_overflow max4.0. The proposal instead studies reference reduction, direct quadrant selection and genuine rounding semantics. No old patch is rerun.',
    entry_gates=['Prove or reject software RN-FMA semantics before coding a production replacement; audit normal, subnormal, underflow, overflow, ties and cancellation.',
        'Validate the CPU model beyond this one trace without altering the golden; establish limits of reference/architecture compatibility.',
        'If later authorized, Device full precision/dispatch/large-amplitude/nonfinite/zero-identity/single-launch gates must pass before native paired timing.',
        'Reject if full-domain precision cannot be proven or modeled costs outweigh plausible family benefit. No performance claim follows from current CPU success.']),
 p1_after_coordinator_review=dict(state='not_started_no_new_PMU_in_this_extension',
    families=[dict(family='aligned FP32',entry='DirectFloatRotary',focus='queue-direct computation, output scratch liveness, broadcast/VEC operands; no nonexistent FP32 cast traffic'),
        dict(family='H1',entry='BatchedRotary / BulkPositionRotary',focus='trig/rotation separation, positions MTE/broadcast, casts and token-tail imbalance'),
        dict(family='nonaligned',entry='Rotary / PackedRotary / HeadTileRotary',focus='short DMA transactions, padding/Gather, coefficient copies, extra input-half cast, PIPE_ALL and tail cores')],
    metrics=['per-core min/max critical time and jobs/bytes','MTE2/MTE3 payload and instructions','VEC/UB read/write and effective masks','Cast/Gather/mask/barrier source or decoded instructions when supported','queue and scalar-vector wait dependencies'],
    assembly_limit='Device HiIPU decoder limitation is already recorded. Do not repeat failing disassembly or invent counts; host NumPy decoding here does not remove that limitation.',
    tiling='D1024/H32 FP16 tileHeads11,3groups,batch5,288 token visits vs256 remains a future model hypothesis; no tiling change is made.',
    negative_history=['benchmarks/experiments/round3/mask_trig.patch','benchmarks/experiments/round3/mask_all.patch','benchmarks/experiments/round8/cos_poly.patch','benchmarks/experiments/agentic/history.json']),
 uncertainties=['Only the frozen theta10000/H17/D1024 amplitude input was newly traced on Device; no global arithmetic-accuracy claim.',
    'The CPU oracle model is validated against the installed NumPy/ARM binary, not the inaccessible official backend version.',
    'Correctly rounded real trig still differs from the current FP32 reference near FP16 midpoints; universal acceptance is not established by a small absolute trig error bound.',
    'Device sqrt cause is identified as the measured Sqrt/vsqrt path, without decoded Device instructions; its vendor accuracy contract is not claimed violated.',
    'No Device RN-FMA primitive, full-domain scalar-reference equivalent or optimized scratch liveness has been implemented/proven.',
    'Instrumented stage timing cannot be used for performance attribution; no new native or replay timing is measured.'],
 task_evidence=dict(task_id=task_id,metadata=metadata,max_time_seconds=60,new_serial_single_card_diagnostic_tasks=1,
    device_launches=1,exit_code=0,lock_released=True,new_performance_measurements=0,new_platform_submissions=0,
    environment_changed=False,cpu_workload_reproduction=dict(workloads=33,profiles=4,byte_identical=True),
    operational_note='Initial CPU-only generated function signature had an extra closing parenthesis; fixed before the sole Device run. No runtime retry or performance trial.'),
 decision=dict(status='diagnosis_complete_no_ready',production_kernel_changed=False,reference_or_thresholds_changed=False,
    candidate_implemented=False,ready_published=False,
    reason='The first hardware arithmetic divergence is sqrt, but the dominant acceptance gap also reflects the FP32 algorithm/reference rounding path. Keep the source-matched 1.092x wide speedup (8.44% latency reduction) and all negatives; defer any production math or tiling change to coordinator review.'),
 reproduction=['python3 benchmarks/diagnostics/rope_v9_trig_internal/prepare.py',
    'source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh && cmake -S benchmarks/diagnostics/rope_v9_trig_internal -B build/rope_v9_trig_internal/probe_build -DROPE_DIAG_MATH_DIR="$PWD/build/rope_v9_trig_internal" && cmake --build build/rope_v9_trig_internal/probe_build -j4',
    'Only if a fresh trace is required: task-submit --device auto --timeout 0 --max-time 60 --run \'cd /data/pyptouser/songxiaoyou/cann_kernel/project && source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh && build/rope_v9_trig_internal/probe_build/trig_internal_probe build/rope_v9_system/input build/rope_v9_trig_internal/stages.bin build/rope_v9_trig_internal/probe_half.bin\'',
    'python3 benchmarks/diagnostics/rope_v9_trig_internal/analyze.py',
    'python3 benchmarks/diagnostics/rope_v9_trig_internal/high_precision.py',
    'python3 benchmarks/diagnostics/rope_v9_trig_internal/reference_runtime.py',
    'python3 benchmarks/diagnostics/rope_v9_trig_internal/finalize_report.py'],
 raw_artifacts='Preserved under ignored build/rope_v9_trig_internal; previous build/rope_v9_system remains untouched except read access.')
paths=[p for p in HERE.iterdir() if p.is_file() and p.name not in ['diagnosis.json']]
report['evidence_hashes']={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
(HERE/'diagnosis.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
history_path=ROOT/'benchmarks/experiments/agentic/history.json';history=json.loads(history_path.read_text())
entry=dict(diagnostic_id='rope_v9_trig_internal',update_id=schema['update_id'],state='diagnosis_complete_no_ready',
    source_sha256=schema['source_sha256'],report='benchmarks/diagnostics/rope_v9_trig_internal/diagnosis.json',
    first_device_arithmetic_divergence='Sqrt, stage24',new_npu_diagnostic_tasks=1,new_performance_measurements=0,ready_published=False,
    decision='Device sqrt differs by one ULP on 5224/59392 angles, but sqrt-only correction leaves 802/817 max-error failures. Local reference FMA/rounding model reproduces trig and outputs. General repair is a proposal only, pending proof/cost review.')
items=history.setdefault('diagnostics',[])
assert not any(v['diagnostic_id']==entry['diagnostic_id'] and v!=entry for v in items)
if not any(v['diagnostic_id']==entry['diagnostic_id'] for v in items):items.append(entry)
history_path.write_text(json.dumps(history,indent=2)+'\n')
print(json.dumps(dict(report=str(HERE/'diagnosis.json'),task_id=task_id,state=report['state'])))
