"""Exchange validated candidates and small platform summaries through Git."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .core import ROOT, TERMINAL, digest, read_json, utcnow, validate_candidate, write_json

PREFIX = 'submissions/rotary_pos_emb'
POINTER = PREFIX + '/latest.json'
SOURCE = 'operators/rotary_pos_emb/kernel.asc'
FILES = ('kernel.asc', 'candidate.json', 'evidence/compliance.json', 'evidence/package.json',
         'evidence/correctness.json', 'evidence/launch_audit.json', 'evidence/launch_count.json')


def git(repository, *args, env=None, input_data=None):
    process = subprocess.run(['git', *args], cwd=repository, env=env, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Only retry a read-only fetch, and only GitHub's SSH transport. This does
    # not edit SSH configuration or affect any Ascend host.
    if process.returncode and args and args[0] == 'fetch' and b'port 22' in process.stderr:
        remote = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=repository,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if remote.returncode == 0 and remote.stdout.strip().startswith(b'git@github.com:'):
            process = subprocess.run(['git', '-c', 'core.sshCommand=ssh -p 443 -o Hostname=ssh.github.com -o BatchMode=yes', *args],
                                     cwd=repository, env=env, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        raise ValueError('Git operation failed: ' + process.stderr.decode(errors='replace').strip())
    return process.stdout


def source_matches(repository, revision, data):
    if git(repository, 'show', revision + ':' + SOURCE) != data:
        raise ValueError('Git kernel source differs from the validated candidate')


def publish_candidate(candidate, repository=ROOT):
    """Write only the candidate allowlist; the caller commits/pushes these files."""
    repository, candidate = Path(repository), Path(candidate)
    manifest, data = validate_candidate(candidate)
    sha = manifest['kernel_sha256']
    source_commit = manifest['git_commit']
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source_commit):
        raise ValueError('Candidate must reference a full Git commit')
    source_matches(repository, source_commit, data)
    source_matches(repository, 'HEAD', data)
    destination = repository / PREFIX / sha
    if destination.exists():
        validate_candidate(destination)
        if any((destination / name).read_bytes() != (candidate / name).read_bytes() for name in FILES):
            raise ValueError('An immutable candidate already exists with different evidence')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.publish-', dir=destination.parent) as temporary:
            prepared = Path(temporary) / sha
            for name in FILES:
                target = prepared / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate / name, target)
            validate_candidate(prepared)
            prepared.rename(destination)
    pointer = {'status': 'ready', 'kernel_sha256': sha, 'git_commit': source_commit,
               'candidate_path': PREFIX + '/' + sha, 'published_at': utcnow()}
    if manifest.get('tuning_request_id'):
        pointer['tuning_request_id'] = manifest['tuning_request_id']
    write_json(repository / POINTER, pointer)
    return destination


def sync_candidate(repository=ROOT, output=None, fetch=True, ref='origin/main'):
    """Read one fetched Git commit without changing the user's checkout/index."""
    repository = Path(repository)
    output = Path(output) if output else repository / 'build/platform_candidates'
    if fetch:
        git(repository, 'fetch', '--no-tags', 'origin', 'main')
        ref = 'FETCH_HEAD'
    tip = git(repository, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
    try:
        pointer = json.loads(git(repository, 'show', tip + ':' + POINTER))
    except (ValueError, json.JSONDecodeError) as error:
        raise ValueError('No published candidate was found at the selected Git revision') from error
    if pointer.get('status') != 'ready':
        raise ValueError('GitHub candidate is not ready: ' + pointer.get('reason', 'unpublished or blocked'))
    sha = pointer.get('kernel_sha256', '')
    if not re.fullmatch(r'[0-9a-f]{64}', sha) or pointer.get('candidate_path') != PREFIX + '/' + sha:
        raise ValueError('Invalid published candidate path or SHA256')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=output) as temporary:
        prepared = Path(temporary) / sha
        for name in FILES:
            target = prepared / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(repository, 'show', tip + ':' + pointer['candidate_path'] + '/' + name))
        manifest, data = validate_candidate(prepared)
        if manifest['kernel_sha256'] != sha or manifest['git_commit'] != pointer.get('git_commit'):
            raise ValueError('Git pointer does not match the frozen candidate')
        if pointer.get('tuning_request_id') != manifest.get('tuning_request_id'):
            raise ValueError('Git pointer refers to a different tuning request')
        source_commit = manifest['git_commit']
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source_commit):
            raise ValueError('Invalid source commit')
        git(repository, 'merge-base', '--is-ancestor', source_commit, tip)
        source_matches(repository, source_commit, data)
        source_matches(repository, tip, data)
        destination = output / sha
        if destination.exists():
            validate_candidate(destination)
            if any((destination / name).read_bytes() != (prepared / name).read_bytes() for name in FILES):
                raise ValueError('A different local candidate already occupies this SHA256')
        else:
            prepared.rename(destination)
    return destination, tip


