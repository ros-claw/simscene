"""Runtime integrity and process-tree behavior for the optional SDK backend."""
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from simscene.generation import usdcraft_backend_worker as worker
from simscene.generation import usdcraft_sdk


class USDCraftRuntimeIntegrityTests(unittest.TestCase):
    def test_structural_validation_precedes_dependency_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {'operation': 'generate', 'recipe_id': usdcraft_sdk.RECIPE,
                    'parameters': {'length_m': .5, 'width_m': .18, 'thickness_m': .015},
                    'expected_runtime': {}, 'template_sha256': 'a' * 64,
                    'output': str(root / 'source.usda'), 'runtime_output': str(root / 'backend-runtime.json'),
                    'report_output': str(root / 'sdk-report.json')}
            with patch.object(worker, 'parameters', side_effect=AssertionError('loaded before bootstrap')):
                worker.validate_task(task, root, normalize=False)

    def test_git_blob_verification_rejects_hidden_tracked_change_and_ignored_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            git('init', '-q')
            git('config', 'user.email', 'fixture@example.invalid')
            git('config', 'user.name', 'Fixture')
            for name in ['sdk/__init__.py', 'sdk/model.template', 'usdcraft/__init__.py',
                         'storage/__init__.py', 'storage/artifact_contract.py']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# committed fixture\n')
            (root / '.gitignore').write_text('sdk/ignored_shadow.py\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            commit = git('rev-parse', 'HEAD')
            baseline = worker._verify_checkout(root, commit)
            self.assertTrue(baseline)
            git('update-index', '--assume-unchanged', 'storage/artifact_contract.py')
            (root / 'storage/artifact_contract.py').write_text('# tampered, not executed\n')
            self.assertEqual(git('status', '--porcelain=v1'), '')
            with self.assertRaisesRegex(ValueError, 'blob|commit'):
                worker._verify_checkout(root, commit)
            (root / 'storage/artifact_contract.py').write_text('# committed fixture\n')
            git('update-index', '--no-assume-unchanged', 'storage/artifact_contract.py')
            (root / 'sdk/ignored_shadow.py').write_text('# ignored, not executed\n')
            self.assertEqual(git('status', '--porcelain=v1'), '')
            with self.assertRaisesRegex(ValueError, 'untracked|unexpected|shadow'):
                worker._verify_checkout(root, commit)

    def test_top_level_sdk_origins_cannot_be_shadowed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root = base / 'checkout'; shadow = base / 'shadow'
            for package in ['sdk', 'usdcraft', 'storage', 'viewer']:
                (root / package).mkdir(parents=True)
                (root / package / '__init__.py').write_text('')
            (shadow / 'storage').mkdir(parents=True)
            (shadow / 'storage' / '__init__.py').write_text('')
            worker._verify_import_origins(root, [str(root)])
            with self.assertRaisesRegex(ValueError, 'origin|shadow'):
                worker._verify_import_origins(root, [str(shadow), str(root)])

    def test_probe_never_executes_pth_startup_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); venv = root / 'venv'; marker = root / 'executed'
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(venv)], check=True)
            site = next((venv / 'lib').glob('python*/site-packages'))
            (site / 'untrusted.pth').write_text('import pathlib; pathlib.Path(' + repr(str(marker)) + ').write_text("ran")\n')
            output = root / 'probe'; output.mkdir()
            # The empty venv must fail the SDK probe, without executing the .pth.
            with self.assertRaises(subprocess.CalledProcessError):
                usdcraft_sdk._run({'operation': 'probe', 'output': str(output / 'observed.json')}, venv / 'bin/python', output)
            self.assertFalse(marker.exists())

    def test_checkout_bytecode_cache_cannot_override_verified_python_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); package = root / 'sdk'; package.mkdir()
            marker = root / 'forged-cache-ran'; source = package / '__init__.py'
            malicious = 'from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("forged")\n'
            safe = '# harmless verified source'.ljust(len(malicious) - 1) + '\n'
            timestamp = int(time.time()) - 10
            source.write_text(malicious); os.utime(source, (timestamp, timestamp))
            py_compile.compile(str(source), doraise=True)
            source.write_text(safe); os.utime(source, (timestamp, timestamp))
            # Establish that the forged, timestamp-valid cache would execute.
            env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1')
            env.pop('PYTHONPYCACHEPREFIX', None)
            subprocess.run([sys.executable, '-S', '-c', 'import sdk'], env=env, cwd=root, check=True)
            self.assertTrue(marker.exists())
            marker.unlink()
            output = root / 'output'; output.mkdir(); launcher = root / 'launcher'
            launcher.write_text('#!/usr/bin/python3\nimport sys\nsys.path.insert(0, ' + repr(str(root)) + ')\nimport sdk\n')
            launcher.chmod(0o755)
            usdcraft_sdk._run({'operation': 'probe', 'output': str(output / 'observed.json')}, launcher, output)
            self.assertFalse(marker.exists())

    def test_timeout_and_cancel_kill_sdk_descendants_before_they_write(self):
        for mode in ('timeout', 'cancel'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); output = root / 'output'; output.mkdir()
                marker = root / 'late-marker'; ready = root / 'child-started'; child = root / 'child.py'; launcher = root / 'launcher'
                child.write_text('import time\nfrom pathlib import Path\nPath(' + repr(str(ready)) + ').write_text("ready")\ntime.sleep(1.5)\nPath(' + repr(str(marker)) + ').write_text("late")\n')
                launcher.write_text('#!/usr/bin/python3\nimport subprocess, time\nsubprocess.Popen(["/usr/bin/python3", ' + repr(str(child)) + '])\ntime.sleep(30)\n')
                launcher.chmod(0o755)
                timer = None
                if mode == 'cancel':
                    timer = threading.Timer(.5, lambda: (root / 'cancel-request.json').write_text('{}'))
                    timer.start()
                try:
                    with patch.object(usdcraft_sdk, 'SDK_TIMEOUT_SECONDS', 1.0):
                        expected = subprocess.TimeoutExpired if mode == 'timeout' else usdcraft_sdk.GenerationCancelled
                        with self.assertRaises(expected):
                            usdcraft_sdk._run({'operation': 'generate'}, launcher, output)
                finally:
                    if timer:
                        timer.join()
                self.assertTrue(ready.exists(), 'the descendant must have actually started')
                time.sleep(1.7)
                self.assertFalse(marker.exists(), 'a descendant survived cancellation or timeout')

    def test_supervisor_records_sdk_cancellation_as_cancelled(self):
        import json
        from simscene.generation import worker as supervisor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'job.json').write_text(json.dumps({'job_id': 'gen-' + 'a' * 32, 'state': 'queued'}))
            (root / 'config.json').write_text('{}')
            (root / 'task.json').write_text(json.dumps({'recipe_id': usdcraft_sdk.RECIPE, 'parameters': {}, 'runtime': {}}))
            with patch('simscene.__file__', str(root / 'runtime' / 'simscene' / '__init__.py')), \
                    patch.object(usdcraft_sdk, 'generate_asset', side_effect=usdcraft_sdk.GenerationCancelled('cancelled')):
                supervisor.execute(root)
            self.assertEqual(json.loads((root / 'job.json').read_text())['state'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
