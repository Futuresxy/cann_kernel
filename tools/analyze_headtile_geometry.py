#!/usr/bin/env python3
"""Check a proposed RoPE layout on CPU; no tensor data or NPU execution.

This proves index/period identities only, not floating-point equivalence,
installed Copy API support, UB allocation safety, or a performance gain.
"""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc'


def examine(dim, heads):
    half = dim // 2
    pitch = (half + 15) // 16 * 16
    tile = min(128, heads, 2048 // pitch)
    period = 8 // math.gcd(dim, 8)
    prefix = period * dim
    assert prefix % 8 == 0 and period <= 4
    groups = []
    for start in range(0, heads, tile):
        rows = min(tile, heads - start)
        count = rows * dim
        aligned = (count + 7) // 8 * 8
        assert aligned <= 2 * tile * pitch
        prefix_used = min(prefix, aligned)
        for flat in range(count):
            col = flat % dim
            prefix_col = (flat % prefix) % dim
            # Repeated prefix must preserve coefficient index and sine sign.
            assert col % half == prefix_col % half
            assert (col < half) == (prefix_col < half)
            rotated = flat - col + (col + half if col < half else col - half)
            assert 0 <= rotated < count
            # Rotation is a bijective involution inside each head.
            rcol = rotated % dim
            back = rotated - rcol + (rcol + half if rcol < half else rcol - half)
            assert back == flat
        pairs = rows * pitch
        groups.append(dict(
            rows=rows, logical_output_elements=count, padded_output_elements=aligned,
            old_gather_elements=4 * pairs + aligned,
            proposal_short_tail_gather_elements=aligned + 2 * prefix_used,
            implemented_full_prefix_gather_elements=aligned + 2 * prefix,
            regular_copy_elements=2 * (aligned - prefix_used),
        ))
    return dict(dim=dim, heads=heads, pitch=pitch, tile_heads=tile,
                period_heads=period, prefix_elements=prefix, groups=groups)


def main():
    shapes = groups = elements = 0
    for dim in range(16, 65, 2):
        if dim % 16 == 0:
            continue
        for heads in range(33, 257):
            case = examine(dim, heads)
            shapes += 1
            groups += len(case['groups'])
            elements += sum(g['logical_output_elements'] for g in case['groups'])
    result = dict(
        schema_version=1, task_id='20261017-headtile-attribution',
        state='geometry_model_only_not_implemented',
        implementation_comparison=dict(
            source_sha256='8d91182ab86ed3937f8127f3d427bb0777bbf94cffff83977b1bab580428eaea',
            note='R6 always gathers the full prefix, including tiny tail groups. The smaller short-tail prefix is an unimplemented proposal, not a measured candidate feature.',
        ),
        baseline_source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        method='Exhaustive public HeadTile D/H domain; every head group and valid flat element',
        checked_shapes=shapes, checked_groups=groups, checked_valid_elements=elements,
        invariants=['32-byte aligned FP32 coefficient prefix',
                    'coefficient index and sine sign preserved by prefix repetition',
                    'rotate-half permutation stays within valid input and is an involution',
                    'rounded output count fits existing two-capacity storage'],
        examples=[examine(d, h) for d, h in [(30, 128), (30, 129), (24, 65), (62, 255)]],
        limitations=[
            'Logical element counts are not cycles, DRAM traffic or measured UB transactions.',
            'Regular Copy API repeat/stride/mask support must be checked in installed dav-2201 headers.',
            'Padding needs explicit safe indices and masks; only valid elements are checked here.',
            'Does not prove FP32 sign/rounding, NaN/Inf classes, position0 identity, UB lifetimes or DMA correctness.',
            'A CPU diagnostic, never submitted or included as a judge dependency.',
        ],
    )
    target = ROOT / 'benchmarks/analysis/headtile_geometry_model.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Checked {shapes} shapes, {groups} groups, {elements} valid element mappings')


if __name__ == '__main__':
    main()
