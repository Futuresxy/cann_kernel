#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
label="${1:-baseline}"
shift || true
device=0
while (($#)); do
    case "$1" in --device) device="$2"; shift 2;; *) echo "unknown option $1"; exit 2;; esac
done
mkdir -p "build/profiles/$label"
# One representative kernel, three PMU groups. Launch replay is bounded.
exec msprof op --aic-metrics=PipeUtilization,Memory,MemoryUB \
    --launch-count=1 --launch-skip-before-match=5 --warm-up=2 \
    --output="build/profiles/$label" \
    --application="$(pwd)/build/rope_runner --device $device --shape 2 512 128 64 --dtype float16 --input $(pwd)/build/data/deepseek_half --output $(pwd)/build/profile_output.bin --warmup 6 --repeat 2 --batches 1"
