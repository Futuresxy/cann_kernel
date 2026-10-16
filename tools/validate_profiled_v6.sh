#!/usr/bin/env bash
# Submit device phases separately, serially, on one card with a 60 s limit.
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
phase=correctness
label=profiled_v6
baseline=build/rope_runner_platform_v4
forward_binary=build/profiled_v6/forward/rope_paired_runner
reverse_binary=build/profiled_v6/reverse/rope_paired_runner
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --phase) phase="$2";shift 2;;
        --label) label="$2";shift 2;;
        --baseline) baseline="$2";shift 2;;
        --forward-binary) forward_binary="$2";shift 2;;
        --reverse-binary) reverse_binary="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
case "$phase" in
    prepare)
        # CPU only; no task-submit card needed.
        python3 tools/compare_v4_outputs.py --candidate build/rope_runner --cases-file tests/round4_precision_cases.json --label "${label}_bits" --generate-only
        python3 tools/compare_v4_outputs.py --candidate build/rope_runner --cases-file tests/round5_precision_cases.json --label "${label}_extended_bits" --generate-only
        python3 tools/suite.py --cases-file tests/round3_performance_cases.json --generate-only
        ;;
    precision)
        python3 tools/compare_v4_outputs.py --device "$device" --baseline "$baseline" --candidate build/rope_runner --cases-file tests/round4_precision_cases.json --label "${label}_bits"
        python3 tools/compare_v4_outputs.py --device "$device" --baseline "$baseline" --candidate build/rope_runner --cases-file tests/round5_precision_cases.json --label "${label}_extended_bits"
        ;;
    correctness)
        python3 tools/suite.py --device "$device" --label "$label" --repeat 30 --batches 3
        python3 tools/suite.py --device "$device" --label "${label}_audit" --binary build/launch_audit/rope_runner --warmup 1 --repeat 5 --batches 1
        python3 tools/check_launch_profile.py --device "$device" --label "${label}_launches"
        ;;
    sweeps)
        python3 tools/suite.py --device "$device" --binary build/launch_audit/rope_runner --label "${label}_sweep" --sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/suite.py --device "$device" --binary build/launch_audit/rope_runner --label "${label}_packed_sweep" --packed-sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/suite.py --device "$device" --binary build/launch_audit/rope_runner --label "${label}_path_sweep" --path-sweep --warmup 1 --repeat 1 --batches 1
        ;;
    aligned_audit)
        # Cover the new FP32 direct-wide kernel, absent from the older matrix.
        python3 tools/suite.py --device "$device" --binary build/launch_audit/rope_runner --label "${label}_aligned_audit" --cases-file tests/round5_precision_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    shared)
        python3 tools/profile_balanced.py --device "$device" --forward-binary "$forward_binary" --reverse-binary "$reverse_binary" --label "${label}_balanced"
        ;;
    paired)
        python3 tools/paired_matrix.py --device "$device" --baseline "$baseline" --candidate build/rope_runner --label "${label}_paired"
        ;;
    pmu_aligned|pmu_dma)
        cases=(deepseek_float sequence8192)
        if [[ "$phase" == pmu_dma ]]; then cases=(unaligned_h128_d30_half sequence_d1024_float); fi
        for variant in baseline candidate; do
            binary="$baseline"
            if [[ "$variant" == candidate ]]; then binary=build/rope_runner; fi
            for case_name in "${cases[@]}"; do
                python3 tools/profile.py --device "$device" --binary "$binary" --cases-file tests/round3_performance_cases.json --case "$case_name" --label "${label}_${variant}_${case_name}"
            done
        done
        ;;
    *) echo 'Choose prepare, precision, correctness, sweeps, aligned_audit, shared, paired, pmu_aligned or pmu_dma';exit 2;;
esac
