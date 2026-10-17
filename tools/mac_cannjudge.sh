#!/usr/bin/env bash
# Run on the Mac. Ascend is not needed for Git sync or browser interaction.
set -eo pipefail
cd "$(dirname "$0")/.."
task_action="${1:-help}"
if [ "$#" -gt 0 ]; then shift; fi
task_python="${CANNJUDGE_PYTHON:-python3}"
task_venv="$PWD/.local/cannjudge/venv"
task_config="$PWD/.local/cannjudge/config.json"
if [ -z "${CANNJUDGE_PYTHON:-}" ] && [ -x "$PWD/.venv/bin/python" ]; then
  task_python="$PWD/.venv/bin/python"
fi
case "$task_action" in
  setup)
    "$task_python" -c 'import sys; assert sys.version_info >= (3,10), "Requires Python 3.10 or newer; set CANNJUDGE_PYTHON to its executable"'
    "$task_python" -m venv "$task_venv"
    "$task_venv/bin/python" -m pip install -r tools/judge_workflow/requirements.txt
    if [ ! -e "$task_config" ]; then
      cp tools/judge_workflow/cannjudge.live.json "$task_config"
    fi
    printf '%s\n' '准备完成。下一步：bash tools/mac_cannjudge.sh login'
    ;;
  login|inspect|resume|run|watch|preflight)
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
    if [ ! -x "$task_venv/bin/python" ]; then
      printf '%s\n' '请先运行：bash tools/mac_cannjudge.sh setup' >&2
      exit 2
    fi
    # Fetch one immutable Git snapshot; never pull/reset the local checkout.
    if [ "$#" -eq 0 ]; then
      task_candidate=$("$task_venv/bin/python" -c 'import sys; from pathlib import Path; sys.path.insert(0,"tools"); from judge_workflow.repository import sync_candidate; print(sync_candidate()[0].resolve())')
      set -- --candidate "$task_candidate"
    fi
    "$task_venv/bin/python" tools/cannjudge.py submit --channel chrome --config "$task_config" "$@"
    ;;
  export-result|compare|handoff|inbox)
    "$task_python" tools/cannjudge.py "$task_action" "$@"
    ;;
  *)
    printf '%s\n' '用法：bash tools/mac_cannjudge.sh setup|login|inspect|preflight|run|watch|sync|submit|resume|export-result|compare|handoff|inbox'
    ;;
esac
