from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bot.installation.update import FocusUpdateController, UpdateError, stop_check_worker, unit_active


class UpdateCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.controller = FocusUpdateController(global_data_root=self.root / '_global')
        self.journal = self.controller.journal
        for target, name, value in (
            ('unavailable_reason', 'available', ''),
            ('launch_worker', 'launch', None),
            ('stop_check_worker', 'stop', None),
            ('unit_active', 'active', True),
        ):
            patcher = patch('bot.installation.update.' + target, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        operation = self.controller.start_check('stable', '')
        self.operation_id = operation['operation_id']
        self.staging = self.journal.directory(self.operation_id)
        self.staging.mkdir(parents=True)
        (self.staging / 'partial-download').write_text('partial')
        self.runtime = self.root / '.python' / 'shared-runtime'
        self.runtime.parent.mkdir()
        self.runtime.write_text('keep runtime')

    def test_cancel_waits_for_children_and_only_then_allows_a_different_target(self) -> None:
        status = self.controller.cancel_check(self.operation_id)
        self.assertEqual(status['state'], 'cancelling')
        self.assertFalse(status['restart_required'])
        self.assertFalse(status['installation_started'])
        self.assertTrue(self.staging.exists())
        self.stop.assert_called_once_with(f'focus-update-{self.operation_id}-check.service')
        for action in (
            lambda: self.controller.start_check('main', ''),
            lambda: self.controller.configure_source('https://example.com/focus.git', 'change-source'),
            lambda: self.controller.apply(self.operation_id, self.operation_id),
        ):
            with self.assertRaises(UpdateError):
                action()
        self.controller.cancel_check(self.operation_id)
        self.stop.assert_called_once()
        with self.assertRaises(UpdateError):
            self.journal.settle(self.operation_id, 'checking', state='ready')
        self.active.return_value = False
        self.assertEqual(self.controller.snapshot()['state'], 'cancelled')
        self.assertFalse(self.staging.exists())
        self.assertEqual(self.runtime.read_text(), 'keep runtime')
        self.assertEqual(self.controller.cancel_check(self.operation_id)['state'], 'cancelled')
        self.stop.assert_called_once()
        next_operation = self.controller.start_check('main', '')
        self.assertEqual(next_operation['state'], 'checking')
        self.assertNotEqual(next_operation['operation_id'], self.operation_id)
        with self.assertRaises(UpdateError):
            self.controller.cancel_check(self.operation_id)
        self.stop.assert_called_once()

    def test_cancel_wins_a_ready_race_but_cannot_cancel_an_apply(self) -> None:
        self.journal.settle(self.operation_id, 'checking', state='ready')
        self.assertEqual(self.controller.cancel_check(self.operation_id)['state'], 'cancelling')
        for state, started, unit in (
            ('applying', False, f'focus-update-{self.operation_id}-apply.service'),
            ('unknown', True, f'focus-update-{self.operation_id}-apply.service'),
            ('checking', True, f'focus-update-{self.operation_id}-check.service'),
            ('checking', False, 'unrelated.service'),
        ):
            with self.subTest(state=state, started=started, unit=unit):
                value = self.journal.read()
                value.update(state=state, installation_started=started, unit=unit)
                self.journal.write(value)
                with self.assertRaises(UpdateError):
                    self.controller.cancel_check(self.operation_id)
        self.stop.assert_called_once()

    def test_unknown_stop_outcome_keeps_admission_closed_and_can_be_retried(self) -> None:
        self.stop.side_effect = UpdateError('stop request timed out')
        self.active.return_value = None
        status = self.controller.cancel_check(self.operation_id)
        self.assertEqual(status['state'], 'cancelling')
        self.assertIn('timed out', status['error'])
        self.assertTrue(self.staging.exists())
        with self.assertRaises(UpdateError):
            self.controller.start_check('main', '')
        self.stop.side_effect = None
        self.active.return_value = False
        self.assertEqual(self.controller.cancel_check(self.operation_id)['state'], 'cancelled')
        self.assertEqual(self.stop.call_count, 2)
        self.assertFalse(self.staging.exists())

    def test_cleanup_failure_does_not_allow_a_new_check(self) -> None:
        self.active.return_value = False
        with patch.object(self.controller, '_remove_staging', side_effect=OSError('busy')):
            status = self.controller.cancel_check(self.operation_id)
        self.assertEqual(status['state'], 'cancelling')
        self.assertIn('cleanup failed', status['error'])
        with self.assertRaises(UpdateError):
            self.controller.start_check('main', '')
        self.assertEqual(self.controller.snapshot()['state'], 'cancelled')

    def test_cancellation_survives_controller_recreation(self) -> None:
        self.controller.cancel_check(self.operation_id)
        reopened = FocusUpdateController(global_data_root=self.journal.root)
        self.assertEqual(reopened.snapshot()['state'], 'cancelling')
        self.active.return_value = False
        self.assertEqual(reopened.snapshot()['state'], 'cancelled')
        self.assertFalse(self.staging.exists())


class UpdateStopCommandTests(unittest.TestCase):
    def test_inactive_unit_with_a_queued_job_is_not_stopped(self) -> None:
        for stdout, expected in (
            ('ActiveState=inactive\nJob=123\n', True),
            ('ActiveState=failed\nJob=123\n', True),
            ('ActiveState=deactivating\nJob=\n', True),
            ('ActiveState=inactive\nJob=\n', False),
            ('Job=\nActiveState=failed\n', False),
            ('ActiveState=inactive\n', None),
        ):
            with self.subTest(stdout=stdout):
                result = subprocess.CompletedProcess([], 0, stdout=stdout)
                with patch('bot.installation.update.subprocess.run', return_value=result):
                    self.assertIs(unit_active('focus-update-test-check.service'), expected)

    def test_stop_is_queued_for_the_exact_unit_without_stopping_focus_services(self) -> None:
        unit = 'focus-update-' + 'a' * 32 + '-check.service'
        with patch('bot.installation.update.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            stop_check_worker(unit)
        self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'stop', '--no-block', unit])

    def test_timeout_has_no_raw_child_output(self) -> None:
        error = subprocess.TimeoutExpired(['systemctl'], 5, stderr='private details')
        with patch('bot.installation.update.subprocess.run', side_effect=error):
            with self.assertRaisesRegex(UpdateError, 'refresh status or retry cancellation') as caught:
                stop_check_worker('focus-update-test-check.service')
        self.assertNotIn('private details', str(caught.exception))


