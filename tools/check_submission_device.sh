#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
device=0
while (($#)); do
    case "$1" in --device) device="$2";shift 2;; *) echo 'unknown option';exit 2;; esac
done
export TASK_DEVICE="$device"
cd build/submission_check/build
timeout 30 ./rotary_pos_emb_custom
python3 ../scripts/verify_result.py 0
