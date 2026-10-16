#!/usr/bin/env bash
# CPU-only build. Does not modify either source or reserve an NPU.
set -eo pipefail
cd "$(dirname "$0")/.."
baseline_dir="$(realpath "${1:?usage: build_paired.sh BASELINE_DIR CANDIDATE_DIR BUILD_DIR}")"
candidate_dir="$(realpath "${2:?candidate directory}")"
pair_build_dir="$(realpath -m "${3:?build directory}")"
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S . -B "$pair_build_dir" -DROPE_KERNEL_DIR="$candidate_dir" \
    -DROPE_BASELINE_DIR="$baseline_dir" -DROPE_PAIRED_PROFILE=ON \
    -DCMAKE_BUILD_TYPE=Release -DNPU_ARCH="${NPU_ARCH:-dav-2201}"
cmake --build "$pair_build_dir" --target rope_paired_runner -j4
python3 tools/stamp_paired.py --baseline "$baseline_dir/kernel.asc" \
    --candidate "$candidate_dir/kernel.asc" --binary "$pair_build_dir/rope_paired_runner"
