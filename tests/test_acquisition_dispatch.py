"""Frozen plan acquisition: independent budgets, exact costs, and private copies."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from simscene.acquisition.dispatch import acquire_selected
from simscene.acquisition.transfer import BudgetExceeded
from simscene.acquisition.locks import copy_acquired_to_job
from simscene.assets import SearchError
from simscene.cache import AssetCache
from simscene.catalog.models import canonical_json
from test_dependency_repair_retry import SOURCE, ROOT, TEXTURE, archive


def freeze(payload):
    payload = deepcopy(payload)
    digest = hashlib.sha256(canonical_json(payload, exclude_volatile=False).encode()).hexdigest()
    return dict(payload, plan_id=digest, plan_payload_sha256=digest)


def plan(source='nvidia-usd-search', **budgets):
    ref = {'source_id': source, 'asset_id': SOURCE if source == 'nvidia-usd-search' else 'item',
           'revision': 'metadata-sha256:fixture' if source == 'nvidia-usd-search' else 'a' * 40,
           'variant_id': None}
    descriptor = {'kind': 'usd_dependency_closure', 'asset_url': SOURCE}
    if source == 'abo-glb':
        descriptor = {'kind': 'hf_glb', 'repository': 'codepawl/abo-glb', 'revision': 'a' * 40,
                      'path': 'objects/item/item.glb'}
    return freeze({'schema_version': 1, 'asset_ref': ref, 'acquisition': descriptor,
                   'source_snapshot': {'entry_path':descriptor.get('path'), 'provenance': {'upstream_asset_id': ref['asset_id']}},
                   'license_decision': {'status': 'known', 'license': 'fixture-license'},
                   'ready_to_fetch': True, 'blocking_reasons': [],
                   'budget_breakdown': dict({'download_bytes': 100000, 'unpacked_bytes': 100000,
                                             'staging_bytes': 100000}, **budgets)})


class Response(io.BytesIO):
    def __init__(self, url, payload, *, length=True):
        super().__init__(payload)
        self.url = url
        self.status = 200
        self.headers = {'Content-Length': str(len(payload))} if length else {}
    def geturl(self):
        return self.url


class Opener:
    def __init__(self, payloads=None):
        self.calls = []
        self.payloads = payloads or {}
    def open(self, request, timeout):
        url = getattr(request, 'full_url', request)
        self.calls.append(url)
        parsed = urlsplit(url)
        if parsed.path == '/download/asset':
            query = parse_qs(parsed.query)
            payload = json.dumps({'total_size': len(ROOT)}).encode() if 'manifest_only' in query else archive()
        elif url in self.payloads:
            payload = self.payloads[url]
        elif parsed.path.endswith('/textures/one.png'):
            payload = TEXTURE
        else:
            raise AssertionError('unexpected request ' + url)
        return Response(url, payload)


def glb_bytes():
    document = json.dumps({'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': []}], 'nodes': []}).encode()
    document += b' ' * (-len(document) % 4)
    return b'glTF' + struct.pack('<II', 2, 20 + len(document)) + struct.pack('<II', len(document), 0x4E4F534A) + document


class AcquisitionDispatchTest(unittest.TestCase):
    def config(self, root):
        return {'asset_cache_directory': str(Path(root) / 'cache'), 'asset_cache_capacity_bytes': 1000000}

    def test_usd_cost_includes_archive_and_texture_and_private_copy_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener()
            config = self.config(directory)
            with patch('simscene.acquisition.transfer.build_opener', return_value=opener), patch('simscene.dependencies.build_opener', return_value=opener):
                acquired = acquire_selected(plan(), config=config, job_directory=Path(directory) / 'job')
                self.assertEqual(acquired['actual_download_bytes'], len(archive()) + len(TEXTURE))
                self.assertEqual(acquired['job_copy_bytes'], len(ROOT) + len(TEXTURE))
                self.assertEqual(acquired['dependency_status'], 'resolved_locally')
                self.assertEqual(Path(acquired['root']).read_bytes(), ROOT)
                self.assertTrue(Path(acquired['root']).is_relative_to(Path(directory) / 'job/source'))
                self.assertEqual(acquired['license'], plan()['license_decision'])
                self.assertEqual(acquired['source_ref'], plan()['asset_ref'])
                self.assertEqual(acquired['provenance'], plan()['source_snapshot']['provenance'])
                self.assertEqual(acquired['manifest_sha256'], acquired['source_manifest_hash'])
                self.assertTrue(all('?' not in e['endpoint'] for e in acquired['transfer_ledger']))
                count = len(opener.calls)
                warm = acquire_selected(plan(), config=config, job_directory=Path(directory) / 'second-job')
                self.assertEqual(warm['actual_download_bytes'], 0)
                self.assertEqual(len(opener.calls), count)
                self.assertEqual(warm['source_manifest_hash'], acquired['source_manifest_hash'])

    def test_primary_plus_dependency_cannot_each_spend_the_full_transfer_budget(self):
        limit = len(archive()) + len(TEXTURE) - 1
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener()
            with patch('simscene.acquisition.transfer.build_opener', return_value=opener), patch('simscene.dependencies.build_opener', return_value=opener):
                with self.assertRaises(BudgetExceeded) as raised:
                    acquire_selected(plan(download_bytes=limit), config=self.config(directory))
            error = raised.exception
            self.assertEqual(error.actual_download_bytes, len(archive()))
            self.assertLessEqual(error.actual_download_bytes, limit)
            self.assertEqual(error.transfer_ledger[-1]['status'], 'budget_exceeded')
            self.assertFalse(list((Path(directory) / 'cache').glob('.partial-*')))
            self.assertFalse(list((Path(directory) / 'cache').glob('[0-9a-f]' * 64)))

    def test_unpacked_and_staging_limits_are_separate_from_transfer_and_cache_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener()
            with patch('simscene.acquisition.transfer.build_opener', return_value=opener), patch('simscene.dependencies.build_opener', return_value=opener):
                for limits in ({'unpacked_bytes': 1}, {'staging_bytes': len(archive()) - 1}):
                    with self.subTest(limits=limits), self.assertRaises(SearchError):
                        acquire_selected(plan(**limits), config=self.config(directory))
                # A small network budget must not shrink or evict global cache entries.
                cache = AssetCache(None, Path(directory) / 'cache', max_bytes=1000000)
                sentinel = cache.directory / ('b' * 64); sentinel.mkdir()
                (sentinel / 'simscene-lock.json').write_text('{}')
                (sentinel / 'payload').write_bytes(b'x' * 200000)
                acquired = acquire_selected(plan(download_bytes=len(archive()) + len(TEXTURE)), config=self.config(directory))
                self.assertTrue(sentinel.exists())
                self.assertEqual(acquired['actual_download_bytes'], len(archive()) + len(TEXTURE))

    def test_no_usd_tools_keeps_unverified_dependency_status(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', {'pxr': None}):
            with patch('simscene.acquisition.transfer.build_opener', return_value=Opener()):
                acquired = acquire_selected(plan(), config=self.config(directory))
            self.assertEqual(acquired['dependency_status'], 'unverified_usd_tools_unavailable')
            self.assertEqual(acquired['files'][0]['sha256'], hashlib.sha256(ROOT).hexdigest())

    def test_glb_and_legacy_usd_share_copy_validation_and_cumulative_accounting(self):
        root = glb_bytes(); license_bytes = b'CC-BY-4.0 fixture notice'
        base = 'https://huggingface.co/datasets/codepawl/abo-glb/resolve/' + 'a' * 40 + '/'
        opener = Opener({base + 'objects/item/item.glb': root,
                         base + 'LICENSE-CC-BY-4.0.txt': license_bytes})
        with tempfile.TemporaryDirectory() as directory, patch('simscene.acquisition.transfer.build_opener', return_value=opener):
            acquired = acquire_selected(plan('abo-glb'), config=self.config(directory), job_directory=Path(directory) / 'job')
            self.assertEqual(acquired['actual_download_bytes'], len(root) + len(license_bytes))
            self.assertEqual(acquired['job_copy_bytes'], len(root) + len(license_bytes))
            self.assertEqual(acquired['dependency_status'], 'resolved_locally')
            self.assertEqual(Path(acquired['root']).read_bytes(), root)
            self.assertEqual(len(acquired['files']), 2)
            self.assertEqual(len(acquired['transfer_ledger']), 2)
            self.assertTrue(all(e['category'] == 'model' for e in acquired['transfer_ledger']))
            count = len(opener.calls)
            warm = acquire_selected(plan('abo-glb'), config=self.config(directory), job_directory=Path(directory) / 'warm-job')
            self.assertEqual(warm['actual_download_bytes'], 0)
            self.assertEqual(len(opener.calls), count)
            changed = dict(warm, manifest_sha256='0' * 64)
            with self.assertRaisesRegex(SearchError, 'manifest changed'):
                copy_acquired_to_job(changed, self.config(directory)['asset_cache_directory'], Path(directory) / 'bad-copy')

    def test_glb_later_file_failure_preserves_prior_model_transfer_cost(self):
        root = glb_bytes(); license_bytes = b'CC-BY-4.0 fixture notice'
        base = 'https://huggingface.co/datasets/codepawl/abo-glb/resolve/' + 'a' * 40 + '/'
        opener = Opener({base + 'objects/item/item.glb': root,
                         base + 'LICENSE-CC-BY-4.0.txt': license_bytes})
        with tempfile.TemporaryDirectory() as directory, patch('simscene.acquisition.transfer.build_opener', return_value=opener):
            with self.assertRaises(BudgetExceeded) as raised:
                acquire_selected(plan('abo-glb', download_bytes=len(root) + len(license_bytes) - 1), config=self.config(directory))
            self.assertEqual(raised.exception.actual_download_bytes, len(root))
            self.assertEqual(raised.exception.transfer_ledger[0]['bytes'], len(root))
            self.assertEqual(raised.exception.transfer_ledger[-1]['status'], 'budget_exceeded')

    def test_failed_dependency_partial_bytes_are_included_in_transaction_cost(self):
        from urllib.error import URLError
        class Interrupted(Response):
            def __init__(self, url):
                super().__init__(url, TEXTURE)
                self.reads = 0
            def read(self, size=-1):
                self.reads += 1
                if self.reads == 1:
                    return super().read(3)
                raise URLError('do not expose https://host/?token=secret')
        class InterruptedOpener(Opener):
            def open(self, request, timeout):
                url = getattr(request, 'full_url', request)
                if url.endswith('/textures/one.png'):
                    self.calls.append(url)
                    return Interrupted(url)
                return super().open(request, timeout)
        opener = InterruptedOpener()
        with tempfile.TemporaryDirectory() as directory, patch('simscene.acquisition.transfer.build_opener', return_value=opener), patch('simscene.dependencies.build_opener', return_value=opener):
            acquired = acquire_selected(plan(), config=self.config(directory))
            self.assertEqual(acquired['dependency_status'], 'missing')
            self.assertEqual(acquired['actual_download_bytes'], len(archive()) + 3)
            self.assertEqual(acquired['transfer_ledger'][-1]['bytes'], 3)
            self.assertNotIn('secret', json.dumps(acquired['transfer_ledger']))
            self.assertNotIn('secret', json.dumps(acquired['repair_errors']))

    def test_mutated_or_blocked_plan_fails_before_any_request(self):
        selected = plan()
        selected['acquisition']['asset_url'] = 'https://elsewhere.example/root.usda'
        with tempfile.TemporaryDirectory() as directory, patch('simscene.acquisition.transfer.build_opener') as opener:
            with self.assertRaisesRegex(ValueError, 'immutable'):
                acquire_selected(selected, config=self.config(directory))
            blocked = dict(plan(), ready_to_fetch=False)
            blocked = freeze({k: v for k, v in blocked.items() if k not in {'plan_id', 'plan_payload_sha256'}})
            with self.assertRaisesRegex(ValueError, 'blocked'):
                acquire_selected(blocked, config=self.config(directory))
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
