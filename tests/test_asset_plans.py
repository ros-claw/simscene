"""Frozen planning is metadata work; probes and payload acquisition are explicit."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simscene.acquisition.plans import make_plan, load_plan
from simscene.acquisition.dispatch import _validate_plan
from simscene.catalog.config import DEFAULTS
from simscene.catalog.models import AssetRef, AssetRecord
from simscene.preparation.glb_convert import CONVERTER
from simscene.preparation.profiles import PreparationError
from simscene.preparation.environment import current_runtime, installation_fingerprint

PARAMETERS = {'source_physics_policy': 'reject_if_physics', 'proxy_tolerance_m': .002}


def config_fixture(root):
    root = Path(root)
    return dict(DEFAULTS, home=str(root / 'home'), index_directory=str(root / 'index'),
                prepared_directory=str(root / 'prepared'), runtime_manifest=str(root / 'runtime.json'),
                asset_cache_directory=str(root / 'source-cache'), asset_cache_capacity_bytes=1024**2)


def runtime_fixture():
    return {'target': {'engine': 'physx', 'isaac_version': '6.2.0', 'usd_version': '0.25.11', 'platform': 'linux-x86_64'},
            'installation': {'launcher_sha256': 'a' * 64, 'isaac_version': '6.2.0'},
            'converter': copy.deepcopy(CONVERTER), 'predecoder_configuration': {'backend': 'fixture-decoder', 'lock_sha256': 'd' * 64}}


def record_fixture(**changes):
    data = {'ref': AssetRef('nvidia-usd-search', 'https://assets.example/selected.usda', 'metadata-sha256:' + 'b' * 64),
            'title': 'Selected fixture', 'format': 'usd', 'entry_path': 'selected.usda',
            'license': {'status': 'known', 'license': 'CC0-1.0'},
            'availability': {'estimated_download_bytes': 1024, 'granularity': 'dependency_closure',
                             'asset_url': 'https://assets.example/selected.usda', 'gated': False, 'private': False},
            'provenance': {'upstream_asset_id': 'fixture'}}
    data.update(changes)
    return AssetRecord(**data)


class AssetPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.config = config_fixture(self.root); self.runtime = runtime_fixture(); self.record = record_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **kwargs):
        values = dict(record=self.record, runtime=self.runtime, config=self.config)
        values.update(kwargs)
        return make_plan(values['record'].ref, 'visual_prop_v1', PARAMETERS, **values)

    def test_plan_does_not_fetch_probe_spawn_or_load_sdk(self):
        with patch('simscene.preparation.environment.probe_runtime', side_effect=AssertionError('probe forbidden')) as probe, patch('simscene.preparation.worker.run_sdk', side_effect=AssertionError('SDK forbidden')) as sdk, patch('subprocess.Popen', side_effect=AssertionError('spawn forbidden')) as process, patch('simscene.acquisition.dispatch.acquire_selected', side_effect=AssertionError('payload forbidden')) as fetch, patch('socket.create_connection', side_effect=AssertionError('network forbidden')) as network:
            first = self.plan(); second = self.plan()
        self.assertTrue(first['ready_to_fetch'])
        self.assertEqual(first['plan_id'], second['plan_id'])
        self.assertEqual(load_plan(first['plan_id'], config=self.config)['converter_selection'], CONVERTER)
        for mock in (probe, sdk, process, fetch, network): mock.assert_not_called()
        self.assertFalse(first['files_complete'])
        self.assertEqual(first['content_identity'], 'pending_acquisition_content_lock')
        self.assertTrue(first['unknown_sizes'])

    def test_each_budget_target_converter_profile_parameter_changes_identity(self):
        original = self.plan()
        for key in ('download_bytes', 'unpacked_bytes', 'staging_bytes'):
            changed = self.plan(budgets={key: 2 * 1024**3})
            with self.subTest(key=key): self.assertNotEqual(changed['plan_id'], original['plan_id'])
        runtime = copy.deepcopy(self.runtime); runtime['target']['isaac_version'] = '6.2.1'
        self.assertNotEqual(self.plan(runtime=runtime)['plan_id'], original['plan_id'])
        runtime = copy.deepcopy(self.runtime); runtime['converter']['version'] += '-changed'
        self.assertNotEqual(self.plan(runtime=runtime)['plan_id'], original['plan_id'])
        changed = make_plan(self.record.ref, 'rigid_prop_v1', dict(PARAMETERS, mass_kg=.2, mass_note='experimental fixture mass'), record=self.record, runtime=self.runtime, config=self.config)
        self.assertTrue(changed['ready_to_fetch'])
        self.assertNotEqual(changed['plan_id'], original['plan_id'])
        altered = make_plan(self.record.ref, 'visual_prop_v1', dict(PARAMETERS, proxy_tolerance_m=.003), record=self.record, runtime=self.runtime, config=self.config)
        self.assertNotEqual(altered['plan_id'], original['plan_id'])
        self.assertEqual(original['budget_breakdown']['download_bytes'], self.config['asset_download_bytes'])
        self.assertEqual(self.config['asset_cache_capacity_bytes'], 1024**2)

    def test_persisted_plan_tampering_and_in_memory_dispatch_changes_rejected(self):
        original = self.plan()
        for key, value in [('target', dict(self.runtime['target'], engine='other')), ('profile_id', 'rigid_prop_v1'), ('budget_breakdown', {'download_bytes': 1, 'staging_bytes': 2, 'unpacked_bytes': 3}), ('source_snapshot', {})]:
            changed = copy.deepcopy(original); changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'immutable acquisition plan changed'):
                _validate_plan(changed)
        path = Path(original['plan_ref']); data = json.loads(path.read_text()); data['parameters']['proxy_tolerance_m'] = .5
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'immutable plan changed'):
            load_plan(original['plan_id'], config=self.config)
        with self.assertRaisesRegex(ValueError, 'modified plan'):
            self.plan()

    def test_invalid_hf_revision_budget_and_mismatched_resolved_ref(self):
        ref = AssetRef('abo-glb', 'selected', 'main')
        with self.assertRaisesRegex(ValueError, 'full commit SHA'):
            make_plan(ref, parameters=PARAMETERS, record=record_fixture(ref=ref), runtime=self.runtime, config=self.config)
        for budgets in ({'download_bytes': True}, {'unpacked_bytes': 0}, {'staging_bytes': -1}, {'cache_bytes': 12}):
            with self.subTest(budgets=budgets), self.assertRaises(ValueError): self.plan(budgets=budgets)
        with self.assertRaisesRegex(ValueError, 'does not match ref'):
            make_plan(AssetRef('nvidia-usd-search', 'different', 'version'), parameters=PARAMETERS, record=self.record, runtime=self.runtime, config=self.config)

    def test_missing_runtime_codec_unknown_license_and_budget_block(self):
        for error, code in [('environment_probe_required: explicit probe needed', 'environment_probe_required'), ('unsupported_codec: required decoder missing', 'unsupported_codec'), ('plan_environment_changed: stale probe', 'plan_environment_changed')]:
            with self.subTest(code=code), patch('simscene.acquisition.plans.current_runtime', side_effect=ValueError(error)):
                result = make_plan(self.record.ref, parameters=PARAMETERS, record=self.record, config=self.config)
                self.assertFalse(result['ready_to_fetch'])
                self.assertIn(code, {item['code'] for item in result['blocking_reasons']})
        for license_info in (None, {'status': 'unknown'}, {'status': 'conflicting'}):
            result = self.plan(record=record_fixture(license=license_info))
            self.assertIn('license_unresolved', {item['code'] for item in result['blocking_reasons']})
        result = self.plan(budgets={'download_bytes': 512})
        self.assertFalse(result['ready_to_fetch'])
        self.assertIn('budget_exceeded', {item['code'] for item in result['blocking_reasons']})
        result = self.plan(target=dict(self.runtime['target'], isaac_version='old'))
        self.assertIn('plan_environment_changed', {item['code'] for item in result['blocking_reasons']})

    def test_typed_runtime_failure_preserves_machine_readable_error_code(self):
        error = PreparationError('dependency_missing', 'required isolated Node decoder installation is absent')
        with patch('simscene.acquisition.plans.current_runtime', side_effect=error):
            result = make_plan(self.record.ref, parameters=PARAMETERS, record=self.record, config=self.config)
        self.assertFalse(result['ready_to_fetch'])
        self.assertEqual(result['blocking_reasons'][0]['code'], 'dependency_missing')
        self.assertEqual(result['blocking_reasons'][0]['detail'], str(error))

    def test_invalid_profile_parameters_are_blocked_not_claimed_ready(self):
        result = make_plan(self.record.ref, 'rigid_prop_v1', PARAMETERS, record=self.record, runtime=self.runtime, config=self.config)
        self.assertFalse(result['ready_to_fetch'])
        self.assertIn('physics_profile_unsupported', {item['code'] for item in result['blocking_reasons']})
        result = self.plan(record=record_fixture(availability=dict(self.record.availability, gated=True)))
        self.assertIn('source_gated', {item['code'] for item in result['blocking_reasons']})

    def test_runtime_observation_requires_current_installation_converter_and_codec(self):
        record = {'schema_version': 1, 'installation': self.runtime['installation'], 'target': self.runtime['target'], 'converter': self.runtime['converter'], 'predecoder_configuration': {'lock': 'fixture'}}
        self.config['converter_tools_prefix'] = str(self.root / 'tools')
        path = Path(self.config['runtime_manifest']); path.write_text(json.dumps(record))
        with patch('simscene.catalog.config.read', return_value=self.config), patch('simscene.preparation.environment.installation_fingerprint', return_value=self.runtime['installation']), patch('simscene.preparation.glb_convert.predecoder_fingerprint', return_value={'lock': 'fixture'}) as codec, patch('subprocess.Popen', side_effect=AssertionError('probe forbidden')):
            self.assertEqual(current_runtime()['target'], self.runtime['target'])
            codec.assert_called_once_with(self.config['converter_tools_prefix'])
            with patch('simscene.preparation.glb_convert.predecoder_fingerprint', return_value=None), self.assertRaisesRegex(ValueError, 'predecoder installation changed'):
                current_runtime()
            record['installation'] = {}; path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'probe is stale'): current_runtime()
            record['installation'] = self.runtime['installation']; record['converter'] = {'backend': 'missing'}; path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'no verified converter'): current_runtime()

    def test_abo_known_compressed_selection_requires_verified_predecoder_environment(self):
        ref = AssetRef('abo-glb', 'selected', 'a' * 40)
        record = record_fixture(ref=ref, format='glb', entry_path='objects/selected/selected.glb')
        for missing in (None, {}):
            runtime = copy.deepcopy(self.runtime); runtime['predecoder_configuration'] = missing
            result = make_plan(ref, parameters=PARAMETERS, record=record, runtime=runtime, config=self.config)
            with self.subTest(configuration=missing):
                self.assertFalse(result['ready_to_fetch'])
                self.assertIn('unsupported_codec', {item['code'] for item in result['blocking_reasons']})
        first = make_plan(ref, parameters=PARAMETERS, record=record, runtime=self.runtime, config=self.config)
        self.assertTrue(first['ready_to_fetch'])
        changed = copy.deepcopy(self.runtime)
        changed['predecoder_configuration']['lock_sha256'] = 'e' * 64
        second = make_plan(ref, parameters=PARAMETERS, record=record, runtime=changed, config=self.config)
        self.assertNotEqual(first['plan_id'], second['plan_id'])
        self.assertEqual(first['converter_environment'], self.runtime['predecoder_configuration'])

    def test_installation_fingerprint_hashes_files_without_executing_launcher(self):
        sdk = self.root / 'sdk'; sdk.mkdir(); launcher = sdk / 'python.sh'; launcher.write_text('unexecuted fixture launcher')
        (sdk / 'VERSION').write_text('fixture-6.2')
        config = sdk / 'extscache' / 'omni.kit.asset_converter-fixture' / 'config' / 'extension.toml'; config.parent.mkdir(parents=True); config.write_text('version="1"')
        with patch('simscene.settings.get', return_value=str(launcher)), patch('subprocess.Popen', side_effect=AssertionError('execution forbidden')):
            first = installation_fingerprint(); config.write_text('version="2"'); second = installation_fingerprint()
        self.assertNotEqual(first['converter_configs'], second['converter_configs'])
        self.assertEqual(first['launcher_sha256'], second['launcher_sha256'])


if __name__ == '__main__': unittest.main()
