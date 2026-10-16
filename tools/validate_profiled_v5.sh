#!/usr/bin/env bash
# Each phase must be scheduled separately on one card, with a 60-second limit.
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
phase=correctness
label=profiled_v5
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --phase) phase="$2";shift 2;;
        --label) label="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
case "$phase" in
    correctness)
        python3 tools/suite.py --device "$device" --label "$label" --repeat 30 --batches 3
        python3 tools/suite.py --device "$device" --label "${label}_audit" --binary build/launch_audit/rope_runner --warmup 1 --repeat 5 --batches 1
        python3 tools/check_launch_profile.py --device "$device" --label "${label}_launches" --binary build/rope_runner
        ;;
    sweeps)
        python3 tools/suite.py --device "$device" --label "${label}_sweep" --binary build/launch_audit/rope_runner --sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/suite.py --device "$device" --label "${label}_packed_sweep" --binary build/launch_audit/rope_runner --packed-sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/suite.py --device "$device" --label "${label}_path_sweep" --binary build/launch_audit/rope_runner --path-sweep --warmup 1 --repeat 1 --batches 1
        ;;
    paired)
        python3 tools/paired_matrix.py --device "$device" --baseline build/rope_runner_platform_v4 --candidate build/rope_runner --label "${label}_paired"
        ;;
    extended)
        python3 tools/paired_matrix.py --device "$device" --baseline build/rope_runner_platform_v4 --candidate build/rope_runner --cases-file tests/round3_extended_cases.json --label "${label}_extended"
        ;;
    pmu)
        for case_name in deepseek_half unaligned_h128_d30_half sequence_d1024_float; do
            python3 tools/profile.py --device "$device" --binary build/rope_runner --cases-file tests/round3_performance_cases.json --case "$case_name" --label "${label}_${case_name}"
        done
        ;;
    *) echo 'Choose phase correctness, sweeps, paired, extended or pmu';exit 2;;
esac
