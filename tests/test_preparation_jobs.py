"""Durable preparation reservations and checkpoint truthfulness without SDK apps."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from simscene.acquisition.plans import make_plan
from simscene.acquisition.locks import copy_acquired_to_job
from simscene.preparation import jobs, worker
from simscene.preparation.profiles import preparation_key, source_identity
from simscene.scene import SceneError
from test_asset_plans import config_fixture, runtime_fixture, record_fixture, PARAMETERS


class PreparationJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.config = config_fixture(self.root); self.runtime = runtime_fixture(); self.record = record_fixture()
        self.plan = make_plan(self.record.ref, parameters=PARAMETERS, record=self.record, runtime=self.runtime, config=self.config)
        self.plan.pop('plan_ref')

    def tearDown(self):
        self.temp.cleanup()

    def snapshot_stub(self, source, destination, **kwargs):
        Path(destination).mkdir(parents=True)
        (Path(destination) / '__init__.py').write_text('# frozen fixture runtime\n')

    def start(self, request='request1', plan_id=None):
        with patch('simscene.preparation.jobs.subprocess.Popen', return_value=SimpleNamespace(pid=123456)) as process, patch('simscene.preparation.jobs._identity', return_value='start-token'), patch('simscene.preparation.jobs.shutil.copytree', side_effect=self.snapshot_stub):
            receipt = jobs.start(plan_id or self.plan['plan_id'], request, config=self.config)
        return receipt, process

    def job_root(self, receipt):
        return jobs.directory(receipt['job_id'], config=self.config)

    def test_persistent_replay_after_reload_includes_failed_jobs(self):
        receipt, launched = self.start(); launched.assert_called_once()
        root = self.job_root(receipt)
        frozen_plan = json.loads((root / 'plan.json').read_text())
        self.assertEqual(frozen_plan, self.plan)
        record = json.loads((root / 'job.json').read_text())
        record.update(state='failed', error_code='unsupported_codec', error='fixture decoder unavailable')
        jobs.write(root / 'job.json', record)
        reloaded = importlib.reload(jobs)
        with patch('subprocess.Popen', side_effect=AssertionError('must not relaunch')) as launch:
            replay = reloaded.start(self.plan['plan_id'], 'request1', config=self.config)
            status = reloaded.status(replay['job_id'], config=self.config)
        launch.assert_not_called()
        self.assertEqual(receipt['job_id'], replay['job_id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['error_code'], 'unsupported_codec')

    def test_same_request_changed_plan_conflicts_without_second_launch(self):
        self.start()
        second = make_plan(self.record.ref, parameters=dict(PARAMETERS, proxy_tolerance_m=.005), record=self.record, runtime=self.runtime, config=self.config)
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')) as process:
            with self.assertRaisesRegex(SceneError, 'different job parameters'):
                jobs.start(second['plan_id'], 'request1', config=self.config)
        process.assert_not_called()
        self.assertEqual(len(list((Path(self.config['home']) / 'preparation_jobs').glob('prep-*'))), 1)

    def test_corrupt_launch_reservation_does_not_become_proof_of_no_launch(self):
        receipt,_=self.start('interrupted-record')
        request_file=Path(self.config['home'])/'job-requests/interrupted-record.json'
        request=json.loads(request_file.read_text());request['state']='starting';request.pop('result')
        jobs.write(request_file,request)
        (self.job_root(receipt)/'job.json').write_text('{incomplete')
        with patch('subprocess.Popen',side_effect=AssertionError('must not relaunch')) as process:
            with self.assertRaisesRegex(SceneError,'uncertain'):
                jobs.start(self.plan['plan_id'],'interrupted-record',config=self.config)
        process.assert_not_called()

    def test_missing_launch_record_after_interruption_never_restarts(self):
        receipt,_=self.start('missing-record')
        request_file=Path(self.config['home'])/'job-requests/missing-record.json'
        request=json.loads(request_file.read_text());request['state']='starting';request.pop('result')
        jobs.write(request_file,request)
        (self.job_root(receipt)/'job.json').unlink()
        with patch('subprocess.Popen',side_effect=AssertionError('must not relaunch')) as process:
            with self.assertRaisesRegex(SceneError,'uncertain'):
                jobs.start(self.plan['plan_id'],'missing-record',config=self.config)
        process.assert_not_called()

    def test_uncertain_launch_reservation_is_recovered_never_relaunched(self):
        with patch('simscene.preparation.jobs.subprocess.Popen', side_effect=OSError('uncertain process launch')), patch('simscene.preparation.jobs.shutil.copytree', side_effect=self.snapshot_stub):
            with self.assertRaisesRegex(OSError, 'uncertain process launch'):
                jobs.start(self.plan['plan_id'], 'uncertain1', config=self.config)
        reloaded = importlib.reload(jobs)
        with patch('subprocess.Popen', side_effect=AssertionError('must not relaunch')) as process:
            replay = reloaded.start(self.plan['plan_id'], 'uncertain1', config=self.config)
            result = reloaded.status(replay['job_id'], config=self.config)
        process.assert_not_called()
        self.assertTrue(replay['replayed'])
        self.assertEqual(result['state'], 'uncertain')
        self.assertEqual(result['error_code'], 'interrupted_job')
        self.assertFalse((self.job_root(replay) / 'launch.json').exists())

    def test_dead_worker_status_is_uncertain_not_failed_or_restarted(self):
        receipt, _ = self.start()
        with patch('simscene.preparation.jobs._identity', return_value=None), patch('subprocess.Popen', side_effect=AssertionError('must not restart')) as process:
            status = jobs.status(receipt['job_id'], config=self.config)
            cancelled = jobs.cancel(receipt['job_id'], config=self.config)
        process.assert_not_called()
        self.assertEqual(status['state'], 'uncertain')
        self.assertEqual(cancelled['state'], 'uncertain')
        # An uncertain launch can still have a detached worker. A cooperative
        # marker is safe, but must never imply confirmed cancellation.
        self.assertTrue((self.job_root(receipt) / 'cancel-request.json').exists())
        self.assertEqual(json.loads((self.job_root(receipt) / 'job.json').read_text())['state'], 'queued')

    def test_cancel_request_is_not_completion_until_checkpoint(self):
        receipt, _ = self.start(); root = self.job_root(receipt)
        with patch('simscene.preparation.jobs._identity', return_value='start-token'):
            result = jobs.cancel(receipt['job_id'], config=self.config)
        self.assertEqual(result['state'], 'queued')
        self.assertTrue(result['cancel_requested'])
        self.assertEqual(json.loads((root / 'job.json').read_text())['state'], 'queued')
        with patch('simscene.preparation.environment.current_runtime', return_value=self.runtime), patch('simscene.acquisition.dispatch.acquire_selected', side_effect=AssertionError('must cancel before fetch')) as acquire, patch('simscene.preparation.worker.run_sdk', side_effect=AssertionError('must cancel before SDK')) as sdk:
            worker.execute(root)
        acquire.assert_not_called(); sdk.assert_not_called()
        status = jobs.status(receipt['job_id'], config=self.config)
        self.assertEqual(status['state'], 'cancelled')
        self.assertEqual(status['error_code'], 'cancelled')

    def test_converter_cancel_waits_for_process_termination_confirmation(self):
        root = self.root / 'sdk-job'; root.mkdir()
        jobs.write(root / 'cancel-request.json', {'requested': True})
        process = SimpleNamespace(pid=123456, poll=lambda: None, wait=Mock(return_value=-signal.SIGTERM))
        def confirmed_exit(pid, sig):
            if sig == 0: raise ProcessLookupError('fixture process group exited')
        with patch('simscene.settings.get', return_value='/fake/sdk/python.sh'), patch('simscene.preparation.worker.subprocess.Popen', return_value=process), patch('simscene.preparation.worker.os.killpg', side_effect=confirmed_exit) as kill:
            with self.assertRaises(worker.Cancelled):
                worker.run_sdk(root, {'output': str(root / 'never-created.json')}, self.config)
        self.assertEqual(kill.call_args_list[0].args, (123456, signal.SIGTERM))
        self.assertFalse(any(call.args[1] == signal.SIGKILL for call in kill.call_args_list))
        process.wait.assert_called_once()
        self.assertFalse((root / 'never-created.json').exists())

    def test_unconfirmed_converter_termination_is_not_reported_cancelled(self):
        process = SimpleNamespace(pid=123456, poll=lambda: None, wait=Mock(return_value=0))
        clock = iter(range(0, 200, 20))
        with patch('simscene.preparation.worker.os.killpg') as kill, patch('simscene.preparation.worker.time.monotonic', side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(RuntimeError, 'cancellation_unconfirmed'):
                worker.terminate_group(process)
        self.assertIn((123456, signal.SIGTERM), [call.args for call in kill.call_args_list])
        self.assertIn((123456, signal.SIGKILL), [call.args for call in kill.call_args_list])
        process.wait.assert_called_once()
        receipt, _ = self.start(); root = self.job_root(receipt)
        acquired = self.source_package()
        with patch('simscene.preparation.environment.current_runtime', return_value=self.runtime), patch('simscene.acquisition.dispatch.acquire_selected', return_value=acquired), patch('simscene.preparation.worker.run_sdk', side_effect=RuntimeError('cancellation_unconfirmed: process group persists')):
            worker.execute(root)
        result = jobs.status(receipt['job_id'], config=self.config)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error_code'], 'cancellation_unconfirmed')

    def test_environment_change_fails_before_source_acquisition(self):
        receipt, _ = self.start(); root = self.job_root(receipt)
        changed = copy.deepcopy(self.runtime); changed['target']['isaac_version'] = 'new-runtime'
        with patch('simscene.preparation.environment.current_runtime', return_value=changed), patch('simscene.acquisition.dispatch.acquire_selected', side_effect=AssertionError('must not fetch changed environment')) as acquire, patch('simscene.preparation.worker.run_sdk', side_effect=AssertionError('must not run changed environment')) as sdk:
            worker.execute(root)
        acquire.assert_not_called(); sdk.assert_not_called()
        result = jobs.status(receipt['job_id'], config=self.config)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error_code'], 'plan_environment_changed')

    def test_blocked_plan_and_failed_transfer_never_launch_converter(self):
        blocked = make_plan(self.record.ref, parameters=PARAMETERS, record=record_fixture(license=None), runtime=self.runtime, config=self.config)
        with patch('subprocess.Popen', side_effect=AssertionError('blocked plan cannot launch')) as process:
            with self.assertRaisesRegex(ValueError, 'plan_not_ready'):
                jobs.start(blocked['plan_id'], 'blocked-request', config=self.config)
        process.assert_not_called()
        receipt, _ = self.start(); root = self.job_root(receipt)
        error = ValueError('download_failed: fixture interrupted payload')
        error.actual_download_bytes = 37
        error.transfer_ledger = [{'category': 'payload', 'status': 'failed', 'bytes': 37}]
        with patch('simscene.preparation.environment.current_runtime', return_value=self.runtime), patch('simscene.acquisition.dispatch.acquire_selected', side_effect=error), patch('simscene.preparation.worker.run_sdk', side_effect=AssertionError('failed transfer cannot convert')) as sdk:
            worker.execute(root)
        sdk.assert_not_called()
        status = jobs.status(receipt['job_id'], config=self.config)
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['actual_download_bytes'], 37)
        self.assertEqual(json.loads((root / 'job.json').read_text())['transfer_ledger'], error.transfer_ledger)

    def source_package(self):
        cache = Path(self.config['asset_cache_directory']); package = cache / ('c' * 64); package.mkdir(parents=True)
        source = package / 'source.usda'; source.write_text('#usda 1.0\ndef Xform "Source" {}\n')
        files = [{'path': 'source.usda', 'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'url': self.record.ref.asset_id}]
        manifest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        acquired = {'schema_version': 1, 'source_ref': self.plan['asset_ref'], 'license': self.plan['license_decision'], 'provenance': self.plan['source_snapshot']['provenance'], 'asset_handle': 'acquired:sha256:' + package.name, 'source': self.record.ref.asset_id, 'package_sha256': package.name, 'manifest_sha256': manifest, 'root': str(source), 'files': files, 'dependency_status': 'resolved_locally', 'actual_download_bytes': 0}
        jobs.write(package / 'simscene-lock.json', acquired)
        source.chmod(0o444)
        return acquired

    def test_private_job_copy_is_independent_from_readonly_source_cache(self):
        acquired = self.source_package(); source = Path(acquired['root']); original = source.read_bytes()
        copied = copy_acquired_to_job(acquired, self.config['asset_cache_directory'], self.root / 'job-input', staging_budget_bytes=1024**2)
        private = Path(copied['root'])
        self.assertNotEqual(private.stat().st_ino, source.stat().st_ino)
        private.write_text('# changed private input\n')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(source.stat().st_mode & 0o222, 0)
        self.assertFalse(list(self.root.glob('.job-input-*')))

    def test_worker_publishes_derived_package_and_reuses_it_without_sdk_or_source_changes(self):
        acquired = self.source_package(); source = Path(acquired['root']); original = source.read_bytes()
        calls = []
        def acquire(plan, *, config, job_directory):
            return copy_acquired_to_job(acquired, config['asset_cache_directory'], job_directory / 'source', staging_budget_bytes=1024**2)
        def sdk(root, task, config):
            calls.append(task)
            private = Path(task['acquired']['root'])
            self.assertNotEqual(private, source)
            self.assertEqual(private.read_bytes(), original)
            output = Path(task['output_directory']); output.mkdir()
            main = output / 'main.usda'; main.write_text('#usda 1.0\ndef Xform "Asset" {}\n')
            files = [{'path': f['path'], 'sha256': f['sha256'], 'size_bytes': f['size']} for f in acquired['files']]
            closure = hashlib.sha256(json.dumps(sorted(files, key=lambda f: f['path']), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            key = preparation_key(source_identity(task['acquired'], closure), self.plan['profile_id'], self.plan['parameters'], self.plan['target'], {'backend': 'openusd', 'version': self.plan['target']['usd_version']})
            manifest = {'schema_version': 1, 'schema': 'simscene.prepared_asset.v1', 'prepared_id': key, 'profile_id': self.plan['profile_id'], 'main': 'main.usda', 'default_prim': '/Asset', 'body_map': {}, 'bounds': {'min': [-1, -1, -1], 'max': [1, 1, 1]}, 'runtime_validation': {'status': 'not_run'}, 'files': [{'path': 'main.usda', 'size_bytes': main.stat().st_size, 'sha256': hashlib.sha256(main.read_bytes()).hexdigest()}]}
            manifest.update(profile_version=1,parameters=self.plan['parameters'], source_ref=task['acquired'].get('source_ref'),
                            source_manifest_sha256=task['acquired']['manifest_sha256'],
                            license=task['acquired'].get('license'), provenance=task['acquired'].get('provenance'),
                            target=self.plan['target'], toolchain={'backend': 'openusd', 'version': self.plan['target']['usd_version']},
                            source_closure_sha256=closure)
            jobs.write(output / 'manifest.json', manifest)
            return {'prepared_id': key}
        receipts = []
        with patch('simscene.preparation.environment.current_runtime', return_value=self.runtime), patch('simscene.acquisition.dispatch.acquire_selected', side_effect=acquire), patch('simscene.preparation.worker.run_sdk', side_effect=sdk), patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            for request in ('first-prepare', 'second-prepare'):
                receipt, _ = self.start(request); receipts.append(receipt)
                worker.execute(self.job_root(receipt))
        first, second = [jobs.status(r['job_id'], config=self.config) for r in receipts]
        self.assertEqual(first['state'], 'completed', first)
        self.assertEqual(second['state'], 'completed', second)
        self.assertEqual(len(calls), 1)
        self.assertFalse(first['result']['cache_hit']); self.assertTrue(second['result']['cache_hit'])
        self.assertEqual(first['result']['prepared_handle'], second['result']['prepared_handle'])
        self.assertEqual(first['result']['runtime_validation']['status'], 'not_run')
        self.assertEqual(source.read_bytes(), original)
        for receipt in receipts:
            self.assertEqual((self.job_root(receipt) / 'source' / 'source.usda').read_bytes(), original)
        self.assertEqual(len(list(Path(self.config['prepared_directory']).glob('[0-9a-f]' * 64))), 1)
        reloaded = importlib.reload(jobs)
        with patch('subprocess.Popen', side_effect=AssertionError('completed job cannot relaunch')) as process:
            replay = reloaded.start(self.plan['plan_id'], 'first-prepare', config=self.config)
        process.assert_not_called()
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['job_id'], receipts[0]['job_id'])
        self.assertEqual(reloaded.status(replay['job_id'], config=self.config)['state'], 'completed')


if __name__ == '__main__': unittest.main()
