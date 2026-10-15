#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S . -B build/launch_audit -DNPU_ARCH="${NPU_ARCH:-dav-2201}" -DROPE_LAUNCH_AUDIT=ON
cmake --build build/launch_audit -j4
python3 tools/stamp_build.py --binary build/launch_audit/rope_runner
