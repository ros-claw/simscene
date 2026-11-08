"""CPU-only checks of public recipe portability and frozen selection contracts."""
from copy import deepcopy
import importlib.util
import hashlib
import io
import tempfile
import zipfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/catalog_gravity_cell'
spec = importlib.util.spec_from_file_location('catalog_mvp_driver', ROOT / 'experiments/run_catalog_mvp.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class CatalogMVPTest(unittest.TestCase):
    def setUp(self):
        self.recipe = json.loads((EXAMPLE / 'recipe.json').read_text())
        self.case = json.loads((EXAMPLE / 'case.json').read_text())
        self.lock = json.loads((EXAMPLE / 'assets.lock.json').read_text())
        self.prepared = {'root': '/runtime/new-prepared/main.usda',
                         'manifest_path': '/runtime/new-prepared/manifest.json', 'manifest_sha256': '1' * 64}

    def test_all_public_json_templates_are_portable_and_actual_notebook_is_pinned(self):
        for path in EXAMPLE.glob('*.json'):
            driver.assert_portable(json.loads(path.read_text()))
        selected = self.lock['assets']['notebook']
        self.assertEqual(selected['source_ref']['asset_id'], 'B01DN8TB5U')
        self.assertEqual(selected['source_ref']['revision'], 'c7c8293fed3b7ab122ef5d7896521a187e0962d7')
        self.assertEqual(selected['source_file_sha256'], '67d61db31084d820ca9b1b0d2d3761662f6a5532944573afceee8f57c8151845')
        self.assertNotIn('prepared_manifest_sha256', selected)
        self.assertEqual(self.lock['assets']['workbench']['license']['status'], 'unknown')
        self.assertNotIn('package_sha256', self.lock['assets']['workbench'])
        self.assertEqual(self.recipe['asset_roles']['notebook']['parameters']['target_longest_extent_m'], 0.15)
        self.assertEqual(self.recipe['asset_roles']['notebook']['parameters']['mass_kg'], 0.12)

    def test_compile_keeps_four_real_independent_assets_and_editable_physical_geometry(self):
        before = deepcopy(self.recipe)
        scene = driver.compile_scene(self.recipe, self.prepared, '/runtime/bare-table.usd')
        books = {k: v for k, v in scene['objects'].items() if k.startswith('book_')}
        self.assertEqual(len(books), 4)
        for obj in books.values():
            self.assertEqual(obj['kind'], 'asset')
            self.assertTrue(obj['dynamic'])
            self.assertEqual(obj['asset_path'], self.prepared['root'])
            self.assertEqual(obj['asset_binding']['manifest_sha256'], self.prepared['manifest_sha256'])
            self.assertNotIn('asset_role', obj)
        for key, value in self.recipe['objects'].items():
            if value['kind'] not in {'asset', 'camera'}:
                self.assertEqual(scene['objects'][key], value)
        self.assertNotIn('asset_metrics', scene['objects']['workbench'])
        self.assertEqual(scene['objects']['workbench']['asset_physics'], 'visual_only')
        self.assertNotIn('overview', scene['objects'])
        self.assertEqual(self.recipe, before)
        captured = driver.compile_scene(self.recipe, self.prepared, '/runtime/bare-table.usd', record=True)
        self.assertEqual(captured['objects']['overview']['camera']['resolution'], [960, 540])
        self.assertEqual(captured['objects']['overview']['camera']['capture_window']['end_step'], 300)

    def test_compiled_scene_passes_real_scene_contract_for_all_object_fields(self):
        from simscene.scene import validate
        verified_manifest = {'profile_id': 'rigid_prop_v1', 'body_map': {'main': {
            'role': 'rigid', 'relative_prim_path': 'Body',
            'collider_relative_prim_paths': ['Body/Visual/Mesh'], 'visual_relative_prim_paths': ['Body/Visual']}}}
        for mode in ('routing', 'smoke'):
            for record in (False, True):
                with self.subTest(mode=mode, record=record):
                    scene = driver.compile_scene(self.recipe, self.prepared, '/runtime/bare-table.usd', mode=mode, record=record)
                    with patch('simscene.physics_binding.validate_asset_binding', return_value=verified_manifest):
                        self.assertEqual(validate(scene), [])
        # Ensure the ordinary validator really protects this import boundary.
        scene['objects']['workbench']['asset_metrics'] = {'meters_per_unit': 0.01, 'up_axis': 'Z'}
        with patch('simscene.physics_binding.validate_asset_binding', return_value=verified_manifest):
            self.assertTrue(any('inspection reason' in item['message'] for item in validate(scene)))

    def test_fresh_prepared_hash_is_frozen_before_run_without_reinterpreting_old_case(self):
        before = deepcopy(self.case)
        source_ref = self.lock['assets']['notebook']['source_ref']
        one = driver.freeze_case(self.case, self.prepared, source_ref)
        self.assertEqual(one['objects'], self.case['objects'])
        self.assertEqual(one['prepared_manifest_sha256'], '1' * 64)
        two = driver.freeze_case(self.case, dict(self.prepared, manifest_sha256='2' * 64), source_ref)
        self.assertEqual(two['objects'], one['objects'])
        self.assertNotEqual(two['prepared_manifest_sha256'], one['prepared_manifest_sha256'])
        self.assertEqual(self.case, before)
        with self.assertRaisesRegex(ValueError, 'already frozen'):
            driver.freeze_case(one, self.prepared, source_ref)
        with self.assertRaisesRegex(ValueError, 'source reference'):
            driver.freeze_case(self.case, self.prepared, dict(source_ref, asset_id='another-model'))
        self.assertEqual(self.case['prepared_manifest_sha256'], driver.PREPARED_SHA_MARKER)

    def test_smoke_is_an_explicit_one_object_subset_of_the_same_physical_case(self):
        scene = driver.compile_scene(self.recipe, self.prepared, '/runtime/table.usd', mode='smoke')
        case = driver.freeze_case(self.case, self.prepared, self.lock['assets']['notebook']['source_ref'], mode='smoke')
        self.assertEqual(set(case['objects']), {'book_left_front'})
        self.assertEqual([name for name in scene['objects'] if name.startswith('book_')], ['book_left_front'])
        self.assertEqual(case['objects']['book_left_front'], self.case['objects']['book_left_front'])
        for name, predicates in self.case['objects'].items():
            lane = 'left' if '_left_' in name else 'right'
            self.assertEqual(predicates['required_contact_actors'], ['/World/ramp_' + lane, '/World/baffle_' + lane, '/World/bin_' + lane + '_floor'])
            self.assertEqual(predicates['min_drop_m'], 0.15)

    def test_source_identity_uses_complete_content_table_not_zip_hash_or_locations(self):
        for role in ('notebook', 'workbench'):
            locked = self.lock['assets'][role]
            acquired = {'files': deepcopy(locked['files']), 'source_ref': locked['source_ref'],
                        'root': '/arbitrary/cache/root.usd', 'package_sha256': '9' * 64}
            if role == 'notebook':
                acquired['manifest_sha256'] = locked['source_manifest_sha256']
            driver.verify_source_lock(acquired, locked)
            acquired['files'].reverse(); acquired['package_sha256'] = '8' * 64
            driver.verify_source_lock(acquired, locked)
            acquired['files'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'source_content_changed'):
                driver.verify_source_lock(acquired, locked)

    def test_private_legacy_input_keeps_real_sha_identity_and_becomes_run_snapshot(self):
        from simscene.cache import AssetCache
        from simscene.jobs import _snapshot_cached_assets
        source = 'https://fixture.example/assets/packing_table.usda'
        child_url = 'https://fixture.example/assets/props/bare_table.usda'
        root_data = b'#usda 1.0\n( subLayers = [@props/bare_table.usda@] )\n'
        child_data = b'#usda 1.0\n(\n defaultPrim = "Table"\n metersPerUnit = 0.01\n upAxis = "Z"\n)\ndef Xform "Table" {}\n'
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('packing_table.usda', root_data)
            archive.writestr('props/bare_table.usda', child_data)
            archive.writestr('manifest.json', json.dumps({'root_url': source, 'files': [
                {'url': source, 'path': 'packing_table.usda', 'size': len(root_data)},
                {'url': child_url, 'path': 'props/bare_table.usda', 'size': len(child_data)}],
                'errors': {}, 'skipped': []}))
        archive_bytes = payload.getvalue()
        class FixtureClient:
            def request(self, path, params=None, output=None, **kwargs):
                if output is not None:
                    output.write_bytes(archive_bytes)
                    return len(archive_bytes)
                return {'total_size': len(root_data) + len(child_data)}
        class NetworkForbidden:
            def request(self, *args, **kwargs):
                raise AssertionError('a verified warm fixture must not download')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cache = root / 'source-cache'
            acquired = AssetCache(FixtureClient(), cache, max_bytes=1000000).acquire(source)
            actual_package_sha = hashlib.sha256(archive_bytes).hexdigest()
            self.assertEqual(acquired['package_sha256'], actual_package_sha)
            selected = next(item for item in acquired['files'] if item['url'] == child_url)
            locked = {'source_ref': {'source_id': 'nvidia-usd-search', 'asset_id': source, 'revision': 'metadata:fixture', 'variant_id': None},
                      'source_url': source, 'content_sha256': AssetCache.content_identity(acquired['files']),
                      'files': acquired['files'], 'selected_member': {'path': selected['path'], 'sha256': selected['sha256']},
                      'license': {'status': 'unknown', 'license': None}, 'source_terms': {'scope': 'CPU fixture'}}
            output = root / 'attempt'; output.mkdir()
            config = {'asset_cache_directory': str(cache), 'asset_cache_capacity_bytes': 1000000}
            with patch('simscene.acquisition.dispatch._BudgetUSDSearch', return_value=NetworkForbidden()):
                member = driver.acquire_workbench(locked, config, output, driver.SceneBudget())
            package = output / 'asset-inputs' / actual_package_sha
            self.assertTrue(member.is_relative_to(package))
            self.assertEqual(json.loads((package / 'simscene-lock.json').read_text())['package_sha256'], actual_package_sha)
            self.assertEqual(member.read_bytes(), child_data)
            scene = {'objects': {'workbench': {'kind': 'asset', 'asset_path': str(member), 'asset_physics': 'visual_only'}}}
            run = root / 'new-run'; run.mkdir()
            with patch('simscene.settings.get', return_value=None), patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
                records = _snapshot_cached_assets(scene, run)
            self.assertEqual(records['workbench']['kind'], 'snapshot')
            self.assertEqual(records['workbench']['package_sha256'], actual_package_sha)
            self.assertEqual(records['workbench']['snapshot_integrity_version'], 1)
            self.assertEqual(len(records['workbench']['snapshot_files']), 2)
            self.assertTrue(Path(scene['objects']['workbench']['asset_path']).is_relative_to(run / 'assets' / actual_package_sha))
            self.assertEqual(Path(scene['objects']['workbench']['asset_path']).read_bytes(), child_data)

    def test_budget_charges_cumulative_failed_bytes_once_and_reserves_unknown_cost(self):
        budget = driver.SceneBudget(limit=100)
        budget.update('workbench', 40)
        budget.update('notebook', 3)
        budget.update('notebook', 7)
        self.assertEqual(budget.actual, 47)
        self.assertEqual(budget.remaining, 53)
        budget.unknown('interrupted', 10)
        self.assertFalse(budget.to_dict()['accounting_complete'])
        self.assertEqual(budget.remaining, 43)
        with self.assertRaises(ValueError):
            budget.update('notebook', 2)
        with self.assertRaises(ValueError):
            budget.update('another-stage', 60)

    def test_compile_and_freeze_require_no_network_subprocess_or_sdk(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), patch('subprocess.Popen', side_effect=AssertionError('SDK/subprocess forbidden')), patch.dict('sys.modules', {'isaacsim': None, 'pxr': None}):
            driver.compile_scene(self.recipe, self.prepared, '/runtime/table.usd')
            driver.freeze_case(self.case, self.prepared, self.lock['assets']['notebook']['source_ref'])
        for value in ('../outside.usd', '/host/path.usd', 'a/%2e%2e/escape.usd'):
            with self.assertRaises(ValueError):
                driver.safe_member(value)


if __name__ == '__main__':
    unittest.main()
