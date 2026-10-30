import hashlib
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch
from pxr import Sdf,Usd,UsdGeom
from simscene.huggingface_cache import acquire
from simscene.asset_inspect import inspect_local
from simscene.assets import SearchError

class HuggingFaceMdlTest(unittest.TestCase):
    def test_transitive_module_and_texture_are_fetched_and_inspected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=Usd.Stage.CreateNew(str(root/'root.usda'));prim=UsdGeom.Xform.Define(stage,'/Root').GetPrim();stage.SetDefaultPrim(prim)
            prim.CreateAttribute('shader',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('materials/base.mdl'));stage.GetRootLayer().Save()
            payload={'root.usda':(root/'root.usda').read_bytes(),'materials/base.mdl':b'mdl 1.7; import coat::*;','materials/coat.mdl':b'mdl 1.7; texture_2d("surface.png");','materials/surface.png':b'png'}
            def fetch(url,target,budget):
                data=payload[unquote(url.split('/resolve/'+'a'*40+'/')[1])]
                if len(data)>budget:raise SearchError('over capacity')
                target.write_bytes(data);return len(data),hashlib.sha256(data).hexdigest()
            # USD alone resolves base.mdl and cannot detect its missing import.
            (root/'materials').mkdir();(root/'materials/base.mdl').write_bytes(payload['materials/base.mdl'])
            self.assertTrue(any('coat.mdl' in v for v in inspect_local(root/'root.usda')['unresolved_dependencies']))
            with patch('simscene.huggingface_cache._download',side_effect=fetch):
                result=acquire('org/repo','a'*40,'root.usda',root/'cache',100000)
            self.assertEqual(result['dependency_status'],'resolved_locally')
            self.assertEqual({f['path'] for f in result['files']},set(payload))
            self.assertFalse(inspect_local(result['root'])['unresolved_dependencies'])

    def test_module_missing_is_not_reported_as_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=Usd.Stage.CreateNew(str(root/'root.usda'));prim=UsdGeom.Xform.Define(stage,'/Root').GetPrim();stage.SetDefaultPrim(prim)
            prim.CreateAttribute('shader',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('base.mdl'));stage.GetRootLayer().Save()
            payload={'root.usda':(root/'root.usda').read_bytes(),'base.mdl':b'mdl 1.7; import missing::*;'}
            def fetch(url,target,budget):
                name=unquote(url.split('/resolve/'+'a'*40+'/')[1])
                if name not in payload:raise SearchError('missing module')
                data=payload[name];target.write_bytes(data);return len(data),hashlib.sha256(data).hexdigest()
            with patch('simscene.huggingface_cache._download',side_effect=fetch):result=acquire('org/repo','a'*40,'root.usda',root/'cache',100000)
            self.assertEqual(result['dependency_status'],'missing');self.assertTrue(any('missing.mdl' in v for v in result['unresolved_dependencies']))
