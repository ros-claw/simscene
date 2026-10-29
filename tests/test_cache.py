import io
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from simscene.assets import SearchError
from simscene.cache import AssetCache

class Client:
    def __init__(self, package): self.package = package
    def request(self, path, params=None, binary=False, output=None, max_bytes=None):
        if output is not None:
            output.write_bytes(self.package)
            return len(self.package)
        return self.package if binary else {'total_size': 10}

def package(name):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr(name, 'data')
        z.writestr('manifest.json', json.dumps({'root_url':'test', 'files':[{'url':'test','path':name,'size':4}], 'errors':{}, 'skipped':[]}))
    return output.getvalue()

class CacheTest(unittest.TestCase):
    def test_next_acquisition_cleans_abandoned_staging_without_following_symlinks(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache_dir=root/'cache';cache_dir.mkdir()
            partial=cache_dir/'.partial-old';partial.mkdir();(partial/'large').write_bytes(b'x'*1024)
            (cache_dir/'.index-abandoned').write_text('incomplete')
            outside=root/'outside';outside.mkdir();(outside/'keep').write_text('safe')
            (cache_dir/'.partial-link').symlink_to(outside,target_is_directory=True)
            cache=AssetCache(Client(package('root.usd')),cache_dir,10000)
            with patch('pxr.UsdUtils.ComputeAllDependencies',return_value=([],[],[])):
                cache.acquire('test')
            self.assertFalse(partial.exists());self.assertFalse((cache_dir/'.index-abandoned').exists())
            self.assertFalse((cache_dir/'.partial-link').is_symlink())
            self.assertEqual((outside/'keep').read_text(),'safe')

    def test_capacity_evicts_least_recently_used_package(self):
        import os
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=root/('a'*64);new=root/('b'*64)
            for entry in (old,new):
                entry.mkdir();(entry/'simscene-lock.json').write_text('{}');(entry/'payload').write_bytes(b'x'*100)
            os.utime(old,(100,100));os.utime(new,(200,200))
            cache=AssetCache(None,root,max_bytes=260)
            cache._evict(incoming=150)
            self.assertFalse(old.exists());self.assertTrue(new.exists())

    def test_rejects_asset_larger_than_capacity_before_download(self):
        class LargeClient:
            def request(self, path, params=None, output=None, **kwargs):
                if output is not None:raise AssertionError('must not download oversized archive')
                return {'total_size':1001}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SearchError,'capacity'):
                AssetCache(LargeClient(),directory,max_bytes=1000).acquire('https://example.com/model.usd')

    def test_package_preserves_parent_space_for_sibling_usd(self):
        from pathlib import Path
        root_url = 'https://example.com/assets/robots/franka/root.usda'
        root_data = b'#usda 1.0\n( subLayers = [@../gripper/grip.usda@] )\n'
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('root.usda', root_data)
            z.writestr('manifest.json', json.dumps({'root_url':root_url,
                'files':[{'url':root_url,'path':'root.usda','size':len(root_data)}],
                'errors':{},'skipped':[]}))
        with tempfile.TemporaryDirectory() as directory:
            cache = AssetCache(Client(archive.getvalue()), directory, 10000)
            with patch('simscene.dependencies.build_opener') as opener:
                def fetch(url, timeout):
                    self.assertEqual(url, 'https://example.com/assets/robots/gripper/grip.usda')
                    response = io.BytesIO(b'#usda 1.0\n')
                    response.geturl = lambda: url
                    return response
                opener.return_value.open.side_effect = fetch
                lock = cache.acquire(root_url)
            self.assertEqual(lock['dependency_status'], 'resolved_locally')
            self.assertTrue((Path(lock['root']).parent.parent / 'gripper/grip.usda').is_file())
            self.assertEqual(len(lock['files']), 2)
            self.assertEqual(cache.acquire(root_url)['root'], lock['root'])

    def test_runtime_system_dependencies_are_rechecked_per_host(self):
        from simscene.cache import _runtime_status
        lock={'dependency_status':'missing','unresolved_dependencies':['OmniPBR.mdl']}
        with patch('simscene.runtime_dependencies.classify',return_value={'runtime_provided':{'OmniPBR.mdl':'/runtime/OmniPBR.mdl'},'unresolved':[]}):
            local=_runtime_status(lock)
        self.assertEqual(local['dependency_status'],'resolved_with_runtime')
        self.assertEqual(local['unresolved_dependencies'],[])
        self.assertEqual(lock['unresolved_dependencies'],['OmniPBR.mdl'])
        with patch('simscene.runtime_dependencies.classify',return_value={'runtime_provided':{},'unresolved':['OmniPBR.mdl']}):
            self.assertEqual(_runtime_status(lock)['dependency_status'],'missing')

    def test_cache_rejects_symlinked_parent(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            cache=AssetCache(Client(package('sub/root.usd')),directory,10000)
            with patch('pxr.UsdUtils.ComputeAllDependencies',return_value=([],[],[])):
                first=cache.acquire('test')
            asset=Path(first['root']); outside=Path(directory)/'outside'; outside.mkdir()
            (outside/'root.usd').write_text('data')
            asset.unlink();asset.parent.rmdir();asset.parent.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(SearchError):cache.acquire('test')

    def test_rejects_zip_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SearchError):
                AssetCache(Client(package('../escape')), directory, 10000).acquire('test')

    def test_manifest_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            # A non-USD test file; the real USD scanner is tested separately.
            with patch('pxr.UsdUtils.ComputeAllDependencies', return_value=([], [], [])):
                lock = AssetCache(Client(package('root.usd')), directory, 10000).acquire('test')
            self.assertEqual(lock['dependency_status'], 'resolved_locally')
            self.assertEqual(len(lock['files'][0]['sha256']), 64)

    def test_cache_hit_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client(package('root.usd'))
            cache = AssetCache(client, directory, 10000)
            with patch('pxr.UsdUtils.ComputeAllDependencies', return_value=([], [], [])):
                first = cache.acquire('test')
                with patch.object(client, 'request', side_effect=AssertionError('network called')):
                    second = cache.acquire('test')
                self.assertEqual(first['root'], second['root'])
                from pathlib import Path
                Path(first['root']).write_text('evil')
                with self.assertRaises(SearchError): cache.acquire('test')
