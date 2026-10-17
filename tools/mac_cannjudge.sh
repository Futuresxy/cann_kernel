#!/usr/bin/env bash
# Run on the Mac. Ascend is not needed for Git sync or browser interaction.
set -eo pipefail
cd "$(dirname "$0")/.."
task_action="${1:-help}"
if [ "$#" -gt 0 ]; then shift; fi
task_python="${CANNJUDGE_PYTHON:-python3}"
task_venv="$PWD/.local/cannjudge/venv"
task_config="$PWD/.local/cannjudge/config.json"
if [ -z "${CANNJUDGE_PYTHON:-}" ]; then
  if [ "$task_action" != setup ] && [ -x "$task_venv/bin/python" ]; then
    task_python="$task_venv/bin/python"
  elif [ -x "$PWD/.venv/bin/python" ]; then
    task_python="$PWD/.venv/bin/python"
  fi
fi
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
  login|inspect|resume|calibrate-result|check-editor)
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
    if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != --publish-result ]; }; then
      printf '%s\n' 'submit 自动同步已验证候选；可加 --publish-result 自动回传成绩。' >&2
      exit 2
    fi
    if [ ! -x "$task_venv/bin/python" ]; then
      printf '%s\n' '请先运行：bash tools/mac_cannjudge.sh setup' >&2
      exit 2
    fi
    # Fetch one immutable Git snapshot; never pull/reset the local checkout.
    task_candidate=$("$task_venv/bin/python" -c 'import sys; from pathlib import Path; sys.path.insert(0,"tools"); from judge_workflow.repository import sync_candidate; print(sync_candidate()[0].resolve())')
    "$task_venv/bin/python" tools/cannjudge.py submit --channel chrome --config "$task_config" --candidate "$task_candidate" "$@"
    ;;
  export-result|share-result|compare)
    "$task_python" tools/cannjudge.py "$task_action" "$@"
    ;;
  *)
    printf '%s\n' '用法：bash tools/mac_cannjudge.sh setup|login|inspect|calibrate-result|check-editor|sync|submit|resume|export-result|share-result|compare'
    ;;
esac
