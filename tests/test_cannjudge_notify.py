"""Notification tests never connect to SSH or start a Codex session."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from judge_workflow.core import read_json, write_json
from judge_workflow.notify import notify_remote


class NotifyTests(unittest.TestCase):
    def test_pinned_thread_is_queued_once_with_git_revision_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / 'config.json'
            thread = '00000000-0000-4000-8000-000000000001'
            write_json(config, {'ssh_host': 'Ascend910', 'thread_id': thread})
            record = {'run_id': 'fixture-run', 'kernel_sha256': 'a' * 64, 'platform_status': 'Pass'}
            request = {'result_path': 'platform_results/rotary_pos_emb/fixture-run.json'}
            with patch('judge_workflow.notify.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Queued', '')) as run:
                state = notify_remote(record, request, {'git_commit': 'b' * 40}, config, directory)
                notify_remote(record, request, {'git_commit': 'b' * 40}, config, directory)
            self.assertEqual(state['state'], 'queued')
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[-2], 'Ascend910')
            self.assertIn(thread, command[-1])
            self.assertIn('a' * 64, command[-1])
            self.assertIn('AGENTIC.md', command[-1])
            self.assertIn('profiling', command[-1])
            self.assertIn('docs/rope_optimization_strategy.md', command[-1])
            self.assertIn('numerical error chain', command[-1])
            self.assertIn('GM/UB traffic', command[-1])
            self.assertNotIn('dangerously-bypass', command[-1])

    def test_timeout_is_durable_and_is_not_automatically_resent(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); config = directory / 'config.json'
            write_json(config, {'ssh_host': 'Ascend910', 'thread_id': '00000000-0000-4000-8000-000000000001'})
            record = {'run_id': 'fixture-run', 'kernel_sha256': 'a' * 64}
            with patch('judge_workflow.notify.subprocess.run', side_effect=subprocess.TimeoutExpired('ssh', 45)) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    notify_remote(record, {'result_path': 'result.json'}, {'git_commit': 'b' * 40}, config, directory)
                with self.assertRaises(ValueError):
                    notify_remote(record, {'result_path': 'result.json'}, {'git_commit': 'b' * 40}, config, directory)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(read_json(directory / 'notification.json')['state'], 'uncertain')

    def test_continuation_task_has_its_own_notification_and_reuses_the_real_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); config = directory / 'config.json'
            write_json(config, {'ssh_host': 'Ascend910', 'thread_id': '00000000-0000-4000-8000-000000000001'})
            record = {'run_id': 'baseline-run', 'kernel_sha256': 'a' * 64}
            request = {'request_id': 'new-experiment', 'result_path': 'platform_results/rotary_pos_emb/baseline-run.json',
                       'requested_focus': 'Test a new vector hypothesis, retaining the rejected experiment record'}
            with patch('judge_workflow.notify.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Queued', '')) as run:
                result = notify_remote(record, request, {'git_commit': 'b' * 40}, config, directory)
                notify_remote(record, request, {'git_commit': 'b' * 40}, config, directory)
            self.assertEqual(result['request_id'], 'new-experiment')
            self.assertEqual(run.call_count, 1)
            self.assertIn('request_id=new-experiment', run.call_args.args[0][-1])
            self.assertIn('baseline-run.json', run.call_args.args[0][-1])
            self.assertTrue((directory / 'notification-new-experiment.json').exists())


if __name__ == '__main__':
    unittest.main()
