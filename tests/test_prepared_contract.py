"""Prepared contract aliases retain evidence and storage-independent recipe identity."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from simscene.preparation.contracts import prepared_contract, MAX_SUMMARY_BYTES
from simscene.preparation.profiles import validate_parameters


def manifest(**changes):
    base = {'schema': 'simscene.prepared_asset.v1', 'schema_version': 1,
            'prepared_id': 'a' * 64, 'profile_id': 'rigid_prop_v1', 'profile_version': 1,
            'main': 'main.usda', 'default_prim': '/Asset',
            'root': '/evicted/old-job/prepared-staging',
            'asset_path': '/evicted/old-job/prepared-staging/main.usda',
            'parameters': {'source_physics_policy': 'reject_if_physics', 'proxy_tolerance_m': 0.01,
                           'mass_kg': 0.2, 'mass_note': 'explicit experimental mass'},
            'target': {'engine': 'physx', 'isaac_version': 'fixture', 'usd_version': '0.25.11', 'platform': 'linux'},
            'toolchain': {'backend': 'openusd', 'version': '0.25.11'},
            'source_manifest_sha256': 'b' * 64,
            'bounds': {'min': [0, 0, 0], 'max': [0.1, 0.2, 0.3], 'dimensions': [0.1, 0.2, 0.3]},
            'body_map': {'main': {'relative_prim_path': 'Body', 'role': 'rigid',
                                  'visual_relative_prim_paths': ['Body/Visual'],
                                  'collider_relative_prim_paths': ['Body/Visual/Mesh']}},
            'runtime_validation': {'status': 'not_run', 'physical_steps': 0},
            'runtime_dependencies': [], 'collision_report': {'method': 'sampled_hull_fidelity'},
            'files': [{'path': 'main.usda', 'sha256': 'c' * 64, 'size_bytes': 100}]}
    return dict(base, **changes)


class PreparedContractTest(unittest.TestCase):
    def test_required_fields_and_current_location_preserve_compatibility_shapes(self):
        source = manifest()
        result = prepared_contract(source, manifest_path='/current/cache/package/manifest.json', manifest_sha256='d' * 64)
        expected = {'prepared_handle', 'root', 'profile_id', 'recipe_hash', 'toolchain', 'target',
                    'source_manifest_hash', 'derived_files', 'metrics', 'body_map', 'material_report',
                    'physics_report', 'warnings', 'runtime_validation'}
        self.assertTrue(expected <= result.keys())
        self.assertEqual(result['root'], '/current/cache/package/main.usda')
        self.assertEqual(result['prepared_handle'], source['prepared_id'])
        self.assertEqual(result['source_manifest_hash'], 'b' * 64)
        self.assertEqual(result['body_map'], source['body_map'])
        self.assertEqual(result['bounds'], source['bounds'])
        self.assertEqual(result['runtime_validation'], {'status': 'not_run', 'physical_steps': 0})
        self.assertEqual(result['metrics']['meters_per_unit'], 1.0)
        self.assertEqual(result['metrics']['up_axis'], 'Z')
        self.assertIn('declaration', result['metrics']['basis'])
        self.assertNotIn('/evicted/', json.dumps(result))

    def test_recipe_identity_normalizes_defaults_and_excludes_paths_jobs_and_observation_metadata(self):
        first = manifest()
        second = manifest(parameters=validate_parameters(first['profile_id'], first['parameters']),
                          root='/another/job', asset_path='/another/job/main.usda', job_id='another',
                          created_at='tomorrow', provenance={'temporary_path': '/tmp/another'})
        one = prepared_contract(first, manifest_path='/one/manifest.json')
        two = prepared_contract(second, manifest_path='/two/manifest.json')
        self.assertEqual(one['recipe_hash'], two['recipe_hash'])
        changed = manifest(parameters=dict(first['parameters'], mass_kg=0.3))
        self.assertNotEqual(one['recipe_hash'], prepared_contract(changed)['recipe_hash'])
        renamed = manifest(parameters=dict(first['parameters'], mass_note='another explicit assumption'))
        self.assertNotEqual(one['recipe_hash'], prepared_contract(renamed)['recipe_hash'])

    def test_unknown_material_information_stays_null_without_counting_mapped_meshes(self):
        result = prepared_contract(manifest())
        report = result['material_report']
        self.assertIsNone(report['inspected_material_count'])
        self.assertEqual(report['material_evidence'], 'unknown')
        self.assertEqual(report['runtime_dependency_count'], 0)
        self.assertEqual(report['runtime_dependency_evidence'], 'inspected')
        missing = manifest(); missing.pop('runtime_dependencies')
        report = prepared_contract(missing)['material_report']
        self.assertIsNone(report['runtime_dependency_count'])
        self.assertEqual(report['runtime_dependency_evidence'], 'unknown')
        known = prepared_contract(manifest(material_report={'inspected_material_count': 0}))
        self.assertEqual(known['material_report']['inspected_material_count'], 0)
        self.assertEqual(known['material_report']['material_evidence'], 'inspected')

    def test_reports_reference_full_details_and_warn_about_actual_assumptions(self):
        source = manifest(runtime_dependencies=[{'kind': 'target_runtime_mdl', 'asset': 'OmniPBR.mdl'}])
        result = prepared_contract(source, manifest_path='/current/manifest.json', manifest_sha256='d' * 64)
        self.assertEqual(result['derived_files']['json_pointer'], '/files')
        self.assertEqual(result['derived_files']['selector'], {'exclude_prefixes': ['source/', 'licenses/']})
        self.assertNotIn('files', result)
        report = result['physics_report']
        self.assertEqual(report['collision_method'], 'convex_hull')
        self.assertEqual(report['mass_assumption_kg'], 0.2)
        self.assertTrue(report['experimental_mass'])
        self.assertEqual(report['collision_report_ref']['json_pointer'], '/collision_report')
        self.assertEqual(report['collision_report_ref']['manifest_sha256'], 'd' * 64)
        self.assertIn('collision_approximation:convex_hull', result['warnings'])
        self.assertIn('runtime_mdl_dependency_requires_target_environment', result['warnings'])
        self.assertIn('experimental_mass_assumption_not_manufacturer_data', result['warnings'])
        self.assertIn('physical_runtime_validation_not_verified', result['warnings'])

    def test_visual_profile_does_not_claim_applied_physics_or_experimental_mass(self):
        source = manifest(profile_id='visual_prop_v1', parameters={'source_physics_policy': 'replace_visual_only', 'proxy_tolerance_m': 0.01},
                          body_map={}, collision_report=None)
        result = prepared_contract(source)
        self.assertFalse(result['physics_report']['collision_applied'])
        self.assertFalse(result['physics_report']['experimental_mass'])
        self.assertFalse(result['physics_report']['experimental_material'])
        self.assertIsNone(result['physics_report']['mass_assumption_kg'])
        self.assertIsNone(result['physics_report']['collision_report_ref'])
        self.assertIsNone(result['root'])  # No current location supplied: stale producer paths are ignored.

    def test_version_nonfinite_and_unsafe_entry_contracts_are_rejected(self):
        for changes in ({'schema_version': 2}, {'schema_version': True}, {'profile_version': 999},
                        {'schema': 'unknown'}, {'main': '../outside.usda'}, {'main': '/outside.usda'},
                        {'parameters': dict(manifest()['parameters'], mass_kg=float('nan'))},
                        {'material_report': {'inspected_material_count': True}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepared_contract(manifest(**changes))
        with self.assertRaises(ValueError):
            prepared_contract(manifest(), manifest_sha256='not a digest')

    def test_pure_summary_performs_no_filesystem_or_sdk_work_and_leaves_input_unchanged(self):
        source = manifest(); before = deepcopy(source)
        with patch.object(Path, 'open', side_effect=AssertionError('file IO forbidden')), patch.dict('sys.modules', {'pxr': None, 'isaacsim': None}):
            result = prepared_contract(source, manifest_path='/never-read/manifest.json')
        self.assertEqual(source, before)
        result['body_map']['main']['role'] = 'changed outside'
        self.assertEqual(source, before)

    def test_large_inventory_and_reports_stay_referenced_and_response_is_bounded(self):
        source = manifest(files=[{'path': 'source/item-' + str(n)} for n in range(10000)],
                          collision_report={'samples': ['large report data'] * 10000})
        result = prepared_contract(source, manifest_path='/current/manifest.json')
        self.assertLess(len(json.dumps(result).encode()), 5000)
        self.assertNotIn('samples', json.dumps(result))
        # Critical mappings must never be silently truncated to satisfy a size cap.
        source['body_map']['main']['collider_relative_prim_paths'] = ['Body/' + 'x' * MAX_SUMMARY_BYTES]
        with self.assertRaisesRegex(ValueError, 'bounded response'):
            prepared_contract(source)


if __name__ == '__main__':
    unittest.main()
