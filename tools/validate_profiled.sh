#!/usr/bin/env bash
# Run through task-submit with one device and a 60-second limit per phase.
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
phase=correctness
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --phase) phase="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
case "$phase" in
    correctness)
        python3 tools/suite.py --device "$device" --label profiled_v4 --repeat 30 --batches 3
        python3 tools/suite.py --device "$device" --label profiled_v4_audit --binary build/launch_audit/rope_runner --warmup 1 --repeat 5 --batches 1
        python3 tools/suite.py --device "$device" --label profiled_v4_sweep --binary build/launch_audit/rope_runner --sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/suite.py --device "$device" --label profiled_v4_packed_sweep --binary build/launch_audit/rope_runner --packed-sweep --warmup 1 --repeat 1 --batches 1
        python3 tools/check_launch_profile.py --device "$device" --label profiled_v4_launches --binary build/rope_runner
        ;;
    paired)
        python3 tools/paired_matrix.py --device "$device" --baseline build/rope_runner_platform_v1 --candidate build/rope_runner --label profiled_v4_paired
        ;;
    pmu)
        for case_name in deepseek_half prefill_h32_d30_float prefill_h32_d1024_half; do
            python3 tools/profile.py --device "$device" --binary build/rope_runner --cases-file tests/performance_cases.json --case "$case_name" --label "profiled_v4_${case_name}"
        done
        ;;
    *) echo "Choose phase correctness, paired or pmu";exit 2;;
esac
