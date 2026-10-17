#!/usr/bin/env python3
"""Read-only CPU cross-check of the V9 stage probe; never changes a golden.

Run with the existing server Python/NumPy after the independent stage probe.
FP64 trig below is a diagnostic comparator, not an alternative acceptance oracle.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

V9 = '5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_differences(a, b, integer_type, mask=None):
    aa, bb = a.view(integer_type), b.view(integer_type)
    if mask is not None:
        aa, bb = aa[mask], bb[mask]
    return int(np.count_nonzero(aa != bb))


def analyze(directory, manifest_path, cores):
    manifest = json.loads(manifest_path.read_text())
    assert manifest['source_sha256'] == V9
    assert manifest['dtype'] == 'float16'
    assert sha(directory / 'v9_math_snapshot.h') == manifest['math_snapshot_sha256']
    for name in ('x.bin', 'positions.bin'):
        assert sha(directory / 'input' / name) == manifest['input_sha256'][name]
    baseline_path = directory / 'v9_baseline_half.bin'
    assert sha(baseline_path) == manifest['baseline_output_sha256']
    assert sha(directory / 'probe_half.bin') == manifest['baseline_output_sha256']
    b, s, h, d = manifest['shape']
    tokens, k = b * s, d // 2
    x = np.fromfile(directory / 'input/x.bin', np.float16).reshape(tokens, h, d)
    p = np.fromfile(directory / 'input/positions.bin', np.int32)
    baseline = np.fromfile(baseline_path, np.float16).reshape(x.shape)
    raw = np.fromfile(directory / 'stages.bin', np.float32)
    assert raw.size == cores * k + 5 * tokens * k + 3 * x.size
    frequency = raw[:cores * k].reshape(cores, k)
    offset, n = cores * k, tokens * k
    angle, reduced, quotient, c, sin = [raw[offset+i*n:offset+(i+1)*n].reshape(tokens, k) for i in range(5)]
    offset += 5 * n
    rotation = raw[offset+2*x.size:offset+3*x.size].reshape(x.shape)
    gf = np.float32(1) / np.power(np.float32(manifest['theta']),
                                 np.arange(0, d, 2, dtype=np.float32) / np.float32(d))
    ga = p.astype(np.float32)[:, None] * gf
    gc, gs = np.cos(ga), np.sin(ga)
    active = p != 0
    trig = {}
    for name, actual, expected in [('cos', c, gc), ('sin', sin, gs)]:
        aa, bb = actual[active], expected[active]
        trig[name] = {'different_bits': bit_differences(aa, bb, np.uint32),
                      'elements': int(aa.size), 'max_abs_error': float(np.max(np.abs(aa-bb)))}
    a, b = x[:, :, :k].astype(np.float32), x[:, :, k:].astype(np.float32)

    def rotate(cc, ss):
        with np.errstate(invalid='ignore', over='ignore'):
            result = np.concatenate((a*cc[:, None, :]-b*ss[:, None, :],
                                     b*cc[:, None, :]+a*ss[:, None, :]), axis=-1)
        result[p == 0] = x[p == 0]
        return result

    def compare_half(actual, expected):
        with np.errstate(invalid='ignore', over='ignore'):
            diff = np.abs(actual.astype(np.float32)-expected.astype(np.float32))
        finite = np.isfinite(diff)
        return {'finite_elements_above_0_1': int(np.count_nonzero(diff[finite] > .1)),
                'max_abs_difference': float(diff[finite].max())}

    with np.errstate(invalid='ignore', over='ignore'):
        reconstructed = rotate(c, sin)
        reconstructed_half = reconstructed.astype(np.float16)
        original_reference = rotate(gc, gs).astype(np.float16)
        high_trig_c = np.cos(ga.astype(np.float64)).astype(np.float32)
        high_trig_s = np.sin(ga.astype(np.float64)).astype(np.float32)
        alternate_diagnostic = rotate(high_trig_c, high_trig_s).astype(np.float16)
    finite32 = np.isfinite(rotation) & np.isfinite(reconstructed)
    finite16 = np.isfinite(baseline) & np.isfinite(reconstructed_half)
    return {
        'diagnostic_only': True, 'acceptance_golden_or_thresholds_changed': False,
        'source_sha256': V9, 'numpy_version': np.__version__, 'shape': manifest['shape'],
        'input_sha256': manifest['input_sha256'],
        'stages_sha256': sha(directory / 'stages.bin'),
        'probe_and_baseline_output_sha256': sha(baseline_path),
        'frequency_different_bits_per_core': [bit_differences(f, gf, np.uint32) for f in frequency],
        'angle_different_bits': bit_differences(angle, ga, np.uint32),
        'trig_vs_original_fp32_reference': trig,
        'finite_fp32_rotation_different_bits_using_device_trig': bit_differences(rotation, reconstructed, np.uint32, finite32),
        'finite_fp16_output_different_bits_using_device_trig': bit_differences(baseline, reconstructed_half, np.uint16, finite16),
        'baseline_vs_original_fp32_reference': compare_half(baseline, original_reference),
        'range_reduction_max_abs_error_vs_fp64_subtraction': float(np.max(np.abs(
            reduced.astype(np.float64)-(angle.astype(np.float64)-quotient.astype(np.float64)*(2*np.pi))))),
        'reference_sensitivity': {
            'comparison': 'Same FP32 angle and separate FP32 rotation; replace only trig with FP64 trig rounded to FP32 for diagnosis',
            'cos_different_bits': bit_differences(gc, high_trig_c, np.uint32),
            'sin_different_bits': bit_differences(gs, high_trig_s, np.uint32),
            'fp16_outputs': compare_half(alternate_diagnostic, original_reference),
            'interpretation': 'A more accurate trig approximation need not reproduce the current FP32 library oracle. '
                              'This is not evidence about the unknown platform golden or permission to alter acceptance.',
        },
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--cores', type=int, default=48)
    args = parser.parse_args()
    print(json.dumps(analyze(args.data_dir, args.manifest, args.cores), indent=2))