class SystemdUpdateCancellationTests(unittest.TestCase):
    def test_cancellation_terminates_descendants_even_after_they_create_new_sessions(self) -> None:
        import os
        import shutil
        import sys
        import time

        if not sys.platform.startswith('linux') or not shutil.which('systemd-run'):
            self.skipTest('A Linux systemd user manager is required')
        manager = subprocess.run(['systemctl', '--user', 'show', '--property=Version', '--value'],
                                 capture_output=True, timeout=5, check=False)
        if manager.returncode:
            self.skipTest('The systemd user manager is unavailable')
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            script = root / 'descendants.py'
            script.write_text(
                'import os,pathlib,signal,subprocess,sys,time\n'
                'root = pathlib.Path(sys.argv[1]); depth = int(sys.argv[2])\n'
                'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                'if depth: subprocess.Popen([sys.executable,"-I",__file__,str(root),str(depth-1)], start_new_session=True)\n'
                '(root / ("pid-" + str(depth))).write_text(str(os.getpid()))\n'
                'while True: time.sleep(1)\n'
            )
            controller = FocusUpdateController(global_data_root=root / '_global')
            units = []

            def launch(journal, operation_id, mode):
                unit = journal.read()['unit']
                units.append(unit)
                subprocess.run([
                    'systemd-run', '--user', '--no-block', '--collect', '--unit', unit,
                    '--property=Type=oneshot', '--property=KillMode=control-group',
                    '--property=TimeoutStopSec=1s', '--', sys.executable, '-I', str(script), str(root), '2',
                ], capture_output=True, timeout=5, check=True)

            def running(pid):
                try:
                    return pathlib.Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] not in {'Z', 'X'}
                except FileNotFoundError:
                    return False

            try:
                with patch('bot.installation.update.unavailable_reason', return_value=''):
                    with patch('bot.installation.update.launch_worker', side_effect=launch):
                        operation = controller.start_check('stable', '')
                    deadline = time.monotonic() + 10
                    while not (root / 'pid-0').exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    pids = [int((root / f'pid-{depth}').read_text()) for depth in range(3)]
                    self.assertTrue(all(running(pid) for pid in pids))
                    self.assertEqual(os.getsid(pids[0]), pids[0])
                    self.assertEqual(os.getsid(pids[1]), pids[1])
                    staging = controller.journal.directory(operation['operation_id'])
                    staging.mkdir(parents=True)
                    (staging / 'partial').write_text('discard')
                    status = controller.cancel_check(operation['operation_id'])
                    deadline = time.monotonic() + 15
                    while status['state'] == 'cancelling' and time.monotonic() < deadline:
                        time.sleep(0.1)
                        status = controller.snapshot()
                    self.assertEqual(status['state'], 'cancelled', status)
                    self.assertTrue(all(not running(pid) for pid in pids))
                    self.assertFalse(staging.exists())
            finally:
                for unit in units:
                    subprocess.run(['systemctl', '--user', 'stop', unit], capture_output=True, timeout=10, check=False)
