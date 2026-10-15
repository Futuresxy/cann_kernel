#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
# The original, unmodified main.asc selects device 0. Reserve precisely that
# one device with task-submit --device 0; do not change the competition harness.
if [[ "${TASK_DEVICE:-0}" != 0 ]]; then
    echo 'Original template uses device 0; submit this check with task-submit --device 0.'
    exit 2
fi
cd build/template_only_submission_check/build
timeout 30 ./rotary_pos_emb_custom
python3 ../scripts/verify_result.py 0
