#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
repo_root="$(pwd)"
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
if [[ "${TASK_DEVICE:-0}" != 0 ]]; then
    echo 'The unmodified template selects device 0; reserve exactly device 0.'
    exit 2
fi
cd build/kernel_only_validation
if ! bash run.sh > "$repo_root/build/kernel_only_template_run.log" 2>&1; then
    tail -n 60 "$repo_root/build/kernel_only_template_run.log"
    exit 1
fi
tail -n 4 "$repo_root/build/kernel_only_template_run.log"
cd "$repo_root"
python3 tools/suite.py --device 0 --label kernel_only --binary build/rope_runner_kernel_only --repeat 50 --batches 5
python3 tools/suite.py --device 0 --label kernel_only_sweep --binary build/rope_runner_kernel_only --sweep --warmup 1 --repeat 1 --batches 1
python3 tools/profile.py --device 0 --label kernel_only --binary build/rope_runner_kernel_only
