"""A transient ordinary texture miss is retryable without mutating frozen packages."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile
from simscene.cache import AssetCache
from simscene.assets import SearchError
from simscene import huggingface_cache

SOURCE = 'https://assets.example.test/assets/root.usda'
ROOT = b'#usda 1.0\ndef Scope "Asset" {\n asset texture = @textures/one.png@\n}\n'
TEXTURE = b'fake-local-texture'


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as stream:
        stream.writestr('root.usda', ROOT)
        stream.writestr('manifest.json', json.dumps({'root_url': SOURCE, 'files': [
            {'url': SOURCE, 'path': 'root.usda', 'size': len(ROOT)}], 'errors': {}, 'skipped': []}))
    return output.getvalue()


class Client:
    def __init__(self):
        self.downloads = 0
    def request(self, path, params=None, output=None, **kwargs):
        if output is not None:
            self.downloads += 1
            output.write_bytes(archive())
        return {'total_size': len(ROOT)}


class Response(io.BytesIO):
    def __init__(self, url, payload=TEXTURE):
        super().__init__(payload)
        self.url = url
    def geturl(self):
        return self.url


class DependencyRepairRetryTest(unittest.TestCase):
    def test_usd_texture_404_then_restored_creates_new_lock_reusing_existing_root(self):
        available = False
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            if not available:
                raise HTTPError(url, 404, 'not found', {}, None)
            return Response(url)
        with tempfile.TemporaryDirectory() as directory, patch('simscene.dependencies.build_opener') as opener:
            opener.return_value.open.side_effect = fetch
            client = Client()
            cache = AssetCache(client, directory, 100000)
            first = cache.acquire(SOURCE)
            self.assertEqual(first['dependency_status'], 'missing')
            old_folder = Path(directory) / first['package_sha256']
            old_lock = (old_folder / 'simscene-lock.json').read_bytes()
            old_root = Path(first['root']).read_bytes()
            self.assertEqual(client.downloads, 1)
            available = True
            repaired = cache.acquire(SOURCE)
            self.assertEqual(repaired['dependency_status'], 'resolved_locally')
            self.assertNotEqual(repaired['package_sha256'], first['package_sha256'])
            self.assertEqual(client.downloads, 1)
            self.assertEqual((old_folder / 'simscene-lock.json').read_bytes(), old_lock)
            self.assertEqual(Path(first['root']).read_bytes(), old_root)
            self.assertFalse((Path(first['root']).parent / 'textures/one.png').exists())
            self.assertEqual((Path(repaired['root']).parent / 'textures/one.png').read_bytes(), TEXTURE)
            prior_calls = len(calls)
            warm = cache.acquire(SOURCE)
            self.assertEqual(warm['package_sha256'], repaired['package_sha256'])
            self.assertEqual(len(calls), prior_calls)

    def test_pinned_hf_usd_texture_retry_reuses_present_files_and_old_lock(self):
        available = False
        fetched = []
        def download(url, destination, budget):
            fetched.append(url)
            if url.endswith('root.usda'):
                payload = ROOT
            elif not available:
                raise SearchError('Hugging Face download failed: HTTP 404')
            else:
                payload = TEXTURE
            destination.write_bytes(payload)
            return len(payload), hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch('simscene.huggingface_cache._download', side_effect=download):
            first = huggingface_cache.acquire('org/models', 'a' * 40, 'root.usda', directory, 100000)
            self.assertEqual(first['dependency_status'], 'missing')
            lock_path = Path(directory) / first['package_sha256'] / 'simscene-lock.json'
            original = lock_path.read_bytes()
            available = True
            repaired = huggingface_cache.acquire('org/models', 'a' * 40, 'root.usda', directory, 100000)
            self.assertEqual(repaired['dependency_status'], 'resolved_locally')
            self.assertNotEqual(repaired['package_sha256'], first['package_sha256'])
            self.assertEqual(sum(url.endswith('root.usda') for url in fetched), 1)
            self.assertEqual(lock_path.read_bytes(), original)
            count = len(fetched)
            huggingface_cache.acquire('org/models', 'a' * 40, 'root.usda', directory, 100000)
            self.assertEqual(len(fetched), count)


if __name__ == '__main__':
    unittest.main()
