import io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pxr import Usd,UsdGeom
from simscene.huggingface_cache import acquire,_download
from simscene.assets import SearchError

class HuggingFaceCacheTest(unittest.TestCase):
    def test_selected_usd_and_parent_dependency_are_cached_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';(source/'models').mkdir(parents=True)
            child=Usd.Stage.CreateNew(str(source/'child.usda'));child.SetDefaultPrim(UsdGeom.Xform.Define(child,'/Child').GetPrim());child.GetRootLayer().Save()
            stage=Usd.Stage.CreateNew(str(source/'models'/'root.usda'));prim=UsdGeom.Xform.Define(stage,'/Model').GetPrim();stage.SetDefaultPrim(prim);prim.GetReferences().AddReference('../child.usda');stage.GetRootLayer().Save()
            payload={'models/root.usda':(source/'models'/'root.usda').read_bytes(),'child.usda':(source/'child.usda').read_bytes()}
            def download(url,target,budget):
                import hashlib
                name=url.split('/resolve/'+'a'*40+'/')[1];data=payload[name]
                if len(data)>budget:raise SearchError('over capacity')
                target.write_bytes(data);return len(data),hashlib.sha256(data).hexdigest()
            with patch('simscene.huggingface_cache._download',side_effect=download):
                lock=acquire('org/repo','a'*40,'models/root.usda',root/'cache',100000)
            self.assertEqual(lock['dependency_status'],'resolved_locally')
            self.assertEqual({x['path'] for x in lock['files']},{'models/root.usda','child.usda'})
            with patch('simscene.huggingface_cache._download',side_effect=AssertionError('network should not be called')):
                again=acquire('org/repo','a'*40,'models/root.usda',root/'cache',100000)
            self.assertEqual(lock['package_sha256'],again['package_sha256'])
            Path(lock['root']).write_text('corrupt')
            with self.assertRaises(SearchError):acquire('org/repo','a'*40,'models/root.usda',root/'cache',100000)

    def test_rejects_mutable_revision_and_encoded_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            for revision,path in [('main','root.usd'),('a'*40,'%2e%2e/root.usd'),('a'*40,'bad%2fpath/root.usd')]:
                with self.assertRaises(ValueError):acquire('org/repo',revision,path,directory)

    def test_oversized_download_removes_partial_file(self):
        class Response(io.BytesIO):
            headers={'Content-Length':'8'}
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        with tempfile.TemporaryDirectory() as directory,patch('simscene.huggingface_cache.build_opener') as opener:
            opener.return_value.open.return_value=Response(b'12345678');path=Path(directory)/'asset'
            with self.assertRaises(SearchError):_download('https://huggingface.co/a',path,4)
            self.assertFalse(path.exists())
