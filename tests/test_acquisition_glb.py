import hashlib
import io
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.acquisition.glb import acquire_glb, inspect_glb, _download
from simscene.acquisition.locks import copy_acquired_to_job
from simscene.assets import SearchError

SHA = 'a' * 40


def glb(document=None, binary=None):
    document = document or {'asset': {'version': '2.0'}}
    raw = json.dumps(document).encode()
    raw += b' ' * (-len(raw) % 4)
    chunks = struct.pack('<II', len(raw), 0x4E4F534A) + raw
    if binary is not None:
        binary += b'\0' * (-len(binary) % 4)
        chunks += struct.pack('<II', len(binary), 0x004E4942) + binary
    return struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks


class AcquisitionGlbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.requests = []
        self.payloads = {'models/item.glb': glb()}
        self.mock = patch('simscene.acquisition.glb._download', self.download)
        self.mock.start()

    def tearDown(self):
        self.mock.stop()
        self.temp.cleanup()

    def download(self, url, target, budget):
        path = url.split('/resolve/' + SHA + '/')[1]
        self.requests.append((path, budget))
        data = self.payloads.get(path)
        if data is None:
            raise SearchError('Hugging Face download failed: 404')
        if len(data) > budget:
            raise SearchError('GLB transfer budget exceeded')
        target.write_bytes(data)
        return len(data), hashlib.sha256(data).hexdigest()

    def acquire(self, **kwargs):
        return acquire_glb('owner/repo', SHA, 'models/item.glb', self.cache, **kwargs)

    def test_only_selected_and_warm_integrity(self):
        self.payloads['unselected.glb'] = glb()
        result = self.acquire(license={'id': 'CC0'}, metadata={'title': 'Object'})
        self.assertEqual([p for p, _ in self.requests], ['models/item.glb'])
        self.assertEqual(result['actual_download_bytes'], len(self.payloads['models/item.glb']))
        self.assertEqual(result['dependency_status'], 'resolved_locally')
        self.assertEqual(result['files'][0]['path'], 'models/item.glb')
        again = self.acquire(license={'id': 'CC0'}, metadata={'title': 'Object'}, download_budget_bytes=0)
        self.assertEqual(again['actual_download_bytes'], 0)
        self.assertEqual(result['asset_handle'], again['asset_handle'])
        Path(result['root']).write_bytes(b'corrupt')
        with self.assertRaises(SearchError):
            self.acquire(license={'id': 'CC0'}, metadata={'title': 'Object'})
        self.assertEqual(len(self.requests), 1)

    def test_external_dependency_retry_preserves_old_package(self):
        self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'buffers': [{'uri': '../data.bin', 'byteLength': 4}], 'images': [{'uri': 'texture.png'}]})
        self.payloads['data.bin'] = b'abcd'
        first = self.acquire()
        self.assertEqual(first['dependency_status'], 'missing')
        old_lock = (Path(first['root']).parents[1] / 'simscene-lock.json').read_bytes()
        self.payloads['models/texture.png'] = b'png'
        second = self.acquire()
        self.assertEqual(second['dependency_status'], 'resolved_locally')
        self.assertEqual(second['actual_download_bytes'], 3)
        self.assertEqual(sum(path == 'models/item.glb' for path, _ in self.requests), 1)
        self.assertNotEqual(first['asset_handle'], second['asset_handle'])
        self.assertEqual((Path(first['root']).parents[1] / 'simscene-lock.json').read_bytes(), old_lock)

    def test_source_drift_after_eviction(self):
        result = self.acquire()
        shutil.rmtree(self.cache / result['package_sha256'])
        self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'extras': {'changed': True}})
        with self.assertRaisesRegex(SearchError, 'immutable source content changed'):
            self.acquire()

    def test_ref_and_path_validation_without_requests(self):
        for sha, path in [('main', 'a.glb'), (SHA, '../a.glb'), (SHA, 'a.usd'), (SHA, 'x/%252e%252e/a.glb')]:
            with self.subTest(sha=sha, path=path), self.assertRaises(ValueError):
                acquire_glb('owner/repo', sha, path, self.cache)
        self.assertEqual(self.requests, [])

    def test_dependency_escape_rejected(self):
        for uri in ['../../escape.bin', 'https://other/a', '//other/a', '%2e%2e/a', '%252e%252e/a', 'a%2fb', 'a\\b']:
            with self.subTest(uri=uri):
                self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'images': [{'uri': uri}]})
                with self.assertRaises(ValueError):
                    self.acquire()

    def test_budget_and_declared_external_length(self):
        with self.assertRaisesRegex(SearchError, 'budget'):
            self.acquire(download_budget_bytes=4)
        self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'x.bin', 'byteLength': 4}]})
        self.payloads['models/x.bin'] = b'wrong'
        with self.assertRaisesRegex(SearchError, 'declared size'):
            self.acquire()
        self.assertFalse(any(self.cache.glob('.partial-*')))

    def test_embedded_and_unknown_codec(self):
        self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'data:application/octet-stream;base64,YWJjZA==', 'byteLength': 4}], 'extensionsUsed': ['KHR_draco_mesh_compression']})
        result = self.acquire()
        self.assertEqual(result['dependency_status'], 'unverified_extensions')
        self.assertEqual(len(self.requests), 1)

    def test_header_chunk_and_binary_bounds(self):
        path = self.root / 'test.glb'
        cases = [b'bad', glb()[:-1], glb({'asset': {'version': '1.0'}}), glb({'asset': {'version': '2.0'}, 'buffers': [{'byteLength': 99}]}, b'1234'), glb({'asset': {'version': '2.0'}, 'buffers': [{'byteLength': 4}], 'bufferViews': [{'buffer': 0, 'byteOffset': 3, 'byteLength': 2}]}, b'1234')]
        for data in cases:
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                inspect_glb(path)
        path.write_bytes(glb())
        with self.assertRaisesRegex(ValueError, 'oversized'):
            inspect_glb(path, max_json_bytes=1)

    def meshopt_document(self):
        return {'asset': {'version': '2.0'},
                'extensionsRequired': ['EXT_meshopt_compression'],
                'extensionsUsed': ['EXT_meshopt_compression'],
                'buffers': [{'byteLength': 8}, {'byteLength': 32, 'extensions': {'EXT_meshopt_compression': {'fallback': True}}}],
                'bufferViews': [{'buffer': 1, 'byteLength': 32, 'byteStride': 8,
                                 'extensions': {'EXT_meshopt_compression': {'buffer': 0, 'byteLength': 8, 'byteStride': 8, 'count': 4, 'mode': 'ATTRIBUTES'}}}]}

    def test_required_meshopt_fallback_is_framed_not_decoded(self):
        self.payloads['models/item.glb'] = glb(self.meshopt_document(), b'encoded!')
        acquired = self.acquire()
        self.assertEqual(acquired['dependency_status'], 'unverified_extensions')
        self.assertEqual(acquired['inspection']['meshopt_decoded_bytes'], 32)
        self.assertEqual(acquired['inspection']['meshopt_compressed_views'], 1)
        self.assertEqual(len(acquired['files']), 1)
        self.assertEqual(len(self.requests), 1)

    def test_meshopt_invalid_fallback_ranges_layout_modes_and_budgets(self):
        path = self.root / 'compressed.glb'
        cases = []
        document = self.meshopt_document(); document['extensionsRequired'] = []; cases.append(document)
        document = self.meshopt_document(); document['buffers'][1]['extensions']['EXT_meshopt_compression']['fallback'] = False; cases.append(document)
        document = self.meshopt_document(); document['bufferViews'][0].pop('extensions'); cases.append(document)
        for field, value in [('buffer', 1), ('byteOffset', 4), ('count', 3), ('count', True), ('mode', 'UNSUPPORTED'), ('filter', 'UNKNOWN'), ('filter', 'QUATERNION')]:
            document = self.meshopt_document()
            document['bufferViews'][0]['extensions']['EXT_meshopt_compression'][field] = value
            # QUATERNION needs stride 8 and is valid here; force stride 4 to test it.
            if field == 'filter' and value == 'QUATERNION':
                document['bufferViews'][0]['extensions']['EXT_meshopt_compression'].update(byteStride=4, count=8)
                document['bufferViews'][0]['byteStride'] = 4
            cases.append(document)
        document = self.meshopt_document(); document['bufferViews'][0]['byteStride'] = 4; cases.append(document)
        document = self.meshopt_document(); document['bufferViews'][0]['extensions']['EXT_meshopt_compression'].update(mode='TRIANGLES', count=16, byteStride=2, filter='EXPONENTIAL'); document['bufferViews'][0]['byteStride'] = 2; cases.append(document)
        for index, document in enumerate(cases):
            path.write_bytes(glb(document, b'encoded!'))
            with self.subTest(index=index), self.assertRaises(ValueError):
                inspect_glb(path)
        path.write_bytes(glb(self.meshopt_document(), b'encoded!'))
        with self.assertRaisesRegex(ValueError, 'decoded byte budget'):
            inspect_glb(path, max_decoded_bytes=16)
        document = self.meshopt_document()
        document['bufferViews'] *= 3
        path.write_bytes(glb(document, b'encoded!'))
        with self.assertRaisesRegex(ValueError, 'decoded byte budget'):
            inspect_glb(path, max_decoded_bytes=64)

    def test_real_stream_download_budgets_and_size(self):
        class Response(io.BytesIO):
            def __init__(self, data, length=None):
                super().__init__(data)
                self.headers = {} if length is None else {'Content-Length': str(length)}
        target = self.root / 'transfer'
        for data, length, budget in [(b'abc', 4, 20), (b'abcd', None, 3), (b'abc', 30, 4)]:
            with self.subTest(length=length), patch('simscene.acquisition.glb.build_opener') as opener:
                opener.return_value.open.return_value = Response(data, length)
                with self.assertRaises(SearchError):
                    _download('https://huggingface.co/file', target, budget)
                self.assertFalse(target.exists())
        with patch('simscene.acquisition.glb.build_opener') as opener:
            opener.return_value.open.return_value = Response(b'abc', 3)
            size, sha = _download('https://huggingface.co/file', target, 3)
            self.assertEqual((size, sha), (3, hashlib.sha256(b'abc').hexdigest()))

    def test_failed_transfer_counts_toward_total_budget(self):
        self.payloads['models/item.glb'] = glb({'asset': {'version': '2.0'}, 'images': [{'uri': 'a.png'}, {'uri': 'b.png'}]})
        original = self.download
        def failed(url, target, budget):
            if url.endswith('a.png'):
                failure = SearchError('Hugging Face download failed: disconnected')
                failure.actual_download_bytes = 5
                raise failure
            return original(url, target, budget)
        self.payloads['models/b.png'] = b'12345'
        root_size = len(self.payloads['models/item.glb'])
        with patch('simscene.acquisition.glb._download', failed), self.assertRaisesRegex(SearchError, 'budget'):
            self.acquire(download_budget_bytes=root_size + 9)
        self.assertEqual(self.requests[-1][1], 4)

    def test_private_copy_budget_and_integrity(self):
        acquired = self.acquire()
        destination = self.root / 'jobs' / 'input'
        copied = copy_acquired_to_job(acquired, self.cache, destination)
        self.assertTrue(Path(copied['root']).is_file())
        self.assertTrue((destination / 'simscene-lock.json').is_file())
        with self.assertRaises(SearchError):
            copy_acquired_to_job(acquired, self.cache, self.root / 'small', staging_budget_bytes=1)
        self.assertFalse((self.root / 'small').exists())
        self.assertFalse(any(destination.parent.glob('.job-input-*')))


if __name__ == '__main__':
    unittest.main()
