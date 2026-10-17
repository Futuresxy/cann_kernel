"""Wake one pinned existing Codex thread after Git feedback is durable."""
import re
import shlex
import subprocess
import uuid

from .core import read_json, utcnow, write_json


def notify_remote(record, request, publication, config_path, directory):
    config = read_json(config_path)
    host = config['ssh_host']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host):
        raise ValueError('Notification needs an SSH host alias, not shell options')
    thread = str(uuid.UUID(config['thread_id']))
    task_id = request.get('request_id', record['run_id'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', task_id):
        raise ValueError('Invalid notification task ID')
    receipt = directory / ('notification.json' if task_id == record['run_id'] else f'notification-{task_id}.json')
    if receipt.exists():
        previous = read_json(receipt)
        if previous['state'] == 'queued':
            return previous
        raise ValueError('A previous notification is uncertain; check the fixed thread before resending')
    message = (
        f'[CANNJudge coordinator request_id={task_id}] '
        f'Mac feedback is pushed to origin/main at {publication["git_commit"]}. '
        f'Read tuning_requests/rotary_pos_emb/{task_id}.json and {request["result_path"]}. '
        f'Parent kernel SHA256={record["kernel_sha256"]}; status={record.get("platform_status")}; '
        f'official score={record.get("platform_score_raw")}. '
        'Mac is the coordinator and is already watching GitHub; do not operate the Mac browser. '
        'Preserve existing work, fetch the new tooling, and read docs/codex_handoff.md. '
        'Before development read ~/cann_kernel/project/AGENTIC.md and its referenced '
        'kernel_requirement.md and forbidden.md; preserve these user-edited untracked files. '
        'Use their current requirements, including matched_ratio >=0.99 and max_abs_error limits; '
        'do not change or interfere with judge precision/timing. All required math must execute '
        'on Device, one kernel per invocation, no Host tensor computation, hardcoded generated results, '
        'testcase-specific shortcuts, warmup detection, stale outputs or cross-invocation caches. '
        'Read docs/rope_optimization_strategy.md before selecting an optimization. '
        'Analyze the RoPE algorithm and numerical error chain first; then model dataflow, GM/UB traffic, '
        'copies, casts, fusion, parallelism and hardware utilization for the actual dtype/shape family; '
        'finally use source-bound profiling and assembly to identify the critical bottleneck. '
        'Distinguish FP16/FP32 x/y from int32 positions. Do not infer lane utilization from VEC busy ratio. '
        'First review the existing tuning reports and benchmarks/experiments, then maintain '
        'benchmarks/experiments/agentic/history.json and a per-request JSON experiment log. '
        'Record algorithm/work and dataflow models, prior attempts, hypothesis, expected metric changes, '
        'PMU/profiling bottleneck evidence, source hashes, change, '
        'correctness and launch checks, paired local timings, decision and why rejected ideas failed. '
        'Do not repeat a disproved approach without new evidence. '
        'Handle this request ID at most once. Use the existing server environment only; no installation, '
        'system configuration, driver or queue management. Choose one profiling-supported hypothesis, '
        'change only kernel.asc in the competition project, validate correctness and one device kernel '
        'per invocation, and use task-submit serially with one card and at most 60 seconds per task. '
        'Publish at most one new validated ready candidate for this notification, using stage --request '
        'and --hypothesis so candidate.json and latest.json retain tuning_request_id. Commit/push normally; '
        'do not overwrite local changes or force-push. If no safe improvement or validation is blocked, '
        f'commit tuning_responses/rotary_pos_emb/{task_id}.json with request_id, state="blocked" '
        'or "no_improvement", reason and evidence paths, then stop. After publishing, stop and wait '
        'for the next Mac notification; do not independently loop or submit to the competition. '
        f'The official platform score target is {config.get("target_score", 70)} or higher, '
        f'from the V9 baseline 48.45; this coordinator batch allows at most {config.get("max_new_rounds", 2)} new candidates. '
        'Reuse existing source-matched measurements before collecting missing evidence. '
        'Choose the experiment from the diagnosed family bottleneck rather than repeatedly trying local instruction substitutions. '
        'Account for frequency/trigonometry initialization, scalar overhead, MTE2/MTE3, vector instructions, '
        'UB traffic/capacity and within-invocation reuse where relevant. '
        'Inherited precision failures must be attributed without changing the golden or thresholds before ready publication. '
        'Use paired native Task Duration measurements, not replay timing, to decide what to publish.')
    if request.get('requested_focus'):
        message += ' New coordinator direction: ' + request['requested_focus']
    state = {'request_id': task_id, 'ssh_host': host, 'thread_id': thread,
             'state': 'queue_intent', 'created_at': utcnow(), 'publication': publication['git_commit']}
    write_json(receipt, state)
    command = shlex.join(['codex', 'queue', '--thread', thread, '--message', message])
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, command],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        if result.returncode:
            raise ValueError('Remote queue failed: ' + result.stderr.strip())
        state.update(state='queued', queued_at=utcnow(), response=result.stdout.strip())
        write_json(receipt, state)
        return state
    except Exception as error:
        state.update(state='uncertain', error=str(error))
        write_json(receipt, state)
        raise
