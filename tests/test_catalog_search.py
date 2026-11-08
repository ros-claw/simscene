"""Federation failure, constraint and pagination tests with actual HTTP fixtures."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from simscene.catalog import AssetRecord, AssetRef, SearchRequest, load_registry
from simscene.catalog.network import fetch_metadata
from simscene.catalog.providers.base import Provider, ProviderPage
from simscene.catalog.providers.abo import ABOProvider
from simscene.catalog.providers.nvidia import NvidiaProvider
from simscene.catalog.search import CursorInvalid, constraint_decision, resolve_asset, search_assets
from simscene.catalog.store import CatalogStore
from simscene.catalog.registry import Registry
from test_catalog_abo import metadata_server, abo_row, INDEX_PATH


def audited_registry():
    return Registry(tuple(replace(source, state='audited', default_enabled=False)
                          for source in load_registry().sources))


def asset(source='abo-glb', identity='item', **changes):
    return AssetRecord(AssetRef(source, identity, 'a' * 40 if source in ('abo-glb','gso-glb','usdcraft') else 'metadata:one'),
                       'Cup ' + identity, **changes)


class HTTPProvider(Provider):
    def __init__(self, source_id, url, *, snapshot='fixture-1'):
        self.source_id = source_id
        self.url = url
        self.version = snapshot
        self.calls = 0
    @property
    def snapshot(self):
        return self.version
    def search(self, request):
        self.calls += 1
        data = fetch_metadata(self.url, deadline=self.deadline, max_bytes=2 * 1024 * 1024,
                              ledger=self.ledger)
        return ProviderPage(tuple(AssetRecord.from_dict(row) for row in json.loads(data)), self.snapshot)


class CatalogSearchTest(unittest.TestCase):
    def test_real_http_one_timeout_other_hits_is_partial_all_failed_is_unavailable(self):
        routes = {'/success': {'payload': [asset().to_dict()]},
                  '/timeout': {'payload': b'[{}]', 'chunk': 1, 'delay': 0.1},
                  '/error': {'status': 500, 'payload': b'failure'}}
        with tempfile.TemporaryDirectory() as directory, metadata_server(routes) as (url, trace):
            providers = {'abo-glb': HTTPProvider('abo-glb', url + '/success'),
                         'nvidia-usd-search': HTTPProvider('nvidia-usd-search', url + '/timeout')}
            request = SearchRequest('cup', source_ids=tuple(providers), deadline_seconds=0.17)
            started = time.monotonic()
            page = search_assets(request, providers=providers, registry=audited_registry(), index_directory=directory)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(page.status, 'partial')
            self.assertEqual(len(page.items), 1)
            self.assertEqual(page.source_statuses['nvidia-usd-search']['status'], 'timeout')
            self.assertTrue(page.items[0]['experimental'])
            self.assertEqual(page.budgets['model_bytes'], 0)
            providers = {key: HTTPProvider(key, url + '/error') for key in providers}
            page = search_assets(replace(request, deadline_seconds=1), providers=providers, registry=audited_registry(), index_directory=directory)
            self.assertEqual(page.status, 'unavailable')
            self.assertEqual(page.items, ())
            self.assertTrue(all(s['status'] == 'unavailable' for s in page.source_statuses.values()))

    def test_production_defaults_query_three_verified_sources_without_experimental_flag(self):
        routes = {'/notebook': {'payload': [asset().to_dict()]},
                  '/workbench': {'payload': [asset('nvidia-usd-search', 'table').to_dict()]},
                  '/scan': {'payload': [asset('gso-glb','box').to_dict()]}}
        with tempfile.TemporaryDirectory() as directory, metadata_server(routes) as (url, trace):
            providers = {'abo-glb': HTTPProvider('abo-glb', url + '/notebook'),
                         'nvidia-usd-search': HTTPProvider('nvidia-usd-search', url + '/workbench'),
                         'gso-glb':HTTPProvider('gso-glb',url+'/scan')}
            page = search_assets(SearchRequest('cup'), providers=providers, index_directory=directory)
            self.assertEqual(page.status, 'ok')
            self.assertEqual(set(page.source_statuses), {'abo-glb', 'nvidia-usd-search','gso-glb'})
            self.assertEqual(len(page.items), 3)
            self.assertTrue(all(not item['experimental'] for item in page.items))
            self.assertTrue(all(provider.calls == 1 for provider in providers.values()))
            self.assertTrue(all(not value['experimental'] for value in page.source_statuses.values()))

    def test_first_abo_query_refreshes_metadata_and_cursor_uses_the_new_index_generation(self):
        rows = [abo_row('ITEM' + str(number)) for number in range(7)]
        payload = ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()
        with tempfile.TemporaryDirectory() as directory, metadata_server({INDEX_PATH: {'payload': payload}}) as (url, trace):
            provider = ABOProvider(CatalogStore(directory), base_url=url)
            request = SearchRequest('shredder', source_ids=('abo-glb',), limit=3)
            page = search_assets(request, providers={'abo-glb': provider}, index_directory=directory)
            self.assertEqual(page.status, 'ok')
            self.assertEqual(len(page.items), 3)
            self.assertEqual(page.budgets['metadata_bytes'], len(payload))
            self.assertEqual(page.budgets['request_metadata_bytes'], len(payload))
            self.assertEqual(page.budgets['model_bytes'], 0)
            self.assertEqual(page.budgets['preview_bytes'], 0)
            self.assertIsNotNone(page.next_cursor)
            identities = [item['ref']['asset_id'] for item in page.items]
            while page.next_cursor:
                page = search_assets(replace(request, cursor=page.next_cursor), providers={'abo-glb': provider}, index_directory=directory)
                self.assertEqual(page.budgets['metadata_bytes'], len(payload))
                self.assertEqual(page.budgets['request_metadata_bytes'], 0)
                self.assertEqual(page.budgets['request_preview_bytes'], 0)
                self.assertEqual(page.budgets['transfer_scope'], 'frozen_query_snapshot')
                identities.extend(item['ref']['asset_id'] for item in page.items)
            self.assertEqual(len(identities), 7)
            self.assertEqual(len(set(identities)), 7)
            self.assertEqual([item['path'] for item in trace], [INDEX_PATH])
            warm = search_assets(request, providers={'abo-glb': provider}, index_directory=directory)
            self.assertEqual(warm.budgets['metadata_bytes'], 0)
            self.assertEqual([item['path'] for item in trace], [INDEX_PATH])

    def test_first_abo_schema_failure_is_unavailable_instead_of_successful_empty(self):
        with tempfile.TemporaryDirectory() as directory, metadata_server({INDEX_PATH: {'payload': b'{"id":"missing-schema"}\n'}}) as (url, trace):
            store = CatalogStore(directory)
            provider = ABOProvider(store, base_url=url)
            with patch('simscene.preparation.jobs.start', side_effect=AssertionError('runtime forbidden')):
                page = search_assets(SearchRequest('shredder', source_ids=('abo-glb',)), providers={'abo-glb': provider}, index_directory=directory)
            self.assertEqual(page.status, 'unavailable')
            self.assertEqual(page.items, ())
            self.assertEqual(page.source_statuses['abo-glb']['status'], 'unavailable')
            self.assertIsNone(store.snapshot('abo-glb'))
            self.assertEqual([item['path'] for item in trace], [INDEX_PATH])

    def test_successful_empty_is_distinct_from_no_enabled_sources(self):
        with tempfile.TemporaryDirectory() as directory, metadata_server({'/empty': {'payload': []}}) as (url, trace):
            provider = HTTPProvider('abo-glb', url + '/empty')
            default = search_assets(SearchRequest('cup'), providers={'abo-glb': provider}, registry=audited_registry(), index_directory=directory)
            self.assertEqual(default.status, 'unavailable')
            self.assertEqual(provider.calls, 0)
            explicit = search_assets(SearchRequest('cup', source_ids=('abo-glb',)),
                                     providers={'abo-glb': provider}, registry=audited_registry(), index_directory=directory)
            self.assertEqual(explicit.status, 'ok')
            self.assertEqual(explicit.items, ())
            self.assertEqual(provider.calls, 1)
            self.assertTrue(explicit.source_statuses['abo-glb']['experimental'])

    def test_unknown_constraints_are_not_matches_and_joint_count_is_not_openable(self):
        unknown = asset(physics={'joint_count': {'value': 2, 'evidence': 'declared'}})
        request = SearchRequest('cup', usage_policy='commercial', size_range_m=(0.01, 1), max_acquire_bytes=1000)
        strict = constraint_decision(unknown, request)
        self.assertFalse(strict['include'])
        allowed = constraint_decision(unknown, replace(request, allow_unknown_constraints=True))
        self.assertTrue(allowed['include'])
        self.assertFalse(allowed['matched'])
        self.assertEqual(set(allowed['unknown']), {'usage_policy', 'size_range_m', 'max_acquire_bytes'})
        capability = constraint_decision(unknown, replace(request, required_capabilities=('openable',), allow_unknown_constraints=True))
        self.assertFalse(capability['include'])
        known = replace(unknown, license={'status': 'known', 'license': 'CC-BY-4.0'}, dimensions_m=(0.1, 0.2, 0.3),
                        availability={'estimated_download_bytes': 500})
        self.assertTrue(constraint_decision(known, request)['matched'])
        self.assertFalse(constraint_decision(replace(known, availability={'estimated_download_bytes': 5000}), request)['include'])
        self.assertFalse(constraint_decision(replace(known, license={'status': 'restricted', 'license': 'CC-BY-NC-4.0'}), request)['include'])

    def test_cursor_freezes_candidates_and_binds_query_filters_and_index_generation(self):
        records = [asset(identity=str(number)) for number in range(13)]
        routes = {'/items': {'payload': [r.to_dict() for r in records]}}
        with tempfile.TemporaryDirectory() as directory, metadata_server(routes) as (url, trace):
            provider = HTTPProvider('abo-glb', url + '/items')
            providers = {'abo-glb': provider}
            request = SearchRequest('cup', source_ids=('abo-glb',), limit=5)
            page = search_assets(request, providers=providers, index_directory=directory)
            identities = [item['ref']['asset_id'] for item in page.items]
            self.assertIsNotNone(page.next_cursor)
            cursor = page.next_cursor
            routes['/items']['payload'] = []  # Remote index changes do not disturb this frozen local buffer.
            while page.next_cursor:
                page = search_assets(replace(request, cursor=page.next_cursor), providers=providers, index_directory=directory)
                identities.extend(item['ref']['asset_id'] for item in page.items)
            self.assertEqual(len(identities), 13)
            self.assertEqual(len(set(identities)), 13)
            self.assertEqual(identities, [str(n) for n in range(13)])
            self.assertEqual(provider.calls, 1)
            for changed in (replace(request, query='chair', cursor=cursor),
                            replace(request, formats=('usd',), cursor=cursor)):
                with self.assertRaises(CursorInvalid):
                    search_assets(changed, providers=providers, index_directory=directory)
            provider.version = 'fixture-2'
            with self.assertRaisesRegex(CursorInvalid, 'snapshot changed'):
                search_assets(replace(request, cursor=cursor), providers=providers, index_directory=directory)
            with self.assertRaises(CursorInvalid):
                search_assets(replace(request, cursor='not a cursor'), providers=providers, index_directory=directory)

    def test_compact_unicode_pages_keep_gap_details_and_persist_full_records(self):
        records = [asset(identity=str(n), category='decoration',
                         license={'status': 'unknown', 'license': None}) for n in range(25)]
        records = [replace(record, title='杯子' * 5000) for record in records]
        with tempfile.TemporaryDirectory() as directory, metadata_server({'/items': {'payload': [r.to_dict() for r in records]}}) as (url, trace):
            provider = HTTPProvider('abo-glb', url + '/items')
            request = SearchRequest('杯子', source_ids=('abo-glb',), limit=20,
                                    usage_policy='commercial', allow_unknown_constraints=True)
            page = search_assets(request, providers={'abo-glb': provider}, index_directory=directory)
            self.assertLessEqual(len(json.dumps(page.to_dict(), ensure_ascii=False).encode()), 12 * 1024)
            self.assertIsNotNone(page.next_cursor)
            item = page.items[0]
            self.assertFalse(item['matched'])
            self.assertIn('usage_policy', item['key_gaps'])
            self.assertIn('runtime_not_verified', item['key_gaps'])
            details = json.loads(Path(item['detail_ref']).read_text())
            self.assertEqual(details['title'], records[0].title)
            resolved = resolve_asset(item['ref'], index_directory=directory)
            self.assertEqual(resolved.title, records[0].title)
            self.assertEqual(len(trace), 1)
            self.assertEqual(page.budgets['original_query'], '杯子')
            self.assertEqual(page.budgets['rewritten_query'], 'cup')

    def test_service_ignoring_image_flag_reports_received_preview_bytes(self):
        hit = {'source': {'asset_url': 'https://assets.example.test/item.usd', 'ext': 'usd'},
               'metadata': {'image': 'data:image/png;base64,' + 'A' * 2048}}
        with tempfile.TemporaryDirectory() as directory, metadata_server({'/search_hybrid': {'payload': {'hits': [hit]}}}) as (url, trace):
            provider = NvidiaProvider(CatalogStore(directory), base_url=url)
            page = search_assets(SearchRequest('item', source_ids=('nvidia-usd-search',)),
                                 providers={'nvidia-usd-search': provider}, index_directory=directory)
            self.assertEqual(page.status, 'ok')
            self.assertGreater(page.budgets['preview_bytes'], 2048)
            self.assertEqual(page.budgets['model_bytes'], 0)
            self.assertIn('inline_preview_received', page.source_statuses['nvidia-usd-search']['warnings'])
            record = resolve_asset(page.items[0]['ref'], index_directory=directory)
            self.assertIsNone(record.provenance['original_metadata']['image'])
            self.assertNotIn('base64', json.dumps(page.to_dict()))

    def test_nvidia_legacy_query_builder_disables_images_and_keeps_unknown_license(self):
        hit = {'source': {'base_key': 'https://assets.example.test/workbench.usd', 'ext': 'usd',
                          'name': 'workbench.usd', 'etag': 'upstream-etag', 'size': 100,
                          'usd_dimensions': {'scaled_bbox_dimension_x': 1.2, 'scaled_bbox_dimension_y': 0.8,
                                             'scaled_bbox_dimension_z': 0.9}}, 'metadata': {}}
        with tempfile.TemporaryDirectory() as directory, metadata_server({'/search_hybrid': {'payload': {'hits': [hit]}}}) as (url, trace):
            provider = NvidiaProvider(CatalogStore(directory), base_url=url)
            page = search_assets(SearchRequest('workbench', source_ids=('nvidia-usd-search',)),
                                 providers={'nvidia-usd-search': provider}, index_directory=directory)
            self.assertEqual(page.status, 'ok')
            self.assertFalse(trace[0]['body']['return_images'])
            self.assertEqual(trace[0]['body']['return_metadata'], True)
            self.assertEqual([r['path'] for r in trace], ['/search_hybrid'])
            self.assertIsNone(page.items[0]['license']['license'])
            record = resolve_asset(page.items[0]['ref'], index_directory=directory)
            self.assertEqual(record.dimensions_m, (1.2, 0.8, 0.9))
            self.assertEqual(record.provenance['asset_url'], 'https://assets.example.test/workbench.usd')
            self.assertEqual(record.availability['content_identity'], 'not_established')
            self.assertIsNone(record.availability['estimated_download_bytes'])


if __name__ == '__main__':
    unittest.main()
