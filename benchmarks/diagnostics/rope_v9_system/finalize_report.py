"""Bind diagnostic evidence and record conclusions; never stages a candidate."""
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
import mpmath
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BUILD=ROOT/'build/rope_v9_system'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((HERE/'input_manifest.json').read_text())
stage=json.loads((HERE/'stage_report.json').read_text())
model=json.loads((HERE/'system_model.json').read_text())
assert sha(ROOT/'operators/rotary_pos_emb/kernel.asc')==manifest['source_sha256']
assert json.loads((HERE/'probe_identity.json').read_text())['bit_mismatches']==0
shutil.copyfile(BUILD/'task.log',HERE/'task.log')
log=(HERE/'task.log').read_text()
metadata=json.loads(next(line for line in log.splitlines() if line.startswith('{"device":')))
assert metadata['device_kernel_launches']==1
assert '已释放设备' in log and '任务完成 (exit=0)' in log
task_id=next(v for v in log.split() if v.startswith('task_'))
boundary=list(csv.DictReader((HERE/'fp16_boundary_failures.csv').open()))
spacing=Counter(r['adjacent_half_spacing'] for r in boundary)

previous=[
 dict(idea='Q53 log exact tail pruning',decision='rejected',why='Fixed-input native geomean 0.995493x, 26/33 slower; exact mathematics did not reduce end-to-end time.',evidence='benchmarks/experiments/agentic/20261017T032204914387Z-5917d3aaeb69.json'),
 dict(idea='True-FMA residual for TwoProd',decision='disproved on tested APIs/device',why='vmadd/vmla use separately rounded products for required probe operands; fma(a,b,-round(a*b)) cannot recover the product residual.',evidence='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/fma_semantics_v2.json'),
 dict(idea='Frequency compensated accumulation folding',decision='rejected',why='Pooled 1.00223x, interval crosses 1, small controls regress. Repaired liveness candidate independently tested; no safe performance result.',evidence='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/vector_accum_review.json'),
 dict(idea='Wide two-work-array operand placement',decision='preserve positive performance evidence, precision blocked',why='31.981 -> 29.2805us: speedup 1.09223x, latency reduction 8.44%. V9 and candidate fail identical inherited amplitude case with bit-identical output.',source_sha256='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556',evidence='benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/experiment.json'),
 dict(idea='Earlier cosine-polynomial substitution / low-precision rotation',decision='do not retry',why='Precision failures already recorded. Current work only diagnoses the existing trig error; it does not repeat either substitution.',evidence='docs/rollback_v4_round4.md; benchmarks/experiments/round6/manifest.json'),
 dict(idea='Other mask, Gather, bank padding, cache sizing, split-column and frequency prototypes',decision='preserved unchanged',why='All prior entries and original artifacts remain in the index; none are rerun in this diagnostic.',evidence='benchmarks/experiments/agentic/history.json')]
