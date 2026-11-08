"""Repository discovery failure contracts, exercised through real local HTTP."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from simscene.catalog.discovery import discover_sources, DiscoveryCursorInvalid
from simscene.catalog.providers.hf_discovery import HFDiscoveryProvider
from simscene.catalog.network import fetch_metadata, MetadataError

SHA = 'a' * 40


def repo(name='org/models', **changes):
    return dict({'id': name, 'sha': SHA, 'private': False, 'gated': False,
                 'tags': ['license:cc-by-4.0'], 'cardData': {'license': 'cc-by-4.0'}}, **changes)


@contextmanager
def api_server(router):
    trace = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            trace.append(self.path)
            route = router(self.path, self.server.base_url)
            payload = route.get('payload', b'')
            if not isinstance(payload, bytes):
                payload = json.dumps(payload).encode()
            self.send_response(route.get('status', 200))
            for key, value in route.get('headers', {}).items():
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                for start in range(0, len(payload), route.get('chunk', len(payload) or 1)):
                    if route.get('delay'):
                        time.sleep(route['delay'])
                    self.wfile.write(payload[start:start + route.get('chunk', len(payload) or 1)])
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.base_url = 'http://127.0.0.1:' + str(server.server_port)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        with patch.dict(os.environ, {'no_proxy': '127.0.0.1,localhost', 'NO_PROXY': '127.0.0.1,localhost'}):
            yield server.base_url, trace
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=1)


def link(base, path, cursor):
    parsed = urlsplit(path); query = parse_qs(parsed.query)
    query['cursor'] = [cursor]
    return '<' + base + parsed.path + '?' + urlencode({k: v[0] for k, v in query.items()}) + '>; rel="next"'


class CatalogDiscoveryTest(unittest.TestCase):
    def discover(self, router, *, budget=None):
        with tempfile.TemporaryDirectory() as directory, api_server(router) as (url, trace):
            page = discover_sources('3d assets', budget, provider=HFDiscoveryProvider(base_url=url), state_directory=directory)
            return page, list(trace)

    def test_empty_first_page_with_next_is_not_mistaken_for_exhaustion(self):
        def router(path, base):
            if urlsplit(path).path == '/api/datasets':
                if 'cursor=' not in path:
                    return {'payload': [], 'headers': {'Link': link(base, path, 'second')}}
                return {'payload': [repo()]}
            return {'payload': []}
        page, trace = self.discover(router)
        self.assertEqual(page.status, 'ok')
        self.assertEqual(len(page.candidates), 1)
        self.assertEqual(page.budgets['pages'], 2)
        self.assertEqual(page.candidates[0]['revision'], SHA)
        self.assertEqual(page.candidates[0]['metadata_layout']['status'], 'unsupported_metadata_layout')
        self.assertFalse(page.candidates[0]['prepared_ready'])
        self.assertEqual(page.budgets['prepared_ready_count'], 0)
        self.assertTrue(all(urlsplit(path).path.startswith('/api/datasets') for path in trace))

    def test_repeated_cursor_stops_with_observable_partial_failure(self):
        def router(path, base):
            if urlsplit(path).path == '/api/datasets':
                suffix = 'two' if 'cursor=' in path else 'one'
                return {'payload': [repo('org/' + suffix)], 'headers': {'Link': link(base, path, 'repeat')}}
            return {'payload': []}
        page, trace = self.discover(router)
        self.assertEqual(page.status, 'partial')
        self.assertIn('repeated_cursor', [item['code'] for item in page.errors])
        self.assertEqual(sum(urlsplit(path).path == '/api/datasets' for path in trace), 2)
        self.assertLessEqual(page.budgets['metadata_bytes'], 4 * 1024**2)

    def test_search_and_tree_links_cannot_escape_origin_query_repository_or_revision(self):
        for attack in ('origin', 'query', 'repo', 'revision'):
            def router(path, base):
                parsed = urlsplit(path)
                if parsed.path == '/api/datasets':
                    if attack in {'origin', 'query'}:
                        target = 'http://169.254.169.254/latest/meta-data' if attack == 'origin' else base + '/api/datasets?search=other&limit=25&full=true&cursor=x'
                        return {'payload': [], 'headers': {'Link': '<' + target + '>; rel="next"'}}
                    return {'payload': [repo()]}
                target = base + '/api/datasets/' + ('other/repo' if attack == 'repo' else 'org/models') + '/tree/' + ('b' * 40 if attack == 'revision' else SHA) + '?recursive=false&limit=20&cursor=x'
                return {'payload': [], 'headers': {'Link': '<' + target + '>; rel="next"'}}
            with self.subTest(attack=attack):
                page, trace = self.discover(router)
                self.assertNotEqual(page.status, 'ok')
                self.assertIn('unsafe_cursor', [item['code'] for item in page.errors])
                self.assertTrue(all('other/repo' not in path and 'b' * 40 not in path for path in trace))
        for origin in ('http://169.254.169.254', 'https://evil.example', 'https://user:secret@huggingface.co'):
            with self.assertRaises(ValueError):
                HFDiscoveryProvider(base_url=origin)

    def test_native_tree_expand_false_default_is_allowed_but_expanded_blobs_are_denied(self):
        for value in ('false', 'true'):
            def router(path, base):
                if urlsplit(path).path == '/api/datasets':
                    return {'payload': [repo()]}
                target = base + urlsplit(path).path + '?expand=' + value + '&recursive=false&limit=20&cursor=next'
                return {'payload': [], 'headers': {'Link': '<' + target + '>; rel="next"'}}
            with self.subTest(expand=value):
                page, trace = self.discover(router)
                if value == 'false':
                    self.assertEqual(page.status, 'ok')
                    self.assertFalse(page.candidates[0]['tree_scope']['complete_root_page'])
                else:
                    self.assertEqual(page.status, 'partial')
                    self.assertIn('unsafe_cursor', [item['code'] for item in page.errors])
                self.assertEqual(len(trace), 2)

    def test_only_exact_pinned_abo_metadata_cache_redirect_can_be_followed(self):
        from simscene.catalog.providers.hf_discovery import DiscoveryTransfer
        row = {'id': 'item', 'file': 'objects/item/item.glb', 'name': 'fixture', 'product_type': 'fixture',
               'size_metres': [1, 1, 1], 'pack_bytes': 100}
        resolve = '/datasets/codepawl/abo-glb/resolve/' + SHA + '/metadata.jsonl'
        cache = '/api/resolve-cache/datasets/codepawl/abo-glb/' + SHA + '/metadata.jsonl'
        def router(path, base):
            if urlsplit(path).path == resolve:
                return {'status': 307, 'headers': {'Location': cache + '?' + urlencode({resolve: '', 'etag': 'fixture'})}, 'payload': b'ignored redirect body'}
            if urlsplit(path).path == cache:
                return {'payload': (json.dumps(row) + '\n').encode()}
            return {'status': 404}
        with api_server(router) as (url, trace):
            transfer = DiscoveryTransfer(time.monotonic() + 1, 32768)
            report = HFDiscoveryProvider(base_url=url).probe_abo_index('codepawl/abo-glb', SHA, transfer)
            self.assertTrue(report['compatible_schema_prefix'])
            self.assertFalse(report['complete_index_inspected'])
            self.assertEqual(len(trace), 2)
            self.assertEqual(transfer.used, len((json.dumps(row) + '\n').encode()))
        # An ordinary API redirect to a metadata-service/private host is never followed.
        page, trace = self.discover(lambda path, base: {'status': 302, 'headers': {'Location': 'http://169.254.169.254/latest/meta-data'}})
        self.assertEqual(page.status, 'unavailable')
        self.assertEqual(len(trace), 1)

    def test_bad_json_oversize_401_403_500_and_timeout_are_not_empty_success(self):
        fixtures = [('json', {'payload': b'[{bad json]'}, {}, 'metadata_schema_changed'),
                    ('nonfinite', {'payload': b'[NaN]'}, {}, 'metadata_schema_changed'),
                    ('size', {'payload': b'x' * 1000}, {'max_bytes': 128}, 'budget_exceeded'),
                    ('401', {'status': 401}, {}, 'access_denied'),
                    ('403', {'status': 403}, {}, 'access_denied'),
                    ('500', {'status': 500}, {}, 'metadata_unavailable'),
                    ('timeout', {'payload': b'x' * 100, 'chunk': 1, 'delay': 0.03}, {'deadline_seconds': 0.1}, 'timeout')]
        for name, response, budget, expected in fixtures:
            with self.subTest(name=name):
                page, trace = self.discover(lambda path, base: response, budget=budget)
                self.assertEqual(page.status, 'unavailable')
                self.assertEqual(page.candidates, ())
                self.assertIn(expected, [item['code'] for item in page.errors])
                self.assertLessEqual(page.budgets['metadata_bytes'], budget.get('max_bytes', 4 * 1024**2))
                self.assertEqual(len(trace), 1)

    def test_gated_repository_is_labeled_without_tree_fetch_or_terms_acceptance(self):
        page, trace = self.discover(lambda path, base: {'payload': [repo(gated='manual')]})
        candidate = page.candidates[0]
        self.assertTrue(candidate['access']['gated'])
        self.assertTrue(candidate['access']['credentials_required'])
        self.assertEqual(candidate['inspection_status'], 'access_restricted')
        self.assertFalse(candidate['default_enabled'])
        self.assertEqual(len(trace), 1)
        self.assertEqual(candidate['physics']['runtime_validation'], 'not_run')

    def test_frozen_pagination_cost_zero_and_query_or_budget_changes_invalidate(self):
        def router(path, base):
            if urlsplit(path).path == '/api/datasets':
                page = 1 if 'cursor=' in path else 0
                return {'payload': [repo('org/model' + str(page))],
                        'headers': {'Link': link(base, path, 'page2')} if not page else {}}
            return {'payload': []}
        with tempfile.TemporaryDirectory() as directory, api_server(router) as (url, trace):
            provider = HFDiscoveryProvider(base_url=url)
            first = discover_sources('objects', {'limit': 1}, provider=provider, state_directory=directory)
            self.assertIsNotNone(first.next_cursor)
            calls = len(trace)
            second = discover_sources('objects', {'limit': 1}, first.next_cursor, provider=provider, state_directory=directory)
            self.assertEqual(len(trace), calls)
            self.assertEqual(second.budgets['request_metadata_bytes'], 0)
            self.assertEqual(second.budgets['metadata_bytes'], first.budgets['metadata_bytes'])
            self.assertNotEqual(second.candidates[0]['repository'], first.candidates[0]['repository'])
            for query, budget in [('changed', {'limit': 1}), ('objects', {'limit': 2})]:
                with self.assertRaises(DiscoveryCursorInvalid):
                    discover_sources(query, budget, first.next_cursor, provider=provider, state_directory=directory)
            with self.assertRaises(DiscoveryCursorInvalid):
                discover_sources('objects', {'limit': 1}, 'https://evil.example/cursor', provider=provider, state_directory=directory)

    def test_no_model_download_execution_or_false_object_count(self):
        def router(path, base):
            if urlsplit(path).path == '/api/datasets':
                return {'payload': [repo()]}
            return {'payload': [{'path': 'all-models.tar', 'type': 'file', 'size': 50000000000},
                                {'path': 'preview.png', 'type': 'file', 'size': 1000000},
                                {'path': 'model.glb', 'type': 'file', 'size': 2000000}]}
        with patch('simscene.preparation.jobs.start', side_effect=AssertionError('runtime forbidden')), patch('subprocess.Popen', side_effect=AssertionError('code execution forbidden')):
            page, trace = self.discover(router)
        candidate = page.candidates[0]
        self.assertEqual(candidate['formats'], ['glb'])
        self.assertIsNone(candidate['acquisition_granularity'])
        self.assertIsNone(candidate['unique_object_count'])
        self.assertTrue(candidate['archive_facts']['present_in_inspected_page'])
        self.assertFalse(candidate['archive_facts']['member_range_access_verified'])
        self.assertEqual(page.budgets['model_bytes'], 0)
        self.assertEqual(page.budgets['preview_bytes'], 0)
        self.assertTrue(all('/resolve/' not in path for path in trace))

    def test_missing_commit_stays_unresolved_and_cannot_trigger_branch_tree_reads(self):
        page, trace = self.discover(lambda path, base: {'payload': [repo(sha='main')]})
        self.assertIsNone(page.candidates[0]['revision'])
        self.assertEqual(page.candidates[0]['inspection_status'], 'unresolved_revision')
        self.assertEqual(len(trace), 1)

    def test_shared_metadata_header_extension_is_bounded_and_preserves_ledger(self):
        with api_server(lambda path, base: {'payload': [], 'headers': {'Link': 'x' * 9000}}) as (url, trace):
            headers = {}; ledger = []
            with self.assertRaises(MetadataError):
                fetch_metadata(url + '/api/datasets', deadline=time.monotonic() + 1,
                               max_bytes=100, response_metadata=headers, ledger=ledger)
            self.assertEqual(headers, {})
            self.assertEqual(ledger[0]['category'], 'metadata')
            self.assertEqual(ledger[0]['bytes'], 0)


if __name__ == '__main__':
    unittest.main()
