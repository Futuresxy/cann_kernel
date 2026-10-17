"""Exhaust every normalized FP32 mantissa for the exact Q53 series pruning.

This is a CPU diagnostic of integer arithmetic, not the competition golden.
Exponent/sign restoration is unchanged in the device implementation.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def mul53(a, b):
    ah, al, bh, bl = a >> 27, a & 0x7ffffff, b >> 27, b & 0x7ffffff
    return (ah * bh << 1) + ((ah * bl + al * bh + ((al * bl) >> 27)) >> 26)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    total = mismatches = 0
    saved = {str(n): 0 for n in range(11)}
    for first in range(0, 1 << 23, 1 << 17):
        sig = np.arange(first, first + (1 << 17), dtype=np.uint64) + (1 << 23)
        sig = np.where(sig <= 11863283, sig << 1, sig)
        numerator = np.maximum(sig, 1 << 24) - np.minimum(sig, 1 << 24)
        denominator = sig + (1 << 24)
        wide = numerator << 38
        high, remainder = wide // denominator, wide % denominator
        z = (high << 15) + ((remainder << 15) // denominator)
        zz = mul53(z, z)
        old_term, old_sum = z.copy(), z.copy()
        new_term, new_sum = z.copy(), z.copy()
        active = np.ones(z.size, dtype=bool)
        steps = np.zeros(z.size, dtype=np.int32)
        for odd in range(3, 22, 2):
            old_term = mul53(old_term, zz)
            old_sum += old_term // odd
            active &= new_term >= odd
            new_term[active] = mul53(new_term[active], zz[active])
            new_sum[active] += new_term[active] // odd
            steps[active] += 1
        mismatches += int(np.count_nonzero(old_sum != new_sum))
        total += z.size
        for count, number in zip(*np.unique(steps, return_counts=True)):
            saved[str(10-int(count))] += int(number)
    report = dict(kind='exhaustive CPU fixed-point equivalence, not device golden',
                  normalized_fp32_mantissas=total, sum_mismatches=mismatches,
                  omitted_multiply_count_histogram=saved,
                  proof='zz<Q53; successive truncated nonnegative terms do not increase; '
                        'term<next_odd implies every subsequent integer quotient is zero')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    assert mismatches == 0


if __name__ == '__main__':
    main()
