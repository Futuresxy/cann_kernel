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
    receipt = directory / 'notification.json'
    if receipt.exists():
        previous = read_json(receipt)
        if previous['state'] == 'queued':
            return previous
        raise ValueError('A previous notification is uncertain; check the fixed thread before resending')
    message = (
        f'[CANNJudge coordinator request_id={record["run_id"]}] '
        f'Mac feedback is pushed to origin/main at {publication["git_commit"]}. '
        f'Read tuning_requests/rotary_pos_emb/{record["run_id"]}.json and {request["result_path"]}. '
        f'Parent kernel SHA256={record["kernel_sha256"]}; status={record.get("platform_status")}; '
        f'official score={record.get("platform_score_raw")}. '
        'Mac is the coordinator and is already watching GitHub; do not operate the Mac browser. '
        'Preserve existing work, fetch the new tooling, and read docs/codex_handoff.md. '
        'Handle this request ID at most once. Use the existing server environment only; no installation, '
        'system configuration, driver or queue management. Choose one profiling-supported hypothesis, '
        'change only kernel.asc in the competition project, validate correctness and one device kernel '
        'per invocation, and use task-submit serially with one card and at most 60 seconds per task. '
        'Publish at most one new validated ready candidate for this notification, using stage --request '
        'and --hypothesis so candidate.json and latest.json retain tuning_request_id. Commit/push normally; '
        'do not overwrite local changes or force-push. If no safe improvement or validation is blocked, '
        f'commit tuning_responses/rotary_pos_emb/{record["run_id"]}.json with request_id, state="blocked" '
        'or "no_improvement", reason and evidence paths, then stop. After publishing, stop and wait '
        'for the next Mac notification; do not independently loop or submit to the competition. '
        'The Mac coordinator is limited to two new optimization rounds in this run.')
    state = {'request_id': record['run_id'], 'ssh_host': host, 'thread_id': thread,
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
