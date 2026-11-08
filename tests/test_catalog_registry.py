"""CPU contracts: admission, unknown facts, identity, and offline resource loading."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from simscene.catalog import (AssetRecord, AssetRef, BackendTarget, MetadataEntry,
                              SearchPage, SearchRequest, canonical_json, stable_hash,
                              load_registry, validate_source)
from simscene.catalog.registry import Registry


class CatalogRegistryTest(unittest.TestCase):
    def test_packaged_registry_is_offline_and_independent_of_cwd(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
            try:
                os.chdir(directory)
                registry = load_registry()
            finally:
                os.chdir(old)
        self.assertEqual([s.source_id for s in registry.select()], ['nvidia-usd-search', 'abo-glb', 'gso-glb'])
        self.assertEqual(registry.schema_version, 1)
        self.assertTrue(all(s.state == 'enabled' and s.default_enabled for s in registry.select()))
        self.assertTrue(all(not s.default_enabled for s in registry.sources if s.state != 'enabled'))
        self.assertTrue(all(s.checked_at == '2026-11-08' for s in registry.sources))
        abo = registry.get('abo-glb')
        self.assertEqual(abo.repository, 'codepawl/abo-glb')
        self.assertEqual(registry.select(['abo-glb']), (abo,))
        self.assertEqual(abo.metadata_entries[0].path, 'metadata.jsonl')
        for source in registry.sources:
            static = [entry for entry in source.evidence if entry['scope'] == 'static_source_review']
            self.assertEqual(len(static), 1)
            self.assertEqual(static[0]['runtime_validation'], 'not_run')

    def test_m1_evidence_is_selected_asset_scoped_and_retains_licensing_gaps(self):
        registry = load_registry()
        target = {'engine': 'physx', 'isaac_version': '6.2.0-rc.14+release.52805.02189a84.gl',
                  'usd_version': '0.25.11', 'platform': 'linux-x86_64'}
        for source in registry.select(['nvidia-usd-search','abo-glb']):
            executed = [entry for entry in source.evidence if entry.get('evidence_basis') == 'locally_executed']
            self.assertEqual(len(executed), 1)
            record = executed[0]
            self.assertEqual(record['runtime_validation'], 'pass')
            self.assertEqual(record['target'], target)
            self.assertEqual(record['public_recipe'], 'examples/catalog_gravity_cell/recipe.json')
            self.assertEqual(record['public_case_template'], 'examples/catalog_gravity_cell/case.json')
            self.assertEqual(record['public_asset_lock'], 'examples/catalog_gravity_cell/assets.lock.json')
            self.assertEqual(source.capabilities, {})  # Admission never upgrades every asset's physics facts.
        nvidia = registry.get('nvidia-usd-search')
        self.assertEqual(nvidia.license_policy['status'], 'unknown')
        nvidia_proof = nvidia.evidence[-1]
        self.assertFalse(nvidia_proof['new_asset_plan_ready'])
        self.assertEqual(nvidia_proof['license_status'], 'unknown')
        self.assertIn('visual-only', ' '.join(nvidia_proof['accepted_scope']))
        notebook = registry.get('abo-glb').evidence[-1]
        self.assertEqual(notebook['selected_asset']['asset_id'], 'B01DN8TB5U')
        self.assertEqual(notebook['selected_asset']['revision'], 'c7c8293fed3b7ab122ef5d7896521a187e0962d7')
        self.assertEqual(notebook['profile_id'], 'rigid_prop_v1')
        self.assertEqual(notebook['recipe_parameters']['target_longest_extent_m'], 0.15)
        self.assertEqual(notebook['recipe_parameters']['mass_kg'], 0.12)
        self.assertEqual(notebook['clean_initializations'], 3)
        self.assertEqual(len(notebook['negative_controls']), 2)

    def test_explicit_audited_fixture_stays_disabled_until_selected(self):
        sources = tuple(replace(source, state='audited', default_enabled=False) for source in load_registry().sources)
        registry = Registry(sources)
        self.assertEqual(registry.select(), ())
        self.assertEqual(registry.select(['abo-glb']), (registry.get('abo-glb'),))
        self.assertTrue(all(source.state == 'audited' and not source.default_enabled for source in sources))

    def test_duplicate_unknown_adapter_and_unsafe_promotion_rejected(self):
        source = load_registry().get('abo-glb')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            Registry((source, source))
        for changes in ({'adapter': 'execute_remote_code'}, {'state': 'audited', 'default_enabled': True},
                        {'schema_version': 2}, {'state': 'runtime_verified'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_source(dict(source.to_dict(), **changes))
        with self.assertRaises(ValueError):
            Registry((replace(source, state='quarantined', default_enabled=False),)).select(['abo-glb'])
        with self.assertRaises(KeyError):
            load_registry().select(['unknown'])

    def test_unknown_source_error_lists_bounded_known_ids_without_changing_lookup(self):
        registry = load_registry()
        with self.assertRaises(KeyError) as caught:
            registry.get('nvidia-simready')
        self.assertIn('unknown catalog source: nvidia-simready', str(caught.exception))
        self.assertIn('known source IDs: nvidia-usd-search, abo-glb', str(caught.exception))
        self.assertEqual(registry.get('nvidia-usd-search').source_id, 'nvidia-usd-search')
        base = registry.get('nvidia-usd-search')
        many = Registry(tuple(replace(base, source_id=f'source{i}-' + 'x' * 1000) for i in range(10)))
        with self.assertRaises(KeyError) as caught:
            many.get('unknown')
        hint = str(caught.exception).split('known source IDs: ', 1)[1]
        self.assertLess(len(hint), 600)
        self.assertNotIn('source8-', hint)
        self.assertNotIn('x' * 65, hint)
        self.assertIn('…', hint)

    def test_custom_registry_duplicate_id_and_unsafe_yaml_rejected(self):
        record = load_registry().to_dict()
        record['sources'].append(deepcopy(record['sources'][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sources.yaml'
            path.write_text(yaml.safe_dump(record))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                load_registry(path)
            path.write_text('!!python/object/apply:os.system ["false"]')
            with self.assertRaisesRegex(ValueError, 'invalid catalog'):
                load_registry(path)

    def test_metadata_must_be_declared_and_safe(self):
        registry = load_registry()
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            registry.validate_metadata_reference('abo-glb', 'models/all.glb')
        base = registry.get('abo-glb').metadata_entries[0].to_dict()
        for changes in ({'path': '../metadata.jsonl'}, {'path': '/tmp/metadata.jsonl'},
                        {'path': 'https://user:password@example.org/index.jsonl'},
                        {'path': 'https://example.org/index.jsonl?token=secret'},
                        {'path': 'file:///tmp/index.jsonl'}, {'path': 'models/all.glb'},
                        {'path': 'https://example.org/archive.zip'}, {'contains_images': True},
                        {'contains_code': True}, {'contains_images': None},
                        {'format': 'parquet'}, {'size_bytes': -1}, {'size_bytes': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                MetadataEntry.from_dict(dict(base, **changes))
        source = registry.get('abo-glb').to_dict()
        source['access']['token'] = 'must-not-store'
        with self.assertRaises(ValueError):
            validate_source(source)

    def test_selection_requires_pinned_hf_revision_not_search_branch(self):
        for revision in ('main', 'a' * 7, 'x' * 40):
            ref = AssetRef('abo-glb', 'item', revision)
            with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, 'full commit'):
                ref.validate_selection()
        ref = AssetRef('abo-glb', 'item', 'a' * 40)
        self.assertIs(ref.validate_selection(), ref)
        with self.assertRaises(ValueError):
            AssetRef('abo-glb', 'item', None)
        with self.assertRaises(ValueError):
            AssetRef('future-hf-source', 'item', 'main').validate_selection(huggingface=True)

    def test_unknown_facts_are_preserved_and_not_capabilities(self):
        asset = AssetRecord(AssetRef('abo-glb', 'item', 'main'), 'Cabinet',
                            license={'status': 'unknown', 'license': None},
                            physics={'joint_count': {'value': 2, 'evidence': 'declared'},
                                     'mass_kg': {'value': None, 'evidence': 'unknown'}},
                            capabilities={'openable': {'value': None, 'evidence': 'unknown'}})
        self.assertIsNone(asset.to_dict()['dimensions_m'])
        self.assertIsNone(asset.to_dict()['physics']['mass_kg']['value'])
        self.assertFalse(asset.has_capability('openable'))
        self.assertFalse(asset.has_capability('joint_count'))
        self.assertEqual(asset.evidence_level, 'unknown')
        self.assertEqual(AssetRecord.from_dict(asset.to_dict()).to_dict(), asset.to_dict())
        for changes in ({'dimensions_m': (0, 1, 1)}, {'dimensions_m': (1, float('nan'), 1)},
                        {'license': {'status': 'known', 'license': None}},
                        {'physics': {'mass_kg': {'value': 0, 'evidence': 'inspected'}}},
                        {'physics': {'mass_kg': {'value': 1, 'evidence': 'unknown'}}},
                        {'capabilities': {'openable': {'value': True, 'evidence': 'unknown'}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(asset, **changes)

    def test_schema_and_json_round_trips_and_stable_identity(self):
        source = load_registry().get('abo-glb')
        self.assertEqual(validate_source(json.loads(json.dumps(source.to_dict()))), source)
        target = BackendTarget('physx', 'detected-6.2', 'detected-25', 'linux-x86_64')
        self.assertEqual(BackendTarget.from_dict(target.to_dict()), target)
        first = {'parameters': {'mass_kg': 1, 'path': 'source/a'}, 'toolchain': {'version': '1'},
                 'created_at': 'yesterday', 'job_id': 'one', 'temporary_path': '/tmp/one'}
        second = dict(first, created_at='today', job_id='two', temporary_path='/tmp/two')
        self.assertEqual(stable_hash(first), stable_hash(second))
        self.assertNotEqual(stable_hash(first), stable_hash(dict(first, parameters={'mass_kg': 2, 'path': 'source/a'})))
        self.assertNotEqual(stable_hash(first), stable_hash(dict(first, parameters={'mass_kg': 1, 'path': 'source/b'})))
        self.assertNotEqual(stable_hash(first), stable_hash(dict(first, toolchain={'version': '2'})))
        self.assertEqual(canonical_json({'b': 1, 'a': 2}), '{"a":2,"b":1}')
        for bad in ({'x': float('inf')}, {1: 'nonstring key'}, {'x': object()}):
            with self.assertRaises(ValueError):
                stable_hash(bad)

    def test_search_bounds_and_failure_semantics(self):
        request = SearchRequest('杯子')
        self.assertEqual((request.limit, request.max_providers, request.deadline_seconds), (8, 3, 12))
        self.assertFalse(request.allow_unknown_constraints)
        for changes in ({'limit': 21}, {'limit': True}, {'max_providers': 4},
                        {'deadline_seconds': float('nan')}, {'max_acquire_bytes': -1},
                        {'size_range_m': (2, 1)}, {'size_range_m': (None, None)},
                        {'allow_unknown_constraints': 'yes'}, {'source_ids': 'abo-glb'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(request, **changes)
        with self.assertRaises(ValueError):
            SearchRequest.from_dict({'query': 'cup', 'silent_unknown_field': True})
        with self.assertRaises(ValueError):
            SearchPage('query', 'ok', (), None, {'abo-glb': {'status': 'timeout'}}, {}, 12)
        page = SearchPage('query', 'unavailable', (), None, {'abo-glb': {'status': 'timeout'}}, {}, 12)
        self.assertEqual(SearchPage.from_dict(page.to_dict()), page)


if __name__ == '__main__':
    unittest.main()
