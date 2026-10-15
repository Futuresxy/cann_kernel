#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
python3 tools/verify_submission.py
python3 - <<'PY'
from zipfile import ZipFile
with ZipFile('dist/rotaryposemb_1743_submission.zip') as z:
    z.extractall('build/template_only_submission_check')
PY
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S build/template_only_submission_check -B build/template_only_submission_check/build
cmake --build build/template_only_submission_check/build -j4
cd build/template_only_submission_check/build
python3 ../scripts/gen_data.py
cp input/case0/x.bin input/x.bin
cp input/case0/positions.bin input/positions.bin
cp output/golden_case0/golden_y.bin output/golden_y.bin
