"""Explicit predecoder setup is isolated, pinned, and never auto-runs npm."""
import hashlib
from importlib import resources
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from simscene.preparation import toolchain_setup
from simscene.preparation.glb_convert import PREDECODER
from simscene.preparation.profiles import PreparationError


class PredecoderSetupTest(unittest.TestCase):
    def which(self, name):
        return '/fixture/bin/' + name

    def npm_success(self, args, **kwargs):
        if args[1:] == ['--version']:
            return subprocess.CompletedProcess(args, 0, stdout=PREDECODER['node_version'] + '\n')
        self.assertEqual(args[1], 'ci')
        for flag in ('--ignore-scripts', '--no-audit', '--no-fund'):
            self.assertIn(flag, args)
        destination = Path(kwargs['cwd'])
        self.assertEqual(args[args.index('--prefix') + 1], str(destination))
        self.assertTrue((destination / 'package-lock.json').is_file())
        self.assertEqual(hashlib.sha256((destination / 'package-lock.json').read_bytes()).hexdigest(), PREDECODER['package_lock_sha256'])
        self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['stderr'], subprocess.STDOUT)
        self.assertLessEqual(kwargs['timeout'], 600)
        (destination / 'node_modules').mkdir()
        (destination / 'node_modules/fixture').write_text('mock installer only')
        kwargs['stdout'].write('mock npm installed pinned packages\n')
        return subprocess.CompletedProcess(args, 0)

    def test_shipped_files_match_verified_lock_and_mirrors(self):
        package, lock = toolchain_setup._resources()
        self.assertEqual(hashlib.sha256(lock).hexdigest(), PREDECODER['package_lock_sha256'])
        self.assertEqual(json.loads(lock)['name'], 'converter-tools')
        self.assertEqual(json.loads(package)['dependencies']['meshoptimizer'], '1.3.0')
        rows = json.loads(lock)['packages']
        self.assertTrue(all(row['resolved'].startswith('https://registry.npmmirror.com/') and row['integrity'].startswith('sha512-')
                            for name, row in rows.items() if name))
        self.assertEqual(package, resources.files('simscene.preparation').joinpath('data/package.json').read_bytes())

    def test_explicit_success_from_another_cwd_verifies_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'new-decoder'
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(toolchain_setup.shutil, 'which', side_effect=self.which), patch.object(toolchain_setup.subprocess, 'run', side_effect=self.npm_success) as run, patch.object(toolchain_setup, 'predecoder_fingerprint', return_value=dict(PREDECODER, prefix=str(destination))) as verify:
                    result = toolchain_setup.setup_predecoder(destination)
            finally:
                os.chdir(previous)
            self.assertEqual(result['status'], 'ready')
            verify.assert_called_once_with(destination)
            self.assertEqual(run.call_count, 2)
            record = json.loads((destination / 'setup-result.json').read_text())
            self.assertEqual(record, result)
            self.assertIn('mock npm installed', (destination / 'install.log').read_text())
            self.assertEqual((destination / 'package-lock.json').read_bytes(), toolchain_setup._resources()[1])

    def test_wrong_node_version_retains_failure_without_running_npm(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'decoder'
            with patch.object(toolchain_setup.shutil, 'which', side_effect=self.which), patch.object(toolchain_setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='v20.0.0\n')) as run:
                with self.assertRaises(PreparationError) as raised:
                    toolchain_setup.setup_predecoder(destination)
            self.assertEqual(raised.exception.code, 'plan_environment_changed')
            self.assertEqual(run.call_count, 1)
            record = json.loads((destination / 'setup-result.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertNotIn('fingerprint', record)
            self.assertTrue((destination / 'install.log').is_file())
            self.assertFalse((destination / 'node_modules').exists())

    def test_missing_tools_fail_without_installing_or_claiming_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'decoder'
            with patch.object(toolchain_setup.shutil, 'which', return_value=None), patch.object(toolchain_setup.subprocess, 'run') as run:
                with self.assertRaises(PreparationError) as raised:
                    toolchain_setup.setup_predecoder(destination)
            self.assertEqual(raised.exception.code, 'dependency_missing')
            run.assert_not_called()
            self.assertEqual(json.loads((destination / 'setup-result.json').read_text())['status'], 'failed')

    def test_failed_npm_keeps_partial_install_and_log_and_refuses_retry_in_place(self):
        def fail(args, **kwargs):
            if args[1:] == ['--version']:
                return subprocess.CompletedProcess(args, 0, stdout=PREDECODER['node_version'])
            destination = Path(kwargs['cwd'])
            (destination / 'node_modules').mkdir()
            (destination / 'node_modules/partial').write_text('retain failed artifact')
            kwargs['stdout'].write('fixture npm failure\n')
            raise subprocess.CalledProcessError(1, args)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'decoder'
            with patch.object(toolchain_setup.shutil, 'which', side_effect=self.which), patch.object(toolchain_setup.subprocess, 'run', side_effect=fail):
                with self.assertRaises(PreparationError) as raised:
                    toolchain_setup.setup_predecoder(destination)
            self.assertEqual(raised.exception.log_path, str(destination / 'install.log'))
            self.assertTrue((destination / 'node_modules/partial').is_file())
            self.assertEqual(json.loads((destination / 'setup-result.json').read_text())['status'], 'failed')
            old_log = (destination / 'install.log').read_bytes()
            with self.assertRaisesRegex(ValueError, 'new or empty'):
                toolchain_setup.setup_predecoder(destination)
            self.assertEqual((destination / 'install.log').read_bytes(), old_log)

    def test_timeout_and_failed_final_fingerprint_never_leave_ready_result(self):
        def timeout(args, **kwargs):
            if args[1:] == ['--version']:
                return subprocess.CompletedProcess(args, 0, stdout=PREDECODER['node_version'])
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        with tempfile.TemporaryDirectory() as directory:
            for name, runner, verifier, expected in (
                ('timeout', timeout, None, 'setup_timeout'),
                ('bad-fingerprint', self.npm_success, PreparationError('plan_environment_changed', 'fixture tree differs'), 'plan_environment_changed')):
                destination = Path(directory) / name
                with self.subTest(name=name), patch.object(toolchain_setup.shutil, 'which', side_effect=self.which), patch.object(toolchain_setup.subprocess, 'run', side_effect=runner), patch.object(toolchain_setup, 'predecoder_fingerprint', side_effect=verifier):
                    with self.assertRaises(PreparationError) as raised:
                        toolchain_setup.setup_predecoder(destination, timeout_seconds=1)
                self.assertEqual(raised.exception.code, expected)
                record = json.loads((destination / 'setup-result.json').read_text())
                self.assertEqual(record['status'], 'failed')
                self.assertNotIn('fingerprint', record)

    def test_npm_cannot_rewrite_the_verified_lock_and_still_be_ready(self):
        def mutate(args, **kwargs):
            result = self.npm_success(args, **kwargs)
            if args[1:] != ['--version']:
                path = Path(kwargs['cwd']) / 'package-lock.json'
                path.write_text(path.read_text() + '\n')
            return result
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'decoder'
            with patch.object(toolchain_setup.shutil, 'which', side_effect=self.which), patch.object(toolchain_setup.subprocess, 'run', side_effect=mutate), patch.object(toolchain_setup, 'predecoder_fingerprint') as verify:
                with self.assertRaises(PreparationError) as raised:
                    toolchain_setup.setup_predecoder(destination)
            self.assertEqual(raised.exception.code, 'verification_failed')
            verify.assert_not_called()
            self.assertEqual(json.loads((destination / 'setup-result.json').read_text())['status'], 'failed')

    def test_nonempty_nonowned_writable_and_symlink_prefixes_are_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / 'existing'; existing.mkdir(); (existing / 'keep').write_text('safe')
            with self.assertRaises(ValueError):
                toolchain_setup.setup_predecoder(existing)
            self.assertEqual((existing / 'keep').read_text(), 'safe')
            empty = root / 'empty'; empty.mkdir()
            with patch.object(toolchain_setup.os, 'geteuid', return_value=os.geteuid() + 1), self.assertRaisesRegex(ValueError, 'owned'):
                toolchain_setup.setup_predecoder(empty)
            self.assertEqual(list(empty.iterdir()), [])
            empty.chmod(0o777)
            with self.assertRaisesRegex(ValueError, 'writable'):
                toolchain_setup.setup_predecoder(empty)
            empty.chmod(0o700)
            linked = root / 'link'; linked.symlink_to(empty, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                toolchain_setup.setup_predecoder(linked)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                toolchain_setup.setup_predecoder(linked / 'nested')
            self.assertEqual(list(empty.iterdir()), [])

    def test_import_and_invalid_timeout_never_install(self):
        with patch.object(toolchain_setup.subprocess, 'run') as run:
            importlib.reload(toolchain_setup)
            run.assert_not_called()
            for timeout in (0, -1, True, 601, float('nan')):
                with self.assertRaises(ValueError):
                    toolchain_setup.setup_predecoder('/not-created', timeout_seconds=timeout)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
