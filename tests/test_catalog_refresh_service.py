"""Exercise explicit metadata refresh through the actual catalog facades."""
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from simscene.catalog import service
from simscene.catalog.models import SearchRequest
from simscene.catalog.network import MetadataDeadline
from simscene.catalog.search import search_assets
from simscene.catalog.store import CatalogStore

from test_catalog_abo import abo_row, metadata_server
from test_catalog_search import asset


class RefreshServiceTests(unittest.TestCase):
    def test_explicit_refresh_has_its_own_budget_and_search_reuses_index(self):
        from simscene.catalog.providers.abo import ABOProvider

        row = abo_row()
        payload = (json.dumps(row) + '\n').encode()
        revision = 'c7c8293fed3b7ab122ef5d7896521a187e0962d7'
        path = f'/datasets/codepawl/abo-glb/resolve/{revision}/metadata.jsonl'
        with tempfile.TemporaryDirectory() as directory, metadata_server({path: {'payload': payload}}) as (url, trace):
            settings = Path(directory) / 'v2.json'
            settings.write_text(json.dumps({'search_deadline_seconds': 1, 'refresh_deadline_seconds': 30,
                                            'index_directory': str(Path(directory) / 'index')}))
            env = {'SIMSCENE_V2_CONFIG': str(settings), 'SIMSCENE_HOME': str(Path(directory) / 'home')}
            def local_provider(store, source, config):
                return ABOProvider(store, source, base_url=url, max_index_bytes=config['metadata_max_bytes'])

            with (patch.dict('os.environ', env),
                  patch('simscene.catalog.providers.factory.make_provider', side_effect=local_provider)):
                report = service.refresh('abo-glb')
                found = service.search('shredder', {'source_ids': ['abo-glb']})
            self.assertEqual(report['deadline_seconds'], 30)
            self.assertEqual(report['records'], 1)
            self.assertEqual(report['metadata_bytes'], len(payload))
            self.assertEqual(report['model_bytes'], 0)
            self.assertEqual(found['budgets']['deadline_seconds'], 1)
            self.assertEqual(found['budgets']['metadata_bytes'], 0)
            self.assertEqual(len(found['items']), 1)
            self.assertEqual([request['path'] for request in trace], [path])

    def test_remember_batch_preserves_detail_and_exact_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(directory)
            records = [asset(identity='first'), asset(identity='second')]
            with patch.object(store, 'connect', wraps=store.connect) as connect:
                paths = store.remember_many(iter(records))
                connect.assert_called_once()
            self.assertEqual(len(paths), len(records))
            for record, path in zip(records, paths):
                self.assertEqual(store.get(record.ref), record)
                self.assertEqual(json.loads(Path(path).read_text()), record.to_dict())


    def test_cold_index_timeout_points_to_explicit_refresh(self):
        request = SearchRequest('notebook', source_ids=('abo-glb',))
        provider = Mock(snapshot='index_not_refreshed')
        provider.search.side_effect = MetadataDeadline('metadata deadline exceeded')
        with tempfile.TemporaryDirectory() as directory:
            status = search_assets(request, providers={'abo-glb': provider},
                                   index_directory=directory).source_statuses['abo-glb']
            self.assertEqual(status['status'], 'timeout')
            self.assertEqual(status['recovery'], {'tool': 'catalog_refresh', 'source_id': 'abo-glb'})
            provider.snapshot = 'existing-index'
            status = search_assets(request, providers={'abo-glb': provider},
                                   index_directory=directory).source_statuses['abo-glb']
            self.assertEqual(status, {'status': 'timeout'})


    def test_cli_reports_refresh_timeout_without_traceback(self):
        from simscene.cli import main

        errors = StringIO()
        with (patch('sys.argv', ['simscene', 'catalog', 'refresh', 'abo-glb']),
              patch('simscene.catalog.service.refresh', side_effect=MetadataDeadline('metadata deadline exceeded')),
              redirect_stderr(errors)):
            self.assertEqual(main(), 1)
        self.assertEqual(errors.getvalue(), 'metadata deadline exceeded\n')

    def test_search_does_not_republish_candidate_from_a_replaced_index(self):
        from dataclasses import replace
        from simscene.catalog.providers.http_assets import PolyHavenProvider
        from simscene.catalog.registry import load_registry
        from simscene.catalog.search import CursorInvalid

        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(directory)
            older = [asset(source='polyhaven', identity='first'), asset(source='polyhaven', identity='second')]
            newer = [replace(record, title='New Cup ' + record.ref.asset_id) for record in older]
            store.replace_index('polyhaven', older, 'old-index')

            class InterleavedRefresh(PolyHavenProvider):
                def search(self, request):
                    page = super().search(request)
                    store.replace_index('polyhaven', newer, 'new-index')
                    return page

            provider = InterleavedRefresh(store, load_registry().get('polyhaven'))
            params = dict(providers={'polyhaven': provider}, index_directory=directory)
            request = SearchRequest('cup', source_ids=('polyhaven',), limit=1)
            page = search_assets(request, **params)
            self.assertIsNotNone(page.next_cursor)
            self.assertIn(page.items[0]['title'], {row.title for row in older})
            for record in newer:
                self.assertEqual(store.get(record.ref).title, record.title)
            with self.assertRaises(CursorInvalid):
                search_assets(replace(request, cursor=page.next_cursor), **params)

    def test_sqlite_reads_index_marker_and_candidates_in_one_snapshot(self):
        import sqlite3
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(directory)
            record = asset()
            store.replace_index('abo-glb', [record], 'old-index')
            with sqlite3.connect(store.database) as db:
                db.execute('PRAGMA journal_mode=WAL').fetchone()
            open_db = store.connect
            changed = []
            def interleave(sql):
                if sql.startswith(('SELECT r.payload', 'SELECT payload FROM records')) and not changed:
                    changed.append(True)
                    writer = CatalogStore(directory)
                    writer.replace_index('abo-glb', [replace(record, title='New Cup')], 'new-index')

            def connect():
                db = open_db()
                db.set_trace_callback(interleave)
                return db

            with patch.object(store, 'connect', side_effect=connect):
                records, marker = store.search('abo-glb', 'cup', include_snapshot=True)
            self.assertEqual(changed, [True])
            self.assertEqual(store.snapshot('abo-glb'), 'new-index')
            self.assertEqual((records, marker), ((record,), 'old-index'))

    def test_over_budget_final_row_preserves_existing_index(self):
        from simscene.catalog.providers.abo import ABOProvider

        row = abo_row()
        payload = (json.dumps(row) + '\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(directory)
            provider = ABOProvider(store)
            old = asset()
            store.replace_index('abo-glb', [old], 'old-index')
            clock = [0]
            provider.configure(60, [])
            def parse(data):
                clock[0] = 61
                return original(data)
            original = provider._record
            with (patch('simscene.catalog.providers.abo.fetch_metadata', return_value=payload),
                  patch('simscene.catalog.providers.base.time.monotonic', side_effect=lambda: clock[0]),
                  patch.object(provider, '_record', side_effect=parse)):
                with self.assertRaises(MetadataDeadline):
                    provider.refresh()
            self.assertEqual(store.snapshot('abo-glb'), 'old-index')
            self.assertEqual(store.get(old.ref), old)
