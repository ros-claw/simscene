import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fetch_assets


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}


class FetchTests(unittest.TestCase):
    def test_fetches_only_locked_objects_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / 'tool'; source.mkdir()
            payloads = {'jetbot.usda': b'root', **{f'payloads/{n}.usda': bytes([n]) for n in range(7)}}
            lock = {'asset': 'jetbot.usda', 'total_bytes': sum(map(len, payloads.values())), 'files': [
                {'path': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                 'url': fetch_assets.SOURCE + path} for path, data in payloads.items()]}
            lock_file = source / 'asset-lock.json'
            lock_file.write_text(json.dumps(lock))
            (source / 'tool-lock.json').write_text(json.dumps({'files_sha256': {
                'asset-lock.json': hashlib.sha256(lock_file.read_bytes()).hexdigest()}}))
            def response(request, timeout):
                return Response(payloads[request.full_url.removeprefix(fetch_assets.SOURCE)])
            with patch.object(fetch_assets, 'HERE', source), patch.object(fetch_assets, 'urlopen', side_effect=response):
                result = fetch_assets.fetch(root / 'download')
                self.assertEqual(result.read_bytes(), b'root')
                self.assertEqual(len((root / 'download/fetch-log.jsonl').read_text().splitlines()), 8)
                with self.assertRaises(ValueError):
                    fetch_assets.fetch(root / 'download')
            def corrupted(request, timeout):
                return Response(b'bad')
            with patch.object(fetch_assets, 'HERE', source), patch.object(fetch_assets, 'urlopen', side_effect=corrupted):
                with self.assertRaises(ValueError):
                    fetch_assets.fetch(root / 'failed')
                record = json.loads((root / 'failed/fetch-log.jsonl').read_text())
                self.assertEqual(record['status'], 'error')


if __name__ == '__main__':
    unittest.main()
