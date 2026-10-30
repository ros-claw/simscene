import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from simscene.mdl_dependencies import references
class MdlDependenciesTest(unittest.TestCase):
 def test_relative_modules_textures_and_builtin_namespace(self):
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);p=root/'OmniPBR.mdl';p.write_text('import ::df::*; import ::nvidia::core_definitions::file_texture; import OmniPBR_ClearCoat::*; import .::nested::Coat::*; // import Fake::*;\n export string t="../Textures/metal.png"; /* "fake.png" */')
   self.assertEqual(set(references(p)),{root/'OmniPBR_ClearCoat.mdl',root/'nested/Coat.mdl',root.parent/'Textures/metal.png'})
 def test_recursive_material_closure_is_inside_existing_fetch_bounds(self):
  from simscene.dependencies import repair
  from pxr import Usd,UsdGeom
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);source=Usd.Stage.CreateNew(str(root/'root.usda'));UsdGeom.Xform.Define(source,'/World');source.GetRootLayer().Save()
   (root/'OmniPBR.mdl').write_text('import OmniPBR_ClearCoat::*;')
   fetched=[]
   def fetch(path,item,*args):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('export string map="textures/metal.png";' if path.suffix=='.mdl' else 'pixels');fetched.append(path.name)
    return {'file':{'path':str(path.relative_to(root)),'url':'https://source/'+path.name,'size':path.stat().st_size,'sha256':'a'*64}}
   with patch('simscene.dependencies._fetch',side_effect=fetch):r=repair(root/'root.usda','https://source/root.usda',root,100000)
   self.assertEqual(fetched,['OmniPBR_ClearCoat.mdl','metal.png']);self.assertFalse(r['unresolved'])