summary=dict(schema_version=1,diagnostic_id='rope_v9_system_inherited_fp16',state='diagnosis_complete_no_ready',
    source_sha256=manifest['source_sha256'],latest_direction='Algorithm/dataflow/profiling diagnosis first; no candidate development or publication.',
    official_baseline=dict(submission_id=879119,score=48.45,status='Pass',target_score=70,target_achieved=False),
    competition_kernel_changed=False,judge_reference_or_thresholds_changed=False,ready_published=False,new_platform_submissions=0,
    environment_changed=False,new_performance_measurements=0,new_npu_diagnostic_tasks=1,
    npu_task=dict(task_id=task_id,auto_assigned_one_card=True,max_time_seconds=60,serial=True,exit_code=0,lock_released=True,
        duration_note='Reservation ended normally. Diagnostic runtime is not used as operator performance evidence.'),
    diagnostic_binary_sha256=sha(BUILD/'probe_build/stage_probe'),diagnostic_runtime_metadata=metadata,
    library_versions=dict(numpy=np.__version__,mpmath=mpmath.__version__,mp_decimal_digits=80),
    calibration=dict(frozen_input=True,regenerated_input_sha_verified=True,
        math_helpers='Unmodified V9 math prefix extracted by source SHA; diagnostic-only instrumentation exports intermediates.',
        final_half_elements=2384896,final_half_bit_mismatches_to_saved_v9=0,
        position_zero_bit_mismatches=0,reference_reconstruction_verified_against_unchanged_suite=True),
    conclusions_zh=[
        '第一处分歧在 SinCosFp32：这份固定输入中，48核 inv_freq 全部一致，512列与当前FP32参考逐位一致；70144个angle也逐位一致。不能再把该失败归因于频率初始化。',
        '设备cos最大绝对误差5.364418e-7，sin为4.395843e-7（相对当前FP32参考）。使用设备sin/cos条件重算后，两个乘积、累加均逐位一致；有限值及Inf符号的最终转换一致。',
        'FP32旋转中间值最大差0.046875；817个有限FP16输出误差超过0.1，其中156个参考中间值恰在半精度中点。matched_ratio=0.9999874208仍不能抵消max_abs_error=32超限。',
        '例：参考FP32=-54960.00390625，设备=-54959.99609375，中点=-54960。仅0.0078125差异使FP16输出分别为-54976和-54944，差32。',
        '80位十进制数学参考表明，直接theta^(-i/W)与当前FP32 pow后倒数有141/512列相差1ULP。不可把数学更精确直接等同于更接近当前浮点参考。',
        'CPU诊断将sin/cos替换为同FP32角度的高精度正确舍入值后，仍有115个输出超过0.1；当前NumPy sin/cos自身与高精度结果最多差1ULP。此反事实只用于归因，未改golden或验收。官方参考的库舍入语义仍未知。',
        'V9与CPU按原SinCos源码顺序重放仍有3896个cos、4064个sin不同；范围缩减重放完全一致。差异在后续多项式、sqrt或倍角阶段内，当前尚未单独导出sqrt，不能断言全由sqrt引起。',
        '性能没有统一瓶颈：tiny标量/控制占比高；DeepSeek为VEC与MTE2混合；宽维FP16 VEC约86%；大流式MTE2约94%。标量占比不是已隔离的频率初始化耗时。',
        '保留宽维约1.092x的源绑定收益和全部负结果；其等价数据流改动没有修复也没有引入这份继承误差。当前不发布ready。'],
    precision_metrics={k:stage[k] for k in ['inv_freq_device_vs_current_fp32','angle_device_vs_current_fp32','cosine_device_vs_current_fp32','sine_device_vs_current_fp32','fp32_rotation_conditional_on_device_trig','fp32_rotation_vs_current_fp32','final_vs_current_reference','half_boundary_summary']},
    bad_half_step_histogram=dict(spacing),
    algorithm_and_branch_model='benchmarks/diagnostics/rope_v9_system/system_model.json',
    strategy_owner_document='docs/rope_optimization_strategy.md',strategy_document_modified_by_this_diagnostic=False,
    previous_attempts=previous,
    selected_next_experiment=dict(
        name='Quarter-angle sqrt and double-angle rounding attribution, diagnostic only',state='selected_not_started',
        evidence='Frequency/angle/reducer match; cosine/sine first diverge; CPU source replay differs from Device downstream of reduction. Direct high-precision trig still fails the strict FP16 output cap against current reference.',
        change='Only extend a development probe to export quarter-angle polynomial value, sqrt input/output, and each double-angle reconstruction intermediate. Keep production V9 and reference unchanged.',
        input_family='Frozen [1,137,17,1024] FP16 failing input and its existing hashes; use all active angle columns and recorded midpoint failures, without inferring hidden platform shapes.',
        compare='Stage-by-stage 80-digit oracle and separately-rounded FP32 source replay; correlate trig error with sqrt rounding and FP16 midpoint distances. Test conditional output rounding, not just mean trig error.',
        expected_information='Separate hardware sqrt rounding from polynomial evaluation and error amplification in reconstruction; determine whether a legal numerical change can satisfy the existing output contract before performance work.',
        difference_from_failed_trials='No cosine-polynomial replacement, frequency residual FMA, two-read rotation or threshold change. This measures the existing algorithm rather than retrying those ideas.',
        pass_or_stop='If no isolated stage explanation, retain inconclusive status. No ready until the original strict correctness suites pass; one-ULP trig improvement alone is not acceptance.',
        device_limit='If executed after review: existing serial task-submit, one auto-assigned card, max-time60, one diagnostic kernel. No performance claims from instrumentation.'),
    missing_evidence=[
        'Installed tools do not decode HiIPU machine instructions, so precise dynamic instruction/port/bank cause is unavailable.',
        'No separate timing isolates V9 frequency vs trigonometry; whole-kernel PMU cannot supply that decomposition.',
        'FP32, H1 and unaligned paths have source/capacity models but lack equally complete source-bound representative PMU coverage.',
        'Official hidden golden implementation and dtype/shape mapping remain unknown; no hidden-case inference is used.',
        'Subnormal/extreme theta and angles beyond the stated position bound need a separate numerical-domain audit before any global trig replacement.'
    ],
    reproduction=dict(prerequisites='Existing server CANN9.0/toolchain, NumPy/mpmath and preserved build artifacts; no installation.',
        prepare='python3 benchmarks/diagnostics/rope_v9_system/prepare.py',
        configure='source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh && cmake -S benchmarks/diagnostics/rope_v9_system -B build/rope_v9_system/probe_build -DROPE_DIAG_MATH_DIR="$PWD/build/rope_v9_system"',
        compile='cmake --build build/rope_v9_system/probe_build -j4',
        diagnostic='task-submit --device auto --timeout 0 --max-time 60 --run \'cd /data/pyptouser/songxiaoyou/cann_kernel/project && source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh && build/rope_v9_system/probe_build/stage_probe build/rope_v9_system/input build/rope_v9_system/stages.bin build/rope_v9_system/probe_half.bin\'',
        analyze='python3 benchmarks/diagnostics/rope_v9_system/analyze_stages.py',
        model='python3 benchmarks/diagnostics/rope_v9_system/cost_model.py',
        archive='python3 benchmarks/diagnostics/rope_v9_system/finalize_report.py',
        large_files='Frozen input, raw stage exports, saved baseline and binaries stay under ignored build/rope_v9_system. Hashes and seed are versioned; original artifacts remain preserved.'),
    evidence_hashes={str(p.relative_to(ROOT)):sha(p) for p in [HERE/'stage_probe.asc',HERE/'prepare.py',HERE/'analyze_stages.py',HERE/'cost_model.py',HERE/'finalize_report.py',HERE/'CMakeLists.txt',HERE/'input_manifest.json',HERE/'probe_identity.json',HERE/'stage_report.json',HERE/'system_model.json',HERE/'fp16_boundary_failures.csv',HERE/'task.log']})
(HERE/'diagnosis.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
history_path=ROOT/'benchmarks/experiments/agentic/history.json'
history=json.loads(history_path.read_text())
items=history.setdefault('diagnostics',[])
entry=dict(diagnostic_id=summary['diagnostic_id'],state=summary['state'],source_sha256=summary['source_sha256'],
    report='benchmarks/diagnostics/rope_v9_system/diagnosis.json',first_divergent_stage='SinCosFp32',
    new_npu_diagnostic_tasks=1,new_performance_measurements=0,ready_published=False,
    decision='Preserve wide performance evidence and all negatives; fixed large-amplitude failure localized to trig plus FP16 midpoint crossings. No production kernel or precision rules changed.')
assert not any(v['diagnostic_id']==entry['diagnostic_id'] and v!=entry for v in items)
if not any(v['diagnostic_id']==entry['diagnostic_id'] for v in items):items.append(entry)
history_path.write_text(json.dumps(history,indent=2)+'\n')
print(json.dumps(dict(report=str(HERE/'diagnosis.json'),task_id=task_id,state=summary['state']),ensure_ascii=False))
