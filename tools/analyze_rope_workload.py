#!/usr/bin/env python3
"""CPU-only RoPE lower bounds and source-bound V9 profiling inventory.

No device operations, timing changes, input generation or submission. The
arithmetic model excludes frequency/trig instructions and physical cache traffic.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V9 = '5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc'


def read(relative):
    return json.loads((ROOT / relative).read_text())


def workload(case):
    b, s, h, d = case['shape']
    element_bytes = {'float16': 2, 'float32': 4}[case['dtype']]
    n, k = b * s, d // 2
    return {
        'name': case['name'], 'shape': case['shape'], 'dtype': case['dtype'],
        'tokens': n, 'frequency_elements_ideal': k,
        'angle_pairs_ideal': n * k, 'rotation_pairs': n * h * k,
        'head_reuse_factor': h,
        'rotation_flops': 6 * n * h * k,
        'x_read_y_write_bytes_min': 2 * n * h * d * element_bytes,
        'positions_read_bytes_min': 4 * n,
        'rotation_flops_per_x_y_byte': 3 / (2 * element_bytes),
    }


def wide_fp16_layout():
    # Source: V9 run_kernel and LargeAlignedRotary::Init/Process. One worked
    # example, not a dispatch implementation or a suggested tile sweep.
    n, h, d, available = 256, 32, 1024, 48
    initial_heads = min(12288 // d, h, 192)
    groups = math.ceil(h / initial_heads)
    tile_heads = math.ceil(h / groups)
    size, freq_size = tile_heads * d, d // 2
    base = 3 * size * 2 + 2 * (size + 8) * 4
    cap = (188 * 1024 - base - freq_size * 4) // (3 * freq_size * 4)
    batch = max(1, min(size // freq_size, 16, cap))
    jobs, blocks = n * groups, min(n * groups, available)
    visits = []
    for block in range(blocks):
        begin, end = jobs * block // blocks, jobs * (block + 1) // blocks
        # All-nonzero-position structural upper bound: a token crossed by a
        # partition boundary is recomputed on both cores; within-core reused.
        visits.append((end - 1) // groups - begin // groups + 1)
    return {
        'case': 'prefill_h32_d1024_half', 'shape': [1, n, h, d],
        'tile_heads': tile_heads, 'head_groups': groups, 'jobs': jobs,
        'blocks': blocks, 'frequency_elements_generated_across_cores': blocks * freq_size,
        'work_size_elements': size, 'work_stride_elements': size + 8,
        'io_and_work_bytes': base, 'trig_batch_tokens': batch,
        'frequency_and_trig_bytes': (1 + 3 * batch) * freq_size * 4,
        'subtotal_ub_bytes_excluding_frequency_math_and_allocator': base + (1 + 3 * batch) * freq_size * 4,
        'nonzero_token_visits_across_cores': sum(visits),
        'ideal_token_visits': n,
        'token_visits_per_core': sorted(set(visits)),
        'note': 'Structural model; position-zero branches can avoid trig work. '
                'Cache capacity, per-core boundary overlap, scratch and queues '
                'must be considered together; these counts are not cycle estimates.',
    }


def unaligned_layout(dtype, d):
    """Worked Rotary-only model; excludes zero-position identity bypasses."""
    n, h, blocks = 1024, 64, 48
    k, e = d // 2, {'float16': 2, 'float32': 4}[dtype]
    pitch = math.ceil(k / 16) * 16
    tile = min(4096 // pitch, 32, h)
    groups = math.ceil(h / tile)
    jobs, capacity = n * groups, tile * pitch
    visits = sum(((jobs * (i+1) // blocks - 1) // groups -
                  (jobs * i // blocks) // groups + 1) for i in range(blocks))
    coefficient_copies = 2 * (tile - 1) * visits
    old_ub = (4 * e + 20) * capacity + 4 * pitch
    new_ub = (4 * e + 20) * capacity + 16 * pitch
    return {
        'shape': [2, 512, h, d], 'dtype': dtype, 'pitch': pitch,
        'tile_heads': tile, 'groups': groups, 'jobs': jobs,
        'all_nonzero_token_visits_across_cores': visits,
        'existing_ub_bytes': old_ub, 'proposed_ub_bytes': new_ub,
        'proposed_additional_ub_bytes': new_ub - old_ub,
        'coefficient_copy_calls_removed': coefficient_copies,
        'coefficient_copy_operand_bytes_removed': coefficient_copies * pitch * 8,
        'repeated_half_load_calls_removed': jobs,
        'repeated_half_load_operand_bytes_removed': n * h * pitch * (e + 4),
        'existing_arithmetic_api_calls_per_job': 6,
        'proposed_arithmetic_api_calls_per_job': 6 * math.ceil(k / 64),
        'minimum_x_y_gm_bytes_unchanged': 2 * n * h * d * e,
        'assumptions': 'Keep both input halves, two result vectors and a temporary '
                       'within the existing five capacity-sized FP32 work vectors. '
                       'Add separate pitch-sized frequency/angle/cos/sin storage. '
                       'Preserve four Mul plus Sub/Add, queue depths and DMA policy. '
                       'This is a source-operand/count model, not physical traffic or timing.',
        'scope': 'Public representative of the existing generic unaligned Rotary '
                 'dispatch only; not a hidden-case mapping. Same Rotary source '
                 'in V9 and the platform-accepted 817f8364 wide-only patch.',
    }


def report():
    source = ROOT / 'operators/rotary_pos_emb/kernel.asc'
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != V9:
        raise ValueError('This inventory is bound to V9; review the layout model for a new source')
    text = source.read_text()
    trig = text[text.index('__aicore__ inline void SinCosFp32'):
                text.index('__aicore__ inline void ScalarFrequencyRange')]
    trig_calls = {name: len(re.findall(r'\b' + name + r'\(', trig))
                  for name in ('Muls', 'Mul', 'Adds', 'Sub', 'Cast', 'Sqrt')}
    performance = read('benchmarks/results/profiled_v9_balanced.json')
    cases = [workload(c) for c in performance['cases']]
    for row, case in zip(cases, performance['cases']):
        latency = case['candidate_us']
        row['local_native_us'] = latency
        row['effective_x_y_GB_s'] = row['x_read_y_write_bytes_min'] / latency / 1000
        row['timing_source'] = 'benchmarks/results/profiled_v9_balanced.json'
    profiles = []
    for family in ('tiny', 'deepseek', 'wide', 'stream'):
        relative = f'benchmarks/profiles/agentic_r1_v9_{family}'
        meta, metrics = read(relative + '/metadata.json'), read(relative + '/summary.json')
        if meta['source_sha256'] != V9:
            raise ValueError('Profile source mismatch: ' + relative)
        profiles.append({'family': family, 'case': meta['case'], 'path': relative,
                         'source_sha256': meta['source_sha256'],
                         'binary_sha256': meta['binary_sha256'], 'replay_diagnostic_only': True,
                         'metrics': metrics})
    feedback = read('platform_results/rotary_pos_emb/20261017T032204914387Z-5917d3aaeb69.json')
    opportunity = []
    for c in feedback['cases']:
        ratio = c['latency_us'] / c['best_latency_us']
        point = 100 / (1 + math.log(ratio, 1.5))
        opportunity.append({'id': c['id'], 'latency_us': c['latency_us'],
                            'best_us': c['best_latency_us'], 'ratio_to_best': ratio,
                            'estimated_point_score': point,
                            'mean_score_gain_if_reaches_best': (100 - point) / 15})
    return {
        'schema_version': 1, 'source_sha256': V9,
        'scope': 'Public local workloads only; no mapping to hidden platform shapes',
        'definitions': {'N': 'B*S', 'K': 'D/2',
                        'rotation': '6 FLOPs per pair; frequency/trig cost excluded',
                        'traffic': 'Logical compulsory X read + Y write; positions listed separately; '
                                   'not a measured DRAM bandwidth or a hardware peak'},
        'workloads': cases, 'wide_fp16_worked_layout': wide_fp16_layout(),
        'generic_unaligned_worked_layouts': [unaligned_layout('float16', 126),
                                             unaligned_layout('float32', 254)],
        'sincos_static_source_api_calls': trig_calls,
        'sincos_static_source_api_calls_note': 'Source calls only, not dynamic instructions or cycles; '
                                              'each API may emit multiple instructions/repeats.',
        'profiles': profiles,
        'official_submission_id': feedback['submission_id'],
        'official_score': float(feedback['platform_score_raw']),
        'platform_opportunities': sorted(opportunity, key=lambda c: c['mean_score_gain_if_reaches_best'], reverse=True),
        'score_note': 'Point estimates use rounded page timings. Only the platform supplies the official score.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/analysis/v9_workload_model.json')
    args = parser.parse_args()
    data = report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(f"Wrote {len(data['workloads'])} workloads and {len(data['profiles'])} source-bound profiles to {args.output}")


if __name__ == '__main__':
    main()
