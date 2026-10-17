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
from judge_workflow.repository import POINTER, SOURCE, export_result, publish_candidate, share_result, sync_candidate
from test_cannjudge_workflow import SOURCE as KERNEL, fixture_candidate


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

    def feedback_remote(self):
        self.publish()
        self.git('branch', '-M', 'main')
        remote = self.base / 'remote.git'
        subprocess.check_call(['git', 'clone', '--bare', '-q', str(self.repository), str(remote)])
        self.git('remote', 'add', 'origin', str(remote))
        run = self.base / 'real-run.json'
        write_json(run, {'run_id': 'fixture-feedback', 'kernel_sha256': digest(KERNEL), 'git_commit': self.revision,
                         'submission_id': '878062', 'state': 'accepted', 'platform_status': 'Pass',
                         'cases': [{'id': i, 'latency_us': i+0.5, 'status': 'Pass', 'error_percent': 0,
                                    'best_latency_us': 0.8} for i in range(1,16)],
                         'cookies': 'private-login-secret', 'result_url': 'https://example.invalid/?private-login-secret'})
        return remote, run

    def remote_git(self, remote, *args):
        return subprocess.check_output(['git', '--git-dir', str(remote), *args], text=True).strip()

    def test_feedback_push_preserves_local_head_index_and_worktree(self):
        remote, run = self.feedback_remote()
        kernel = self.repository / SOURCE
        kernel.write_bytes(b'local staged kernel edit')
        self.git('add', SOURCE)
        (self.repository / 'private-untracked.txt').write_text('private-login-secret')
        before = (self.git('rev-parse', 'HEAD'), self.git('diff', '--cached'), self.git('status', '--porcelain'))
        result = share_result(run, self.repository)
        self.assertTrue(result['pushed'])
        self.assertEqual(before, (self.git('rev-parse', 'HEAD'), self.git('diff', '--cached'), self.git('status', '--porcelain')))
        self.assertEqual(kernel.read_bytes(), b'local staged kernel edit')
        changed = self.remote_git(remote, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'main')
        self.assertEqual(changed, result['result_path'])
        self.assertNotIn('private-login-secret', self.remote_git(remote, 'show', 'main:' + result['result_path']))
        self.assertFalse((self.repository / result['result_path']).exists())
        self.git('pull', '--ff-only', 'origin', 'main')
        self.assertTrue((self.repository / result['result_path']).exists())
        self.assertEqual(kernel.read_bytes(), b'local staged kernel edit')

    def test_feedback_publish_is_idempotent_and_rejects_a_changed_result(self):
        remote, run = self.feedback_remote()
        first = share_result(run, self.repository)
        second = share_result(run, self.repository)
        self.assertTrue(first['pushed'])
        self.assertFalse(second['pushed'])
        self.assertEqual(first['published_commit'], second['published_commit'])
        record = read_json(run); record['cases'][0]['latency_us'] = 999; write_json(run, record)
        with self.assertRaisesRegex(ValueError, 'different immutable result'):
            share_result(run, self.repository)

    def test_feedback_rejects_incorrect_source_association(self):
        remote, run = self.feedback_remote()
        original = self.remote_git(remote, 'rev-parse', 'main')
        record = read_json(run); record['kernel_sha256'] = '0'*64; write_json(run, record)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            share_result(run, self.repository)
        self.assertEqual(self.remote_git(remote, 'rev-parse', 'main'), original)

    def test_feedback_retries_a_concurrent_push_without_overwriting_it(self):
        from judge_workflow import repository as exchange
        remote, run = self.feedback_remote()
        other = self.base / 'other clone'
        subprocess.check_call(['git', 'clone', '-q', str(remote), str(other)])
        def other_git(*args):
            subprocess.check_call(['git', *args], cwd=other, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        other_git('config', 'user.name', 'Concurrent fixture')
        other_git('config', 'user.email', 'fixture@example.invalid')
        actual_git = exchange.git
        pushes = 0
        def concurrent(repository, *args, **kwargs):
            nonlocal pushes
            if args[0] == 'push':
                pushes += 1
                if pushes == 1:
                    (other / 'concurrent.txt').write_text('another valid change')
                    other_git('add', 'concurrent.txt'); other_git('commit', '-qm', 'concurrent update')
                    other_git('push', 'origin', 'main')
            return actual_git(repository, *args, **kwargs)
        with patch.object(exchange, 'git', concurrent):
            result = share_result(run, self.repository)
        self.assertEqual(pushes, 2)
        self.assertTrue(result['pushed'])
        self.assertEqual(self.remote_git(remote, 'show', 'main:concurrent.txt'), 'another valid change')


if __name__ == '__main__':
    unittest.main(verbosity=2)
