"""Git exchange tests. Local repositories only; no GitHub, browser or NPU."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from judge_workflow.core import digest, read_json, validate_candidate, write_json
from judge_workflow.repository import POINTER, SOURCE, export_result, publish_candidate, sync_candidate, git
from test_cannjudge_workflow import SOURCE as KERNEL, fixture_candidate
from judge_workflow.handoff import create_request, publish_feedback, inbox


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repository = self.base / 'repository'
        self.repository.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Local fixture')
        kernel = self.repository / SOURCE
        kernel.parent.mkdir(parents=True)
        kernel.write_bytes(KERNEL)
        self.git('add', '.'); self.git('commit', '-qm', 'fixture kernel')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        self.candidate = self.base / 'candidate'
        manifest = fixture_candidate(self.candidate)
        manifest['git_commit'] = self.revision
        package = self.candidate / 'evidence/package.json'
        content = read_json(package); content['git_commit'] = self.revision; write_json(package, content)
        manifest['evidence_sha256']['package.json'] = digest(package.read_bytes())
        write_json(self.candidate / 'candidate.json', manifest)

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repository, text=True, stderr=subprocess.PIPE)

    def publish(self):
        result = publish_candidate(self.candidate, self.repository)
        self.git('add', '.'); self.git('commit', '-qm', 'publish fixture')
        return result

    def test_publish_sync_preserves_mac_worktree(self):
        (self.candidate / 'not_for_github.txt').write_text('must not be copied')
        published = self.publish()
        self.assertFalse((published / 'not_for_github.txt').exists())
        (self.repository / SOURCE).write_bytes(b'local user edit')
        result, tip = sync_candidate(self.repository, self.base / 'downloads', fetch=False, ref='HEAD')
        self.assertEqual((self.repository / SOURCE).read_bytes(), b'local user edit')
        self.assertEqual((result / 'kernel.asc').read_bytes(), KERNEL)
        self.assertEqual(validate_candidate(result)[0]['git_commit'], self.revision)
        self.assertEqual(tip, self.git('rev-parse', 'HEAD').strip())

    def test_fetch_candidate_in_separate_mac_clone(self):
        self.publish()
        self.git('branch', '-M', 'main')
        clone = self.base / 'mac clone'
        subprocess.check_call(['git', 'clone', '-q', str(self.repository), str(clone)])
        result, tip = sync_candidate(clone, clone / 'build/candidates')
        self.assertEqual((result / 'kernel.asc').read_bytes(), KERNEL)
        self.assertEqual(tip, self.git('rev-parse', 'HEAD').strip())

    def test_blocked_release_never_becomes_a_candidate(self):
        write_json(self.repository / POINTER, {'status': 'blocked', 'reason': 'Host frequency table'})
        self.git('add', '.'); self.git('commit', '-qm', 'blocked')
        with self.assertRaisesRegex(ValueError, 'Host frequency table'):
            sync_candidate(self.repository, self.base / 'downloads', fetch=False, ref='HEAD')

    def test_new_unvalidated_git_kernel_blocks_old_pointer(self):
        self.publish()
        (self.repository / SOURCE).write_bytes(KERNEL + b'// new source\n')
        self.git('add', '.'); self.git('commit', '-qm', 'unvalidated change')
        with self.assertRaisesRegex(ValueError, 'differs'):
            sync_candidate(self.repository, self.base / 'downloads', fetch=False, ref='HEAD')

    def test_published_evidence_tampering_is_blocked(self):
        published = self.publish()
        (published / 'evidence/correctness.json').write_text('{}')
        self.git('add', '.'); self.git('commit', '-qm', 'broken evidence')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            sync_candidate(self.repository, self.base / 'downloads', fetch=False, ref='HEAD')

    def test_export_omits_private_browser_information(self):
        run = self.base / 'run.json'
        record = {'run_id': 'fixture-run-1', 'kernel_sha256': digest(KERNEL), 'git_commit': self.revision,
                  'submission_id': 'test-1', 'state': 'accepted', 'platform_status': 'Accepted',
                  'cases': [{'id': i, 'latency_us': 2.5} for i in range(1, 16)],
                  'cookies': 'private', 'result_url': 'https://example.invalid/?secret=private',
                  'last_error': 'private account details'}
        write_json(run, record)
        destination = export_result(run, self.repository)
        exported = read_json(destination)
        self.assertEqual(len(exported['cases']), 15)
        self.assertNotIn('private', destination.read_text())
        record['state'] = 'pending'; write_json(run, record)
        with self.assertRaises(ValueError): export_result(run, self.repository)

    def test_github_fetch_retries_443_without_changing_ssh_configuration(self):
        replies = [subprocess.CompletedProcess([], 128, b'', b'Connection closed by host port 22'),
                   subprocess.CompletedProcess([], 0, b'git@github.com:fixture/repo.git\n', b''),
                   subprocess.CompletedProcess([], 0, b'fetched', b'')]
        with patch('judge_workflow.repository.subprocess.run', side_effect=replies) as run:
            self.assertEqual(git(self.repository, 'fetch', 'origin', 'main'), b'fetched')
        self.assertIn('core.sshCommand=ssh -p 443 -o Hostname=ssh.github.com -o BatchMode=yes', run.call_args.args[0])

    def test_failed_push_is_never_automatically_retried(self):
        with patch('judge_workflow.repository.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 128, b'', b'Connection closed by host port 22')) as run:
            with self.assertRaises(ValueError): git(self.repository, 'push', 'origin', 'main')
        self.assertEqual(run.call_count, 1)

    def test_feedback_handoff_publishes_only_result_and_task_without_touching_worktree(self):
        self.git('branch', '-M', 'main')
        remote = self.base / 'origin.git'
        subprocess.check_call(['git', 'clone', '--bare', '-q', str(self.repository), str(remote)])
        self.git('remote', 'add', 'origin', str(remote))
        record = {'run_id': '20261017T000000Z-fixture', 'state': 'accepted', 'submission_id': 'job-1',
                  'kernel_sha256': digest(KERNEL), 'git_commit': self.revision, 'platform_score_raw': '48.45',
                  'cases': [{'id': i, 'latency_us': 2.5} for i in range(1, 16)]}
        path = self.base / 'run.json'; write_json(path, record)
        exported = export_result(path, self.repository)
        request = create_request(record, {'cases': record['cases'], 'diagnostics': {
            'message': 'private account information\nkernel.asc:123:7: error: invalid expression'}}, self.repository)
        self.assertNotIn('private account', request.read_text())
        self.assertEqual(read_json(request)['compiler_errors'][0]['line'], 123)
        (self.repository / SOURCE).write_text('local user edit')
        before_head = self.git('rev-parse', 'HEAD')
        before_index = self.git('diff', '--cached')
        revision = publish_feedback(request, self.repository)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before_head)
        self.assertEqual(self.git('diff', '--cached'), before_index)
        self.assertEqual((self.repository / SOURCE).read_text(), 'local user edit')
        changed = subprocess.check_output(['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', revision], cwd=remote, text=True).splitlines()
        self.assertEqual(set(changed), {exported.relative_to(self.repository).as_posix(), request.relative_to(self.repository).as_posix()})
        received = inbox(self.repository)
        self.assertEqual(read_json(received)['request_id'], record['run_id'])
        self.assertIsNone(inbox(self.repository, after=record['run_id']))
        self.assertEqual(publish_feedback(request, self.repository), revision)
        # A rejected local experiment can start another task without inventing
        # a new competition submission or overwriting the original task.
        next_task = read_json(request)
        next_task.update(request_id=record['run_id'] + '-experiment2', baseline_run_id=record['run_id'])
        next_task['required_output']['tuning_request_id'] = next_task['request_id']
        next_path = self.repository / 'tuning_requests/rotary_pos_emb' / (next_task['request_id'] + '.json')
        write_json(next_path, next_task)
        next_revision = publish_feedback(next_path, self.repository)
        self.assertNotEqual(next_revision, revision)
        self.assertEqual(read_json(inbox(self.repository))['request_id'], next_task['request_id'])
        next_task['parent_kernel_sha256'] = '0' * 64
        write_json(next_path, next_task)
        with self.assertRaisesRegex(ValueError, 'baseline result'):
            publish_feedback(next_path, self.repository)

    def test_tuning_request_identity_survives_publish_and_sync(self):
        path = self.candidate / 'candidate.json'
        manifest = read_json(path); manifest['tuning_request_id'] = 'fixture-request'; write_json(path, manifest)
        self.publish()
        self.assertEqual(read_json(self.repository / POINTER)['tuning_request_id'], 'fixture-request')
        destination, _ = sync_candidate(self.repository, self.base / 'downloads', fetch=False, ref='HEAD')
        self.assertEqual(read_json(destination / 'candidate.json')['tuning_request_id'], 'fixture-request')


if __name__ == '__main__':
    unittest.main(verbosity=2)
