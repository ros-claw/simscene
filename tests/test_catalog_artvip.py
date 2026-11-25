"""Metadata-only ArtVIP admission and selected native package planning."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from simscene.catalog import SearchRequest, load_registry
from simscene.catalog.providers.factory import make_provider
from simscene.catalog.network import MetadataError
from simscene.catalog.registry import Registry
from simscene.catalog.search import resolve_asset, search_assets
from simscene.catalog.store import CatalogStore
from simscene.acquisition.plans import make_plan
from simscene.acquisition.dispatch import acquire_selected
from test_asset_plans import config_fixture, runtime_fixture
from test_catalog_abo import metadata_server

REVISION = 'd22f2095bc9db29fdd4b60f4a3c4f8177e1f5e9e'
FOLDER = 'Articulated_objects/small_furniture/door/door002'
ROOT = FOLDER + '/model_door.usd'
SHA = 'a5e596ad9be87033a4f9e02056d1b3baf125355ef0495a5c63b92d9004cec2be'
TREE_PATH = '/api/datasets/X-Humanoid/ArtVIP/tree/' + REVISION + '/' + FOLDER + '?recursive=false&expand=true&limit=100'


def tree_payload():
    # The official tree metadata describes the root file and directories only.
    return json.dumps([
        {'type': 'directory', 'oid': 'a' * 40, 'size': 0, 'path': FOLDER + '/resource'},
        {'type': 'file', 'oid': 'b' * 40, 'size': 22536, 'path': ROOT,
         'lfs': {'oid': SHA, 'size': 22536, 'pointerSize': 130}},
    ]).encode()


class ArtVIPProviderTests(unittest.TestCase):
    def test_artvip_is_available_only_by_explicit_source_selection(self):
        registry = load_registry()
        self.assertIn('artvip', {source.source_id for source in registry.select(('artvip',))})
        self.assertNotIn('artvip', {source.source_id for source in registry.select()})

    def test_search_is_metadata_only_and_plan_freezes_root_without_claiming_closure(self):
        payload = tree_payload()
        with tempfile.TemporaryDirectory() as directory, metadata_server({TREE_PATH: {'payload': payload}}) as (url, trace):
            source = load_registry().get('artvip')
            config = config_fixture(directory)
            provider = make_provider(CatalogStore(config['index_directory']), source, config)
            provider.base_url = url
            request = SearchRequest('door', source_ids=('artvip',), limit=10)
            with patch('subprocess.Popen', side_effect=AssertionError('no runtime or downloader during metadata search')):
                page = search_assets(request, providers={'artvip': provider}, index_directory=config['index_directory'])
                warm = search_assets(request, providers={'artvip': provider}, index_directory=config['index_directory'])
            self.assertEqual(page.status, 'ok')
            self.assertEqual(len(page.items), 1)
            self.assertEqual([item['path'] for item in trace], [TREE_PATH])
            self.assertEqual(page.budgets['metadata_bytes'], len(payload))
            self.assertEqual(page.budgets['model_bytes'], 0)
            self.assertEqual(warm.budgets['metadata_bytes'], 0)
            record = resolve_asset(page.items[0]['ref'], index_directory=config['index_directory'])
            self.assertEqual(record.entry_path, ROOT)
            self.assertEqual(record.ref.revision, REVISION)
            self.assertIsNone(record.physics)
            self.assertFalse(record.has_capability('declared_single_joint'))
            self.assertEqual(record.license['basis'], 'pinned_ArtVIP_dataset_card')
            self.assertEqual(record.license['card_sha256'], '3193c5d74ef7f1d4777fe0ff77d3f9f2f4c436969ea1802726da177897003f63')
            self.assertTrue(record.license['card_url'].endswith('/' + REVISION + '/README.md'))
            self.assertIsNone(record.availability['estimated_download_bytes'])
            descriptor = record.availability['acquisition']
            self.assertEqual(descriptor['files'], [{'path': ROOT, 'size': 22536, 'sha256': SHA}])
            self.assertFalse(descriptor['files_complete'])
            params = {'source_physics_policy': 'preserve_valid', 'proxy_tolerance_m': .002}
            plan = make_plan(record.ref, 'articulated_prop_v1', params, record=record,
                             runtime=runtime_fixture(), config=config)
            self.assertTrue(plan['ready_to_fetch'])
            self.assertFalse(plan['files_complete'])
            self.assertEqual(plan['content_identity'], 'pending_acquisition_content_lock')
            with patch('simscene.acquisition.hf_package.acquire_hf_package', return_value={'routed': True}):
                self.assertEqual(acquire_selected(plan, config=config), {'routed': True})

    def test_invalid_tree_never_replaces_a_previous_good_index(self):
        routes = {TREE_PATH: {'payload': tree_payload()}}
        source = load_registry().get('artvip')
        root = json.loads(tree_payload())[1]
        cases = [
            [dict(root, lfs={'oid': 'not-a-sha', 'size': 22536})],
            [dict(root, lfs={'oid': SHA, 'size': 1})],
            [root, dict(root, path=FOLDER + '/another.usd')],
            [dict(root, path=FOLDER + '/../outside.usd')],
            [dict(root, path=FOLDER + '/resource/material.usd')],
        ]
        with tempfile.TemporaryDirectory() as directory, metadata_server(routes) as (url, _):
            provider = make_provider(CatalogStore(directory), source, config_fixture(directory))
            provider.base_url = url
            provider.refresh()
            previous = provider.snapshot
            record = provider.search(SearchRequest('door')).items[0]
            for payload in cases:
                routes[TREE_PATH]['payload'] = json.dumps(payload).encode()
                with self.subTest(payload=payload), self.assertRaises(MetadataError):
                    provider.refresh()
                self.assertEqual(provider.snapshot, previous)
                self.assertEqual(provider.resolve(record.ref), record)

    def test_paginated_tree_is_rejected_instead_of_silently_indexing_a_partial_directory(self):
        source = load_registry().get('artvip')
        with tempfile.TemporaryDirectory() as directory:
            provider = make_provider(CatalogStore(directory), source, config_fixture(directory))
            def truncated(_url, **kwargs):
                kwargs['response_metadata']['link'] = '<https://example.invalid/next>; rel="next"'
                return tree_payload()
            with patch('simscene.catalog.providers.artvip.fetch_metadata', side_effect=truncated):
                with self.assertRaises(MetadataError):
                    provider.refresh()
            self.assertEqual(provider.snapshot, 'index_not_refreshed')

    def test_changed_explicit_selection_cannot_resolve_stale_index(self):
        source = load_registry().get('artvip')
        with tempfile.TemporaryDirectory() as directory, metadata_server({TREE_PATH: {'payload': tree_payload()}}) as (url, _):
            store = CatalogStore(directory)
            old = make_provider(store, source, config_fixture(directory))
            old.base_url = url
            record = old.search(SearchRequest('door')).items[0]
            changed = replace(source, metadata_entries=(replace(source.metadata_entries[0], path=FOLDER + '_other'),))
            new = make_provider(store, changed, config_fixture(directory))
            self.assertEqual(new.snapshot, 'index_not_refreshed')
            with self.assertRaisesRegex(ValueError, 'stale'):
                new.resolve(record.ref)

    def test_removed_source_cannot_resolve_a_cached_artvip_record(self):
        source = load_registry().get('artvip')
        with tempfile.TemporaryDirectory() as directory, metadata_server({TREE_PATH: {'payload': tree_payload()}}) as (url, _):
            provider = make_provider(CatalogStore(directory), source, config_fixture(directory))
            provider.base_url = url
            record = provider.search(SearchRequest('door')).items[0]
            with patch('simscene.catalog.search.load_registry', return_value=Registry(())):
                with self.assertRaisesRegex(ValueError, 'configured registry'):
                    resolve_asset(record.ref, index_directory=directory)

    def test_frozen_plan_cannot_download_after_the_selected_registration_is_revoked(self):
        source = load_registry().get('artvip')
        selected = source.metadata_entries[0]
        other = replace(selected, path=FOLDER + '_other')
        original = replace(source, metadata_entries=(selected, other))
        with tempfile.TemporaryDirectory() as directory, metadata_server({TREE_PATH: {'payload': tree_payload()}}) as (url, _):
            config = config_fixture(directory)
            registry_path = Path(directory) / 'registry.json'
            config['registry_path'] = str(registry_path)
            registry_path.write_text(json.dumps(Registry((original,)).to_dict()))
            provider = make_provider(CatalogStore(config['index_directory']), source, config)
            provider.base_url = url
            record = provider.search(SearchRequest('door')).items[0]
            plan = make_plan(record.ref, 'articulated_prop_v1',
                             {'source_physics_policy': 'preserve_valid', 'proxy_tolerance_m': .002},
                             record=record, runtime=runtime_fixture(), config=config)
            self.assertTrue(plan['ready_to_fetch'])
            with patch('simscene.acquisition.hf_package.acquire_hf_package', return_value={'routed': True}) as download:
                self.assertEqual(acquire_selected(plan, config=config), {'routed': True})
                download.assert_called_once()
            revised = 'f' * 40
            changes = {
                'removed': replace(original, metadata_entries=(other,)),
                'path_changed': replace(original, metadata_entries=(replace(selected, path=FOLDER + '_renamed'), other)),
                'revision_changed': replace(original, metadata_entries=(replace(selected, revision=revised), replace(other, revision=revised))),
                'adapter_changed_and_removed': replace(original, adapter='simready_package', metadata_entries=(other,)),
            }
            for name, changed in changes.items():
                with self.subTest(change=name):
                    registry_path.write_text(json.dumps(Registry((changed,)).to_dict()))
                    with patch('simscene.acquisition.hf_package.acquire_hf_package') as download:
                        with self.assertRaisesRegex(ValueError, 'ArtVIP'):
                            acquire_selected(plan, config=config)
                        download.assert_not_called()

    def test_plan_cannot_dispatch_a_package_or_root_outside_its_selected_directory(self):
        source = load_registry().get('artvip')
        with tempfile.TemporaryDirectory() as directory, metadata_server({TREE_PATH: {'payload': tree_payload()}}) as (url, _):
            config = config_fixture(directory)
            provider = make_provider(CatalogStore(config['index_directory']), source, config)
            provider.base_url = url
            record = provider.search(SearchRequest('door')).items[0]
            for name in ('package_path', 'root_directory', 'noncanonical_root'):
                with self.subTest(mismatch=name):
                    availability = copy.deepcopy(record.availability)
                    descriptor = availability['acquisition']
                    root = ROOT
                    if name == 'package_path':
                        descriptor['package_path'] = FOLDER + '_other'
                    elif name == 'root_directory':
                        root = FOLDER + '/resource/material.usd'
                    else:
                        root = FOLDER + '//model_door.usd'
                    descriptor['path'] = root
                    descriptor['files'][0]['path'] = root
                    changed = replace(record, entry_path=root, availability=availability)
                    plan = make_plan(changed.ref, 'articulated_prop_v1',
                                     {'source_physics_policy': 'preserve_valid', 'proxy_tolerance_m': .002},
                                     record=changed, runtime=runtime_fixture(), config=config)
                    self.assertTrue(plan['ready_to_fetch'])
                    with patch('simscene.acquisition.hf_package.acquire_hf_package') as download:
                        with self.assertRaisesRegex(ValueError, 'ArtVIP'):
                            acquire_selected(plan, config=config)
                        download.assert_not_called()

    def test_an_unreviewed_revision_does_not_inherit_the_pinned_card_license(self):
        source = load_registry().get('artvip')
        unknown_revision = 'f' * 40
        changed = replace(source, metadata_entries=(replace(source.metadata_entries[0], revision=unknown_revision),))
        tree = TREE_PATH.replace(REVISION, unknown_revision)
        with tempfile.TemporaryDirectory() as directory, metadata_server({tree: {'payload': tree_payload()}}) as (url, _):
            config = config_fixture(directory)
            provider = make_provider(CatalogStore(config['index_directory']), changed, config)
            provider.base_url = url
            record = provider.search(SearchRequest('door')).items[0]
            self.assertEqual(record.license['status'], 'unknown')
            self.assertIsNone(record.license['license'])
            plan = make_plan(record.ref, 'articulated_prop_v1',
                             {'source_physics_policy': 'preserve_valid', 'proxy_tolerance_m': .002},
                             record=record, runtime=runtime_fixture(), config=config)
            self.assertFalse(plan['ready_to_fetch'])
            self.assertIn('license_unresolved', {reason['code'] for reason in plan['blocking_reasons']})


if __name__ == '__main__':
    unittest.main()
