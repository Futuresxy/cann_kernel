#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh
msprof --help > build/msprof_help.txt 2>&1
msprof op --help > build/msprof_op_help.txt 2>&1
