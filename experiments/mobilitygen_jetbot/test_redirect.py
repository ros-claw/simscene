import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import urllib.request

import fetch_assets


class RedirectTests(unittest.TestCase):
    def test_redirect_is_rejected_before_cross_origin_request(self):
        hits, source_hits = [], []
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200); self.send_header('Content-Length', '4'); self.end_headers()
                self.wfile.write(b'root')
            def log_message(self, *args):
                pass
        target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        target_thread = Thread(target=target.serve_forever, daemon=True); target_thread.start()
        class Source(BaseHTTPRequestHandler):
            def do_GET(self):
                source_hits.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{target.server_port}/private')
                self.end_headers()
            def log_message(self, *args):
                pass
        source = ThreadingHTTPServer(('127.0.0.1', 0), Source)
        source_thread = Thread(target=source.serve_forever, daemon=True); source_thread.start()
        try:
            with tempfile.TemporaryDirectory() as name:
                root = Path(name); tool = root / 'tool'; tool.mkdir()
                prefix = f'http://127.0.0.1:{source.server_port}/'
                payloads = {'jetbot.usda': b'root', **{f'{n}.usda': bytes([n]) for n in range(7)}}
                lock = {'asset': 'jetbot.usda', 'total_bytes': sum(map(len, payloads.values())), 'files': [
                    {'path': p, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'url': prefix + p}
                    for p, data in payloads.items()]}
                lock_file = tool / 'asset-lock.json'; lock_file.write_text(json.dumps(lock))
                (tool / 'tool-lock.json').write_text(json.dumps({'files_sha256': {
                    'asset-lock.json': hashlib.sha256(lock_file.read_bytes()).hexdigest()}}))
                with (patch.object(fetch_assets, 'HERE', tool), patch.object(fetch_assets, 'SOURCE', prefix),
                      patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}),
                      patch.object(urllib.request, '_opener', None)):
                    with self.assertRaises(Exception) as caught:
                        fetch_assets.fetch(root / 'download')
                self.assertIsInstance(caught.exception, HTTPError)
                self.assertEqual(caught.exception.code, 302)
                self.assertEqual(source_hits, ['/jetbot.usda'])
                self.assertEqual(hits, [], 'redirect target must never be contacted')
        finally:
            source.shutdown(); target.shutdown()
            source.server_close(); target.server_close()


if __name__ == '__main__':
    unittest.main()
