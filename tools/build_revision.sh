#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
ref="${1:?usage: build_revision.sh GIT_REF LABEL}"
label="${2:?usage: build_revision.sh GIT_REF LABEL}"
if [[ ! "$label" =~ ^[a-zA-Z0-9_-]+$ ]]; then echo 'invalid label'; exit 2; fi
revision="$(git rev-parse --verify "${ref}^{commit}")"
source_dir="$(pwd)/build/revisions/$revision"
mkdir -p "$source_dir"
git show "$revision:operators/rotary_pos_emb/kernel.asc" > "$source_dir/kernel.asc"
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S . -B "$source_dir/build" -DROPE_KERNEL_DIR="$source_dir" -DNPU_ARCH="${NPU_ARCH:-dav-2201}"
cmake --build "$source_dir/build" -j4
cp "$source_dir/build/rope_runner" "build/rope_runner_$label"
python3 tools/stamp_build.py --source "$source_dir/kernel.asc" --binary "build/rope_runner_$label" --ref "$revision"
