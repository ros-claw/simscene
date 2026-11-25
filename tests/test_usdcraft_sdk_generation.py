"""Trusted USDCraft template selection, durable dispatch and immutable sources."""
import json
import hashlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simscene.generation import jobs

COMMIT = '46fec187bdce40845c30863a56143047edc4a263'
RECIPE = 'usdcraft_sdk_guide_plate_v1'


class USDCraftSDKGenerationTests(unittest.TestCase):
    def test_explicit_sdk_recipe_uses_its_own_runtime_and_replays_durable_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = {'schema_version': 1, 'backend': 'usdcraft_sdk', 'python': '/isolated/sdk-python',
                       'reviewed_commit': COMMIT,
                       'observed': {'usdcraft_commit': COMMIT, 'usdcraft_version': '1.0.0', 'source_clean': True}}
            manifest = root / 'sdk-runtime.json'
            manifest.write_text(json.dumps(runtime))
            config = {'home': str(root / 'state'), 'index_directory': str(root / 'index'),
                      'usdcraft_generation_runtime': str(manifest)}
            with patch('simscene.generation.jobs.subprocess.Popen') as launch, \
                    patch('simscene.jobs._process_identity', return_value={'start_ticks': 123}):
                launch.return_value.pid = 999
                first = jobs.start(RECIPE, {'length_m': .6}, 'sdk-request', config=config)
                second = jobs.start(RECIPE, {'length_m': .6}, 'sdk-request', config=config)
                self.assertEqual(first['job_id'], second['job_id'])
                self.assertTrue(second['replayed'])
                self.assertEqual(launch.call_count, 1)
                task = json.loads((jobs.directory(first['job_id'], config=config) / 'task.json').read_text())
                self.assertEqual(task['recipe_id'], RECIPE)
                self.assertEqual(task['runtime']['backend'], 'usdcraft_sdk')
                self.assertEqual(task['parameters'], {'length_m': .6, 'width_m': .18, 'thickness_m': .015})

    def test_generated_sdk_source_is_pinned_and_uses_ordinary_plan_and_acquisition(self):
        from simscene.generation import usdcraft_sdk
        from simscene.catalog.models import AssetRef
        from simscene.catalog.store import CatalogStore
        from simscene.acquisition.plans import make_plan
        from simscene.acquisition.dispatch import acquire_selected
        from test_asset_plans import config_fixture, runtime_fixture
        self.assertTrue(callable(getattr(usdcraft_sdk, 'generate_asset', None)), 'SDK generator missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = config_fixture(directory)
            runtime = {'schema_version': 1, 'backend': 'usdcraft_sdk', 'python': '/isolated/sdk-python',
                       'reviewed_commit': COMMIT,
                       'observed': {'usdcraft_commit': COMMIT, 'usdcraft_version': '1.0.0', 'source_clean': True}}
            def backend(task, python, folder):
                self.assertEqual(task['recipe_id'], RECIPE)
                self.assertEqual(task['parameters']['length_m'], .6)
                Path(task['output']).write_text('#usda 1.0\n')
                Path(task['runtime_output']).write_text(json.dumps(runtime['observed']))
                Path(task['report_output']).write_text(json.dumps({'check': 'passed', 'compile': 'passed', 'closure': 'resolved_locally'}))
            with patch('simscene.generation.usdcraft_sdk._run', side_effect=backend):
                result = usdcraft_sdk.generate_asset(RECIPE, {'length_m': .6}, runtime,
                                                     output_directory=root / 'job-output', config=config)
            record = CatalogStore(config['index_directory']).get(AssetRef.from_dict(result['asset_ref']))
            self.assertEqual(record.ref.source_id, 'local-usdcraft-sdk')
            self.assertEqual(record.license['license'], 'Apache-2.0')
            self.assertEqual(record.provenance['generator'], 'usdcraft_sdk')
            self.assertEqual(record.provenance['identity']['toolchain']['reviewed_commit'], COMMIT)
            self.assertEqual(record.provenance['identity']['parameters']['length_m'], .6)
            self.assertEqual(len(record.provenance['identity']['template_sha256']), 64)
            self.assertEqual(result['physics_status'], 'not_prepared')
            self.assertEqual(record.availability['acquisition']['kind'], 'generated_package')
            plan = make_plan(record.ref, 'visual_prop_v1', {'source_physics_policy': 'replace_visual_only', 'proxy_tolerance_m': .002},
                             record=record, runtime=runtime_fixture(), config=config)
            self.assertTrue(plan['ready_to_fetch'], plan['blocking_reasons'])
            acquired = acquire_selected(plan, config=config)
            self.assertEqual(hashlib.sha256(Path(acquired['root']).read_bytes()).hexdigest(),
                             record.provenance['identity']['output_sha256'])
            self.assertEqual(acquired['dependency_status'], 'resolved_locally')
            self.assertEqual(acquired['actual_download_bytes'], 0)

    def test_sdk_backend_rejects_program_text_paths_and_unbounded_parameters(self):
        from simscene.generation import usdcraft_sdk
        for value in ({'program': 'print(1)'}, {'script_path': '/tmp/evil.py'}, {'length_m': float('nan')},
                      {'thickness_m': .08, 'width_m': .02}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                usdcraft_sdk.parameters(RECIPE, value)
        self.assertFalse(callable(getattr(usdcraft_sdk, 'run_external_program', None)))
        from simscene.generation import usdcraft_backend_worker as worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {'operation': 'generate', 'recipe_id': RECIPE,
                    'parameters': {'length_m': .5, 'width_m': .18, 'thickness_m': .015},
                    'expected_runtime': {}, 'template_sha256': 'a' * 64,
                    'output': str(root / 'source.usda'), 'runtime_output': str(root / 'backend-runtime.json'),
                    'report_output': str(root / 'sdk-report.json')}
            for bad in (dict(task, program='print(1)'), dict(task, model_path='/tmp/evil.py'),
                        dict(task, output='/tmp/escaped.usda'), dict(task, recipe_id='other')):
                with self.subTest(task=bad), self.assertRaises(ValueError):
                    worker.validate_task(bad, root)

    def test_identical_generated_source_reuses_identity_despite_job_specific_report_hash(self):
        from simscene.generation import usdcraft_sdk
        from simscene.catalog.models import stable_hash
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'home': str(root / 'state'), 'index_directory': str(root / 'index')}
            runtime = {'schema_version': 1, 'backend': 'usdcraft_sdk', 'python': '/isolated/sdk-python',
                       'reviewed_commit': COMMIT,
                       'observed': {'usdcraft_commit': COMMIT, 'usdcraft_version': '1.0.0', 'source_clean': True}}
            def backend(task, python, folder):
                Path(task['output']).write_text('#usda 1.0\n')
                Path(task['runtime_output']).write_text(json.dumps(runtime['observed']))
                Path(task['report_output']).write_text(json.dumps({'check': 'passed', 'compile': 'passed',
                    'closure': 'resolved_locally', 'compile_report_sha256': hashlib.sha256(str(folder).encode()).hexdigest()}))
            with patch('simscene.generation.usdcraft_sdk._run', side_effect=backend):
                first = usdcraft_sdk.generate_asset(RECIPE, {}, runtime, output_directory=root / 'one', config=config)
                manifest = Path(first['generated_manifest_path'])
                generated = json.loads(manifest.read_text())
                self.assertEqual(generated['identity']['generation_contract_version'], 3)
                self.assertNotIn('compile_report_sha256', generated['generator_check'])
                first_manifest = manifest.read_bytes()
                # Recreate an older published contract at its original distinct
                # identity and ensure a new generation neither alters nor aliases it.
                legacy = json.loads(first_manifest)
                legacy['identity']['generation_contract_version'] = 2
                legacy_revision = stable_hash(legacy['identity'])
                legacy['asset_ref']['revision'] = legacy_revision
                legacy['generator_check']['compile_report_sha256'] = 'a' * 64
                legacy['generator_check']['compiled_root_sha256'] = 'b' * 64
                legacy_dir = root / 'state' / 'generated_assets' / legacy_revision
                legacy_dir.mkdir()
                shutil.copyfile(manifest.parent / 'source.usda', legacy_dir / 'source.usda')
                legacy_bytes = json.dumps(legacy).encode()
                (legacy_dir / 'generated.json').write_bytes(legacy_bytes)
                second = usdcraft_sdk.generate_asset(RECIPE, {}, runtime, output_directory=root / 'two', config=config)
                self.assertEqual(manifest.read_bytes(), first_manifest)
                self.assertEqual((legacy_dir / 'generated.json').read_bytes(), legacy_bytes)
                self.assertNotEqual(first['asset_ref']['revision'], legacy_revision)
                # Differences in frozen toolchain data remain an immutable collision.
                altered = json.loads(first_manifest)
                altered['identity']['toolchain']['reviewed_commit'] = '0' * 40
                manifest.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'immutable generated source collision'):
                    usdcraft_sdk.generate_asset(RECIPE, {}, runtime, output_directory=root / 'three', config=config)
            self.assertEqual(first['asset_ref'], second['asset_ref'])
            self.assertNotEqual(first['sdk_report_sha256'], second['sdk_report_sha256'])
            self.assertTrue(Path(second['sdk_report_path']).is_file())

    def test_changed_runtime_or_template_is_rejected_before_template_execution(self):
        from simscene.generation import usdcraft_backend_worker as worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = {'usdcraft_version': '1.0.0', 'source_tree_sha256': '1' * 64}
            task = {'operation': 'generate', 'recipe_id': RECIPE,
                    'parameters': {'length_m': .5, 'width_m': .18, 'thickness_m': .015},
                    'expected_runtime': dict(runtime), 'template_sha256': 'a' * 64,
                    'output': str(root / 'source.usda'), 'runtime_output': str(root / 'backend-runtime.json'),
                    'report_output': str(root / 'sdk-report.json')}
            with patch.object(worker, '_observe', return_value=dict(runtime, source_tree_sha256='2' * 64)):
                with self.assertRaisesRegex(ValueError, 'runtime changed'):
                    worker.run(task, root)
            with patch.object(worker, '_observe', return_value=runtime):
                with self.assertRaisesRegex(ValueError, 'template differs'):
                    worker.run(task, root)
            self.assertFalse((root / 'model.py').exists())

    def test_supervisor_dispatches_sdk_recipe_without_calling_sand3d(self):
        from simscene.generation import worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'job.json').write_text(json.dumps({'job_id': 'gen-' + 'a' * 32, 'state': 'queued'}))
            (root / 'config.json').write_text(json.dumps({'home': str(root)}))
            (root / 'task.json').write_text(json.dumps({'recipe_id': RECIPE, 'parameters': {}, 'runtime': {'backend': 'usdcraft_sdk'}}))
            with patch('simscene.__file__', str(root / 'runtime' / 'simscene' / '__init__.py')), \
                    patch('simscene.generation.usdcraft_sdk.generate_asset', return_value={'asset_ref': {'source_id': 'local-usdcraft-sdk'}}), \
                    patch('simscene.generation.sand3d.generate_asset', side_effect=AssertionError('wrong backend')):
                worker.execute(root)
            record = json.loads((root / 'job.json').read_text())
            self.assertEqual(record['state'], 'completed')
            self.assertEqual(record['result']['asset_ref']['source_id'], 'local-usdcraft-sdk')

    def test_sdk_runtime_has_separate_configuration_and_explicit_probe_cli(self):
        from simscene.catalog.config import read
        from simscene.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = root / 'v2.json'; manifest = root / 'sdk-runtime.json'
            config.write_text(json.dumps({'usdcraft_generation_runtime': str(manifest)}))
            with patch.dict('os.environ', {'SIMSCENE_V2_CONFIG': str(config)}):
                self.assertEqual(read()['usdcraft_generation_runtime'], str(manifest))
            argv = ['simscene', 'generate', 'probe', '--backend', 'usdcraft-sdk', '--python', '/sdk/python',
                    '--checkout', '/sdk/reviewed-checkout', '--output', str(manifest)]
            with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()), \
                    patch('simscene.generation.usdcraft_sdk.probe_runtime', return_value={'backend': 'usdcraft_sdk'}) as probe:
                self.assertEqual(main(), 0)
            probe.assert_called_once_with('/sdk/python', str(manifest), checkout='/sdk/reviewed-checkout')


if __name__ == '__main__':
    unittest.main()
