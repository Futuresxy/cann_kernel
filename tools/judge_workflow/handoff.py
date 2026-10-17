"""Git handoff to an existing tuning session; no SSH or environment management."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .core import TERMINAL, read_json, utcnow, write_json
from .repository import git

REQUESTS = 'tuning_requests/rotary_pos_emb'


def tuning_response(repository, request_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', request_id):
        raise ValueError('Invalid response request ID')
    try:
        data = git(repository, 'show', f'FETCH_HEAD:tuning_responses/rotary_pos_emb/{request_id}.json')
    except ValueError:
        return None
    response = json.loads(data)
    if response.get('request_id') != request_id or response.get('state') not in ('blocked', 'no_improvement'):
        raise ValueError('Invalid remote tuning response')
    return response


def create_request(record, report, repository):
    if record['state'] not in TERMINAL:
        raise ValueError('Only completed feedback can request another tuning round')
    run_id = record['run_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('Invalid handoff ID')
    request = {'schema_version': 1, 'request_id': run_id, 'state': 'ready_for_tuning',
               'baseline_run_id': run_id,
               'parent_kernel_sha256': record['kernel_sha256'], 'source_git_commit': record['git_commit'],
               'result_path': f'platform_results/rotary_pos_emb/{run_id}.json',
               'result_state': record['state'], 'platform_status': record.get('platform_status'),
               'official_score_raw': record.get('platform_score_raw'), 'rank_at_capture': record.get('platform_rank'),
               'cases': report.get('cases', []),
               'priority_case_ids': [c['id'] for c in report.get('slowest_relative_to_best', [])[:5]],
               'required_output': {'status': 'ready', 'path': 'submissions/rotary_pos_emb/latest.json',
                                   'tuning_request_id': run_id,
                                   'evidence': 'New source hash with complete correctness, single-launch and compliance evidence'},
               'user_policy_files': ['~/cann_kernel/project/AGENTIC.md',
                                     '~/cann_kernel/project/kernel_requirement.md',
                                     '~/cann_kernel/project/forbidden.md'],
               'experiment_log': f'benchmarks/experiments/agentic/{run_id}.json',
               'experiment_fields': ['prior_attempts_reviewed', 'hypothesis', 'bottleneck_evidence',
                                     'parent_source_sha256', 'candidate_source_sha256',
                                     'changes', 'validation', 'local_performance', 'decision', 'next_steps'],
               'execution_constraints': ['Use the existing user environment; no installation or system configuration',
                                        'Only kernel.asc changes in the competition project',
                                        'NPU tasks serial, one card, task-submit, at most 60 seconds per task',
                                        'Do not infer hidden shapes from case IDs or bypass correctness',
                                        'State one optimization hypothesis and measure before publishing'],
               'created_at': utcnow()}
    if record.get('tuning_request_id'):
        request['responds_to'] = record['tuning_request_id']
    context = report.get('problem_context')
    if context:
        request['problem_context'] = {k: context.get(k) for k in ('source_url', 'start', 'deadline', 'constraints', 'rules', 'precision', 'scoring')}
    leaders = report.get('leaderboard', {}).get('leaders', [])
    request['leaders'] = [{k: row[k] for k in ('rank', 'score_raw', 'cases') if k in row} for row in leaders]
    diagnostics = report.get('diagnostics', {})
    # Share compiler locations/messages, not raw page text, account data or logs.
    errors = []
    for match in re.finditer(r'(kernel\.asc):(\d+)(?::(\d+))?:\s*((?:fatal )?error:[^\n]+)', diagnostics.get('message', '')):
        error = {'file': match[1], 'line': int(match[2]), 'message': match[4][:500]}
        if match[3]:
            error['column'] = int(match[3])
        if error not in errors:
            errors.append(error)
    request['compiler_errors'] = errors
    path = Path(repository) / REQUESTS / (run_id + '.json')
    if not path.exists():
        write_json(path, request)
    else:
        previous = read_json(path)
        if previous['parent_kernel_sha256'] != record['kernel_sha256']:
            raise ValueError('An immutable handoff ID was reused for different source')
    return path


def publish_feedback(request_path, repository):
    """Publish only two allowlisted files in a disposable clone; never alter the user's index."""
    repository = Path(repository).resolve()
    request = read_json(request_path)
    request_relative = f'{REQUESTS}/{request["request_id"]}.json'
    result_relative = request['result_path']
    baseline = request.get('baseline_run_id', request['request_id'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', request['request_id']) or not re.fullmatch(r'[A-Za-z0-9_-]+', baseline) or result_relative != f'platform_results/rotary_pos_emb/{baseline}.json':
        raise ValueError('Unexpected feedback publication path')
    contents = {name: (repository / name).read_bytes() for name in (request_relative, result_relative)}
    result = json.loads(contents[result_relative])
    if result.get('run_id') != baseline or result.get('kernel_sha256') != request['parent_kernel_sha256']:
        raise ValueError('Tuning task does not match its completed baseline result')
    remote = git(repository, 'remote', 'get-url', 'origin').decode().strip()
    transport = ['-c', 'core.sshCommand=ssh -p 443 -o Hostname=ssh.github.com -o BatchMode=yes'] if remote.startswith('git@github.com:') else []
    with tempfile.TemporaryDirectory(prefix='cannjudge-feedback-') as temporary:
        checkout = Path(temporary) / 'repository'
        git(repository, 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout))
        git(checkout, 'remote', 'set-url', 'origin', remote)
        for attempt in range(3):
            git(checkout, 'fetch', '--no-tags', 'origin', 'main')
            git(checkout, 'checkout', '--quiet', '-B', 'cannjudge-feedback', 'FETCH_HEAD')
            for name, data in contents.items():
                target = checkout / name
                if name == request_relative and target.exists() and target.read_bytes() != data:
                    raise ValueError('Remote handoff is immutable and already contains different data')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            git(checkout, 'add', '--', *contents)
            changed = git(checkout, 'diff', '--cached', '--name-only')
            if not changed:
                return git(checkout, 'rev-parse', 'HEAD').decode().strip()
            git(checkout, '-c', 'user.name=CANNJudge feedback', '-c', 'user.email=cannjudge-feedback@localhost',
                'commit', '--quiet', '-m', 'Record CANNJudge feedback ' + request['request_id'])
            process = subprocess.run(['git', *transport, 'push', 'origin', 'HEAD:refs/heads/main'], cwd=checkout,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode == 0:
                return git(checkout, 'rev-parse', 'HEAD').decode().strip()
            if attempt == 2:
                raise ValueError('Feedback push failed: ' + process.stderr.decode(errors='replace'))


def inbox(repository, after=None, wait=False, interval=60, timeout=1800):
    if interval < 60 or timeout < interval:
        raise ValueError('Inbox needs interval >=60 seconds and timeout >=interval')
    deadline = time.monotonic() + timeout
    while True:
        git(repository, 'fetch', '--no-tags', 'origin', 'main')
        tip = git(repository, 'rev-parse', 'FETCH_HEAD').decode().strip()
        names = git(repository, 'ls-tree', '-r', '--name-only', tip, '--', REQUESTS).decode().splitlines()
        for name in sorted(names, key=lambda value: Path(value).stem, reverse=True):
            request_id = Path(name).stem
            if not name.endswith('.json') or (after and request_id <= after):
                continue
            request = json.loads(git(repository, 'show', tip + ':' + name))
            if request.get('state') != 'ready_for_tuning':
                continue
            if request.get('schema_version') != 1 or request.get('request_id') != request_id or not re.fullmatch(r'[0-9a-f]{64}', request.get('parent_kernel_sha256', '')):
                raise ValueError('Invalid tuning request identity')
            path = Path(repository) / '.local/cannjudge/inbox' / (request_id + '.json')
            write_json(path, request)
            return path
        if not wait or time.monotonic() + interval >= deadline:
            return None
        print('Waiting for Mac performance feedback; no NPU resources are held', flush=True)
        time.sleep(interval)
