import io,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from simscene.assets import SearchError
from simscene.cache import AssetCache
from simscene.cache_restore import restore_reference
from simscene.jobs import _snapshot_cached_assets

SOURCE='https://example.com/assets/robot/root.usda'

def archive(content):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('root.usda',content)
        z.writestr('manifest.json',json.dumps({'root_url':SOURCE,'files':[{'url':SOURCE,'path':'root.usda','size':len(content)}],'errors':{},'skipped':[]}))
    return out.getvalue()

class Client:
    def __init__(self,content):self.data=archive(content)
    def request(self,path,params=None,output=None,**kwargs):
        if output is None:return {'total_size':len(self.data)}
        output.write_bytes(self.data);return len(self.data)

class RestoreTest(unittest.TestCase):
    def evicted(self,root,content):
        cache=AssetCache(Client(content),root/'cache',max_bytes=10000)
        original=cache.acquire(SOURCE);path=Path(original['root'])
        provenance=cache.directory/'.provenance'/(original['package_sha256']+'.json')
        self.assertTrue(provenance.is_file())
        cache._evict(cache.max_bytes)
        self.assertFalse(path.exists());self.assertTrue(provenance.is_file())
        return path

    def test_evicted_asset_restores_selected_locked_content(self):
        content=b'#usda 1.0\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.evicted(root,content)
            with patch('simscene.cache_restore.USDSearch',return_value=Client(content)),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000'}):
                restored=restore_reference(old)
            self.assertEqual(restored.read_bytes(),content)

    def test_evicted_nested_member_restores_at_its_original_relative_path(self):
        root_data=b'#usda 1.0\n( subLayers = [@sub/child.usda@] )\n'
        child_data=b'#usda 1.0\n'
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as z:
            z.writestr('root.usda',root_data);z.writestr('sub/child.usda',child_data)
            z.writestr('manifest.json',json.dumps({'root_url':SOURCE,'files':[
                {'url':SOURCE,'path':'root.usda','size':len(root_data)},
                {'url':'https://example.com/assets/robot/sub/child.usda','path':'sub/child.usda','size':len(child_data)}],
                'errors':{},'skipped':[]}))
        client=Client(root_data);client.data=output.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            cache=AssetCache(client,Path(directory)/'cache',10000);lock=cache.acquire(SOURCE)
            child=Path(lock['root']).parent/'sub/child.usda';cache._evict(cache.max_bytes)
            with patch('simscene.cache_restore.USDSearch',return_value=client),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000'}):
                restored=restore_reference(child)
            self.assertEqual(restored.read_bytes(),child_data)

    def test_changed_source_is_rejected_after_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.evicted(root,b'#usda 1.0\n')
            with patch('simscene.cache_restore.USDSearch',return_value=Client(b'#usda 1.0\n# changed\n')),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000'}):
                with self.assertRaisesRegex(SearchError,'content changed'):
                    restore_reference(old)

    def test_eviction_preserves_provenance_for_older_cache_entries(self):
        content=b'#usda 1.0\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=AssetCache(Client(content),root/'cache',10000)
            original=cache.acquire(SOURCE)
            provenance=cache.directory/'.provenance'/(original['package_sha256']+'.json')
            provenance.unlink()  # entry predates provenance support
            cache._evict(cache.max_bytes)
            self.assertTrue(provenance.is_file())
            with patch('simscene.cache_restore.USDSearch',return_value=Client(content)),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000'}):
                restored=restore_reference(original['root'])
            self.assertEqual(restored.read_bytes(),content)

    def test_job_snapshots_restored_asset_without_changing_saved_scene_path(self):
        from simscene.scene import SceneStore
        content=b'#usda 1.0\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.evicted(root,content);run=root/'run';run.mkdir()
            with patch('simscene.cache_restore.USDSearch',return_value=Client(content)),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000','SIMSCENE_HOME':str(root/'state')}):
                store=SceneStore();store.open('saved')
                store.apply('saved',0,'asset',[{'op':'add','id':'robot','object':{'kind':'asset','asset_path':str(old)}}])
                scene=store.get('saved')
                records=_snapshot_cached_assets(scene,run)
                self.assertEqual(store.get('saved')['objects']['robot']['asset_path'],str(old))
            self.assertEqual(records['robot']['kind'],'snapshot')
            self.assertEqual(Path(scene['objects']['robot']['asset_path']).read_bytes(),content)
            self.assertTrue(Path(scene['objects']['robot']['asset_path']).is_relative_to(run))

    def test_evicted_huggingface_asset_uses_original_pinned_revision(self):
        import hashlib
        from simscene.huggingface_cache import acquire
        content=b'#usda 1.0\n'
        def download(url,target,budget):
            self.assertIn('/resolve/'+('a'*40)+'/models/root.usda',url)
            target.write_bytes(content)
            return len(content),hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=AssetCache(None,root/'cache',10000)
            with patch('simscene.huggingface_cache._download',side_effect=download),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000'}):
                original=acquire('org/repo','a'*40,'models/root.usda',cache.directory,10000)
                old=Path(original['root']);cache._evict(cache.max_bytes)
                self.assertFalse(old.exists())
                restored=restore_reference(old)
            self.assertEqual(restored.read_bytes(),content)

    def test_direct_scene_export_restores_evicted_asset(self):
        from simscene.scene import SceneStore
        from simscene.usd_export import export_scene
        content=b'#usda 1.0\n(\n    defaultPrim = "Robot"\n    metersPerUnit = 1\n    upAxis = "Z"\n)\ndef Xform "Robot" {}\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.evicted(root,content)
            with patch('simscene.cache_restore.USDSearch',return_value=Client(content)),patch.dict(os.environ,{'SIMSCENE_CACHE_BYTES':'10000','SIMSCENE_HOME':str(root/'state')}):
                store=SceneStore();store.open('saved')
                store.apply('saved',0,'asset',[{'op':'add','id':'robot','object':{'kind':'asset','asset_path':str(old)}}])
                output=root/'scene.usda'
                export_scene(store.get('saved'),output)
            self.assertTrue(output.is_file())
