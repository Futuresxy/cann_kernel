#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
with ZipFile('dist/rotaryposemb_1743_submission.zip') as z:
    z.extractall('build/submission_check')
PY
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S build/submission_check -B build/submission_check/build
cmake --build build/submission_check/build -j4
cd build/submission_check/build
python3 ../scripts/gen_data.py
cp input/case0/x.bin input/x.bin
cp input/case0/positions.bin input/positions.bin
cp output/golden_case0/golden_y.bin output/golden_y.bin
