#!/usr/bin/env bash
# CPU preparation is separate. Submit each device phase serially through
# task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/validate_profiled_v9.sh --phase ...'
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
phase=correctness
label=profiled_v9
binary=build/rope_runner
audit_binary=build/launch_audit/rope_runner
forward_binary=build/tuning_round8/final_forward/rope_paired_runner
reverse_binary=build/tuning_round8/final_reverse/rope_paired_runner
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --phase) phase="$2";shift 2;;
        --label) label="$2";shift 2;;
        --binary) binary="$2";shift 2;;
        --audit-binary) audit_binary="$2";shift 2;;
        --forward-binary) forward_binary="$2";shift 2;;
        --reverse-binary) reverse_binary="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
case "$phase" in
    prepare)
        python3 tools/compare_v4_outputs.py --candidate "$binary" --cases-file tests/round4_precision_cases.json --label "${label}_bits" --generate-only
        python3 tools/compare_v4_outputs.py --candidate "$binary" --cases-file tests/round5_precision_cases.json --label "${label}_extended_bits" --generate-only
        python3 tools/suite.py --cases-file tests/round6_performance_cases.json --generate-only
        ;;
    correctness)
        python3 tools/suite.py --device "$device" --binary "$binary" --label "$label" --warmup 3 --repeat 5 --batches 1
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_audit" --warmup 1 --repeat 2 --batches 1
        python3 tools/check_launch_profile.py --device "$device" --binary "$binary" --label "${label}_launches"
        ;;
    math)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_math" --cases-file tests/round6_math_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    sweep|packed_sweep|path_sweep)
        flag="--${phase//_/-}"
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_${phase}" "$flag" --warmup 1 --repeat 1 --batches 1
        ;;
    new_math)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_new_math" --cases-file tests/round8_precision_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    dispatch)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_dispatch" --cases-file tests/round8_dispatch_precision_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    small)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_small" --cases-file tests/round7_small_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    aligned_audit)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_aligned_audit" --cases-file tests/round5_precision_cases.json --warmup 1 --repeat 1 --batches 1
        ;;
    precision)
        python3 tools/compare_v4_outputs.py --device "$device" --baseline build/rope_runner_platform_v4 --candidate "$binary" --cases-file tests/round4_precision_cases.json --label "${label}_bits"
        python3 tools/compare_v4_outputs.py --device "$device" --baseline build/rope_runner_platform_v4 --candidate "$binary" --cases-file tests/round5_precision_cases.json --label "${label}_extended_bits"
        ;;
    shared)
        python3 tools/profile_balanced.py --device "$device" --forward-binary "$forward_binary" --reverse-binary "$reverse_binary" --cases-file tests/round6_performance_cases.json --label "${label}_balanced"
        ;;
    pmu)
        for case_name in tiny prefill_h32_d1024_half; do
            python3 tools/profile.py --device "$device" --binary "$binary" --cases-file tests/round6_performance_cases.json --case "$case_name" --label "${label}_${case_name}"
        done
        ;;
    *) echo 'Choose prepare, correctness, math, new_math, dispatch, sweep, packed_sweep, path_sweep, small, aligned_audit, precision, shared or pmu';exit 2;;
esac
