#!/usr/bin/env bash
# Build both runners first; invoke this script only through task-submit.
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
label=single_launch_v3
launch_label=launch_count_v3
while (($#)); do
    case "$1" in
        --device) device="$2";shift 2;;
        --label) label="$2";shift 2;;
        --launch-label) launch_label="$2";shift 2;;
        *) echo "Unknown argument: $1";exit 2;;
    esac
done
python3 tools/suite.py --device "$device" --label "$label" --repeat 50 --batches 5
python3 tools/suite.py --device "$device" --label "${label}_audit" --binary build/launch_audit/rope_runner --warmup 1 --repeat 5 --batches 1
python3 tools/suite.py --device "$device" --label "${label}_sweep" --binary build/launch_audit/rope_runner --sweep --warmup 1 --repeat 1 --batches 1
python3 tools/check_launch_profile.py --device "$device" --label "$launch_label" --binary build/rope_runner
python3 tools/profile.py --device "$device" --label "$label" --binary build/rope_runner
