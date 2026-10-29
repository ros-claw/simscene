import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from simscene.dependencies import repair

class Response(io.BytesIO):
    def __init__(self, url):
        super().__init__(b'dependency')
        self.url = url
    def geturl(self): return self.url

class DependencyTest(unittest.TestCase):
    def test_repeated_relative_name_never_replaces_an_existing_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            root=base/'root.usda'
            root.write_text('#usda 1.0\n( subLayers = [@one/layer.usda@, @two/layer.usda@] )\n')
            for name in ('one','two'):
                (base/name).mkdir()
                (base/name/'layer.usda').write_text('#usda 1.0\n( subLayers = [@geom.usda@] )\n')
            original=b'#usda 1.0\n# original\n'
            (base/'one/geom.usda').write_bytes(original)
            with patch('simscene.dependencies.build_opener') as opener:
                def fetch(url, timeout):
                    self.assertEqual(url, 'https://example.com/assets/two/geom.usda')
                    response=Response(url)
                    response.seek(0);response.truncate();response.write(b'#usda 1.0\n');response.seek(0)
                    return response
                opener.return_value.open.side_effect=fetch
                result=repair(root,'https://example.com/assets/root.usda',directory,10000)
            self.assertEqual(result['unresolved'],[])
            self.assertEqual((base/'one/geom.usda').read_bytes(),original)
            self.assertEqual(len(result['files']),1)

    def test_fetches_sibling_dependency_within_package_and_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'origin/robots/franka/root.usda'
            root.parent.mkdir(parents=True)
            root.write_text('#usda 1.0\n( subLayers = [@../gripper/grip.usda@] )\n')
            with patch('simscene.dependencies.build_opener') as opener:
                def fetch(url, timeout):
                    self.assertEqual(url, 'https://example.com/assets/robots/gripper/grip.usda')
                    response = Response(url)
                    response.seek(0); response.truncate(); response.write(b'#usda 1.0\n'); response.seek(0)
                    return response
                opener.return_value.open.side_effect = fetch
                result = repair(root, 'https://example.com/assets/robots/franka/root.usda', directory, 10000)
            self.assertEqual(result['unresolved'], [])
            self.assertTrue((root.parent.parent / 'gripper/grip.usda').is_file())

    def test_fetches_authored_relative_paths_against_owning_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root.usda'
            root.write_text('#usda 1.0\n( subLayers = [@sub/child.usda@] )\n')
            payloads = {
                'https://example.com/assets/sub/child.usda': b'#usda 1.0\n( subLayers = [@nested/material.usda@] )\n',
                'https://example.com/assets/sub/nested/material.usda': b'#usda 1.0\n',
            }
            with patch('simscene.dependencies.build_opener') as opener:
                def fetch(url, timeout):
                    response = Response(url)
                    response.seek(0); response.truncate(); response.write(payloads[url]); response.seek(0)
                    return response
                opener.return_value.open.side_effect = fetch
                result = repair(root, 'https://example.com/assets/root.usda', directory, 10000)
            self.assertEqual(result['unresolved'], [])
            self.assertEqual({f['url'] for f in result['files']}, set(payloads))
            self.assertTrue((Path(directory) / 'sub/nested/material.usda').is_file())

    def test_fetches_and_hashes_relative_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root.usd'; root.write_text('root')
            dep = str(Path(directory) / 'textures' / 'one.png')
            with patch('pxr.UsdUtils.ComputeAllDependencies', side_effect=[([], [], [dep]), ([], [], []), ([], [], [])]), patch('simscene.dependencies.build_opener') as opener:
                opener.return_value.open.side_effect = lambda url, timeout: Response(url)
                result = repair(root, 'https://example.com/assets/root.usd', directory, 10000)
            self.assertEqual(result['unresolved'], [])
            self.assertEqual(result['files'][0]['url'], 'https://example.com/assets/textures/one.png')
            self.assertEqual((Path(directory) / 'textures/one.png').read_bytes(), b'dependency')

    def test_does_not_fetch_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root.usd'; root.write_text('root')
            outside = str(Path(directory).parent / 'outside.usd')
            with patch('pxr.UsdUtils.ComputeAllDependencies', return_value=([], [], [outside])), patch('simscene.dependencies.build_opener') as get:
                result = repair(root, 'https://example.com/root.usd', directory, 10000)
            get.assert_not_called()
            self.assertEqual(result['unresolved'], [outside])
