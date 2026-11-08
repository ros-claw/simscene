"""Real local HTTP fixtures prove refresh reads only a pinned metadata index."""
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from simscene.catalog import AssetRef, SearchRequest, load_registry
from simscene.catalog.network import MetadataDeadline, MetadataError, fetch_metadata
from simscene.catalog.providers.abo import ABOProvider
from simscene.catalog.store import CatalogStore

SHA = 'c7c8293fed3b7ab122ef5d7896521a187e0962d7'
INDEX_PATH = '/datasets/codepawl/abo-glb/resolve/' + SHA + '/metadata.jsonl'


def abo_row(identity='B000S6N026', **changes):
    row = {'id': identity, 'file': f'objects/{identity}/{identity}.glb', 'name': 'Paper shredder',
           'product_type': 'office products', 'brand': 'Example', 'color': 'Black',
           'material': None, 'style': 'micro cut', 'size_metres': [0.311, 0.419, 0.2372],
           'catalog_weight_kg': 6.68, 'pack_bytes': 768644, 'source_bytes': 18856172,
           'lods': [{'file': f'lods/{identity}/{identity}_lod1.glb', 'bytes': 469828}]}
    return dict(row, **changes)


@contextmanager
def metadata_server(routes):
    trace = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def handle_request(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            trace.append({'path': self.path, 'method': self.command,
                          'body': json.loads(body) if body else None})
            route = routes.get(self.path, {'status': 404, 'payload': b'not found'})
            payload = route.get('payload', b'')
            if not isinstance(payload, bytes):
                payload = json.dumps(payload).encode()
            self.send_response(route.get('status', 200))
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            chunk = route.get('chunk', len(payload) or 1)
            try:
                for offset in range(0, len(payload), chunk):
                    if route.get('delay'):
                        time.sleep(route['delay'])
                    self.wfile.write(payload[offset:offset + chunk])
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        do_GET = handle_request
        do_POST = handle_request
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        with patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}):
            yield 'http://127.0.0.1:' + str(server.server_port), trace
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class ABOProviderTest(unittest.TestCase):
    def test_explicit_pinned_refresh_index_search_resolve_without_model_fetch(self):
        payload = (json.dumps(abo_row()) + '\n').encode()
        with tempfile.TemporaryDirectory() as directory, metadata_server({INDEX_PATH: {'payload': payload}}) as (url, trace):
            store = CatalogStore(directory)
            provider = ABOProvider(store, base_url=url).configure(time.monotonic() + 3, [])
            self.assertEqual(trace, [])
            report = provider.refresh()
            self.assertEqual(report['records'], 1)
            self.assertEqual(report['model_bytes'], 0)
            page = provider.search(SearchRequest('shredder'))
            record = page.items[0]
            self.assertEqual(record.ref, AssetRef('abo-glb', 'B000S6N026', SHA))
            self.assertEqual(record.availability['estimated_download_bytes'], 768644)
            self.assertEqual(record.dimensions_m, (0.311, 0.419, 0.2372))
            self.assertIsNone(record.physics)
            self.assertFalse(record.has_capability('openable'))
            self.assertEqual(provider.resolve(record.ref), record)
            self.assertEqual([r['path'] for r in trace], [INDEX_PATH])
            self.assertEqual(provider.ledger[0]['category'], 'metadata')
            self.assertEqual(provider.ledger[0]['bytes'], len(payload))
            with self.assertRaises(ValueError):
                provider.resolve(AssetRef('abo-glb', record.ref.asset_id, 'main'))

    def test_first_search_refreshes_only_pinned_jsonl_then_warm_search_has_no_http(self):
        payload = (json.dumps(abo_row()) + '\n').encode()
        model_path = '/datasets/codepawl/abo-glb/resolve/' + SHA + '/objects/B000S6N026/B000S6N026.glb'
        texture_path = '/datasets/codepawl/abo-glb/resolve/' + SHA + '/thumbs/B000S6N026.webp'
        routes = {INDEX_PATH: {'payload': payload}, model_path: {'payload': b'model must not be fetched'},
                  texture_path: {'payload': b'preview must not be fetched'}}
        with tempfile.TemporaryDirectory() as directory, metadata_server(routes) as (url, trace):
            ledger = []; deadline = time.monotonic() + 3
            provider = ABOProvider(CatalogStore(directory), base_url=url).configure(deadline, ledger)
            with patch('simscene.preparation.jobs.start', side_effect=AssertionError('runtime preparation forbidden')), patch('subprocess.Popen', side_effect=AssertionError('SDK forbidden')):
                page = provider.search(SearchRequest('shredder'))
                self.assertEqual(len(page.items), 1)
                self.assertEqual(page.bytes_read, len(payload))
                self.assertEqual(provider.deadline, deadline)
                self.assertIs(provider.ledger, ledger)
                self.assertEqual([item['path'] for item in trace], [INDEX_PATH])
                self.assertTrue(all(item['category'] == 'metadata' for item in ledger))
                warm = provider.search(SearchRequest('shredder'))
                self.assertEqual(warm.items, page.items)
                self.assertEqual(warm.bytes_read, 0)
                self.assertEqual([item['path'] for item in trace], [INDEX_PATH])

    def test_first_search_schema_budget_and_deadline_failures_publish_no_index(self):
        fixtures = (
            ('schema', {'payload': json.dumps({'id': 'missing-fields'}).encode()}, 3, 1024),
            ('size', {'payload': (json.dumps(abo_row()) + '\n').encode()}, 3, 32),
            ('deadline', {'payload': b'x' * 30, 'chunk': 1, 'delay': 0.03}, 0.1, 1024),
        )
        for name, response, seconds, limit in fixtures:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, metadata_server({INDEX_PATH: response}) as (url, trace):
                store = CatalogStore(directory)
                provider = ABOProvider(store, base_url=url, max_index_bytes=limit).configure(time.monotonic() + seconds, [])
                with patch('simscene.preparation.jobs.start', side_effect=AssertionError('runtime forbidden')), patch('subprocess.Popen', side_effect=AssertionError('SDK forbidden')):
                    with self.assertRaises(MetadataError):
                        provider.search(SearchRequest('shredder'))
                self.assertIsNone(store.snapshot('abo-glb'))
                self.assertEqual(provider.snapshot, 'index_not_refreshed')
                self.assertEqual(store.search('abo-glb', 'shredder'), ())
                self.assertEqual([item['path'] for item in trace], [INDEX_PATH])

    def test_schema_drift_and_unsafe_paths_preserve_existing_good_index(self):
        route = {'payload': json.dumps(abo_row()).encode()}
        with tempfile.TemporaryDirectory() as directory, metadata_server({INDEX_PATH: route}) as (url, trace):
            provider = ABOProvider(CatalogStore(directory), base_url=url).configure(time.monotonic() + 3, [])
            provider.refresh()
            snapshot = provider.snapshot
            for row in ({'id': 'missing fields'}, abo_row(file='../outside.glb'),
                        abo_row(pack_bytes=True), abo_row(size_metres=[0, 1, 1])):
                route['payload'] = json.dumps(row).encode()
                with self.subTest(row=row), self.assertRaisesRegex(MetadataError, 'schema changed'):
                    provider.refresh()
                self.assertEqual(provider.snapshot, snapshot)
                self.assertEqual(len(provider.search(SearchRequest('shredder')).items), 1)

    def test_metadata_budget_and_absolute_deadline_apply_to_actual_reads(self):
        routes = {'/large': {'payload': b'x' * 500},
                  '/slow': {'payload': b'x' * 50, 'chunk': 1, 'delay': 0.03},
                  '/failure': {'status': 500, 'payload': b'server failed'}}
        with metadata_server(routes) as (url, trace):
            ledger = []
            with self.assertRaises(MetadataError):
                fetch_metadata(url + '/large', deadline=time.monotonic() + 1, max_bytes=32, ledger=ledger)
            self.assertLessEqual(ledger[-1]['bytes'], 33)
            start = time.monotonic()
            with self.assertRaises(MetadataDeadline):
                fetch_metadata(url + '/slow', deadline=start + 0.13, max_bytes=500, ledger=ledger)
            self.assertLess(time.monotonic() - start, 0.4)
            self.assertEqual(ledger[-1]['status'], 'timeout')
            with self.assertRaisesRegex(MetadataError, 'HTTP 500'):
                fetch_metadata(url + '/failure', deadline=time.monotonic() + 1, max_bytes=500, ledger=ledger)
            self.assertEqual(ledger[-1]['http_status'], 500)

    def test_ledger_and_failures_do_not_expose_signed_query_or_credentials(self):
        with metadata_server({'/failure?token=secret': {'status': 500, 'payload': b'secret'}}) as (url, trace):
            ledger = []
            with self.assertRaises(MetadataError) as raised:
                fetch_metadata(url + '/failure?token=secret', deadline=time.monotonic() + 1,
                               max_bytes=100, ledger=ledger, headers={'Authorization': 'Bearer hidden'})
            self.assertNotIn('secret', str(raised.exception))
            self.assertNotIn('secret', json.dumps(ledger))
            self.assertNotIn('hidden', json.dumps(ledger))
            self.assertEqual(ledger[0]['endpoint'], url + '/failure')

    def test_sqlite_text_fallback_remains_searchable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(directory)
            store.fts = False
            provider = ABOProvider(store)
            record = provider._record(abo_row())
            store.replace_index('abo-glb', [record], 'fixture-snapshot')
            self.assertEqual(store.search('abo-glb', 'shredder')[0], record)
            self.assertEqual(store.search('abo-glb', 'nonexistent'), ())


if __name__ == '__main__':
    unittest.main()