def export_result(run, repository=ROOT):
    """Copy an explicit allowlist; login state, screenshots and logs stay local."""
    record = read_json(run)
    if record.get('state') not in TERMINAL or not record.get('submission_id'):
        raise ValueError('Only a bound, completed platform result can be shared')
    if record['state'] == 'accepted' and (
            len(record.get('cases', [])) != 15 or {c['id'] for c in record['cases']} != set(range(1, 16))):
        raise ValueError('Accepted platform result needs all 15 test cases')
    run_id = record.get('run_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('Invalid run ID')
    allowed = ('run_id', 'kernel_sha256', 'git_commit', 'created_at', 'updated_at',
               'state', 'submission_id', 'platform_status', 'platform_score_raw',
               'platform_rank', 'displayed_timings_score', 'score_note', 'cases',
               'tuning_request_id', 'parent_kernel_sha256', 'optimization_hypothesis')
    summary = {key: record[key] for key in allowed if key in record}
    if 'cases' in summary:
        summary['cases'] = [{key: case[key] for key in ('id', 'latency_us', 'raw_latency', 'status',
                              'best_latency_us', 'ratio_to_best', 'output_error_percent',
                              'error_percent', 'raw_error_percent', 'raw_best_latency') if key in case}
                            for case in record['cases']]
    # URLs, raw errors and page content may contain user/account information.
    destination = Path(repository) / 'platform_results/rotary_pos_emb' / (run_id + '.json')
    if destination.exists():
        previous = read_json(destination)
        if {k: v for k, v in previous.items() if k != 'exported_at'} == summary:
            return destination
    summary['exported_at'] = utcnow()
    write_json(destination, summary)
    return destination


def share_result(run, repository=ROOT):
    """Publish one result on top of fetched main; preserve checkout and index.

    No pull, reset, force push or broad add. A concurrent push is retried once
    from the new remote tip. The run remains available if publishing fails.
    """
    repository = Path(repository)
    with tempfile.TemporaryDirectory(prefix='cannjudge-feedback-') as temporary:
        temporary = Path(temporary)
        summary_file = export_result(run, temporary)
        relative = summary_file.relative_to(temporary).as_posix()
        data = summary_file.read_bytes()
        summary = json.loads(data)
        sha, source = summary['kernel_sha256'], summary['git_commit']
        if not re.fullmatch(r'[0-9a-f]{64}', sha) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source):
            raise ValueError('Feedback must reference the full validated source SHA and Git commit')
        for attempt in range(2):
            git(repository, 'fetch', '--no-tags', 'origin', 'main')
            tip = git(repository, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}').decode().strip()
            git(repository, 'merge-base', '--is-ancestor', source, tip)
            if digest(git(repository, 'show', source + ':' + SOURCE)) != sha:
                raise ValueError('Feedback kernel SHA does not match its Git source commit')
            manifest = json.loads(git(repository, 'show', tip + ':' + PREFIX + '/' + sha + '/candidate.json'))
            if manifest['kernel_sha256'] != sha or manifest['git_commit'] != source:
                raise ValueError('Feedback source does not match a published candidate')
            if git(repository, 'ls-tree', '--name-only', tip, '--', relative).strip():
                existing = json.loads(git(repository, 'show', tip + ':' + relative))
                comparable = lambda value: {k: v for k, v in value.items() if k != 'exported_at'}
                if comparable(existing) != comparable(summary):
                    raise ValueError('A different immutable result already uses this run ID')
                return {'result_path': relative, 'published_commit': tip, 'pushed': False}
            index = temporary / ('git-index-' + str(attempt))
            env = dict(os.environ, GIT_INDEX_FILE=str(index))
            git(repository, 'read-tree', tip, env=env)
            blob = git(repository, 'hash-object', '-w', '--stdin', input_data=data).decode().strip()
            git(repository, 'update-index', '--add', '--cacheinfo', '100644', blob, relative, env=env)
            tree = git(repository, 'write-tree', env=env).decode().strip()
            message = ('Record CANNJudge result ' + str(summary['submission_id']) + '\n').encode()
            commit = git(repository, 'commit-tree', tree, '-p', tip, input_data=message).decode().strip()
            try:
                git(repository, 'push', 'origin', commit + ':refs/heads/main')
            except ValueError:
                if attempt:
                    raise
                continue
            return {'result_path': relative, 'published_commit': commit, 'pushed': True}
