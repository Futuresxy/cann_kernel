#!/usr/bin/env bash
# Run on the Mac. Ascend is not needed for Git sync or browser interaction.
set -eo pipefail
cd "$(dirname "$0")/.."
task_action="${1:-help}"
if [ "$#" -gt 0 ]; then shift; fi
task_python="${CANNJUDGE_PYTHON:-python3}"
task_venv="$PWD/.local/cannjudge/venv"
task_config="$PWD/.local/cannjudge/config.json"
case "$task_action" in
  setup)
    "$task_python" -c 'import sys; assert sys.version_info >= (3,10), "Requires Python 3.10 or newer; set CANNJUDGE_PYTHON to its executable"'
    "$task_python" -m venv "$task_venv"
    "$task_venv/bin/python" -m pip install -r tools/judge_workflow/requirements.txt
    if [ ! -e "$task_config" ]; then
      cp tools/judge_workflow/cannjudge.example.json "$task_config"
    fi
    printf '%s\n' '准备完成。下一步：bash tools/mac_cannjudge.sh login'
    ;;
  login|inspect|resume)
    if [ ! -x "$task_venv/bin/python" ]; then
      printf '%s\n' '请先运行：bash tools/mac_cannjudge.sh setup' >&2
      exit 2
    fi
    "$task_venv/bin/python" tools/cannjudge.py "$task_action" --channel chrome --config "$task_config" "$@"
    ;;
  sync)
    "$task_python" tools/cannjudge.py sync "$@"
    ;;
  submit)
    if [ "$#" -ne 0 ]; then
      printf '%s\n' 'submit 会同步并提交 GitHub 已验证版本，无需传入候选路径。' >&2
      exit 2
    fi
    if [ ! -x "$task_venv/bin/python" ]; then
      printf '%s\n' '请先运行：bash tools/mac_cannjudge.sh setup' >&2
      exit 2
    fi
    # Fetch one immutable Git snapshot; never pull/reset the local checkout.
    task_candidate=$("$task_venv/bin/python" -c 'import sys; from pathlib import Path; sys.path.insert(0,"tools"); from judge_workflow.repository import sync_candidate; print(sync_candidate()[0].resolve())')
    "$task_venv/bin/python" tools/cannjudge.py submit --channel chrome --config "$task_config" --candidate "$task_candidate"
    ;;
  export-result|compare)
    "$task_python" tools/cannjudge.py "$task_action" "$@"
    ;;
  *)
    printf '%s\n' '用法：bash tools/mac_cannjudge.sh setup|login|inspect|sync|submit|resume|export-result|compare'
    ;;
esac
