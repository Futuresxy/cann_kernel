#!/usr/bin/env bash
# Run each device phase in a separate, bounded, single-card task-submit job.
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
phase=correctness
label=round4_replay
binary=build/replayed_experiments/round4/precision_safe_tiled/build/rope_runner
baseline=build/rope_runner
audit_binary=
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --phase) phase="$2";shift 2;;
        --label) label="$2";shift 2;;
        --binary) binary="$2";shift 2;;
        --baseline) baseline="$2";shift 2;;
        --audit-binary) audit_binary="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
if [[ -z "$audit_binary" ]]; then audit_binary="${binary%/build/rope_runner}/audit/rope_runner"; fi
case "$phase" in
    prepare)
        # CPU only. This phase does not need a task-submit device reservation.
        python3 tools/compare_v4_outputs.py --candidate "$binary" --cases-file tests/round4_precision_cases.json --label "${label}_bits" --generate-only
        python3 tools/suite.py --cases-file tests/round3_performance_cases.json --generate-only
        ;;
    precision)
        python3 tools/compare_v4_outputs.py --device "$device" --baseline "$baseline" --candidate "$binary" --cases-file tests/round4_precision_cases.json --label "${label}_bits"
        ;;
    correctness)
        python3 tools/suite.py --device "$device" --binary "$binary" --label "$label" --warmup 1 --repeat 3 --batches 1
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_audit" --warmup 1 --repeat 1 --batches 1
        python3 tools/check_launch_profile.py --device "$device" --binary "$binary" --label "${label}_launches"
        ;;
    paths)
        python3 tools/suite.py --device "$device" --binary "$audit_binary" --label "${label}_paths" --path-sweep --warmup 1 --repeat 1 --batches 1
        ;;
    paired|extended)
        cases=tests/performance_cases.json
        if [[ "$phase" == extended ]]; then cases=tests/round3_extended_cases.json; fi
        python3 tools/paired_matrix.py --device "$device" --baseline "$baseline" --candidate "$binary" --cases-file "$cases" --label "${label}_${phase}"
        ;;
    pmu)
        for variant in baseline candidate; do
            measured_binary="$baseline"
            if [[ "$variant" == candidate ]]; then measured_binary="$binary"; fi
            for case_name in unaligned_h128_d30_half sequence_d1024_float; do
                python3 tools/profile.py --device "$device" --binary "$measured_binary" --cases-file tests/round3_extended_cases.json --case "$case_name" --label "${label}_${variant}_${case_name}"
            done
        done
        ;;
    *) echo 'Choose prepare, precision, correctness, paths, paired, extended or pmu';exit 2;;
esac
