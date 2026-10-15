#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S . -B build -DNPU_ARCH="${NPU_ARCH:-dav-2201}"
cmake --build build -j4
