import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from simscene.preparation.profiles import validate_parameters, PreparationError
from simscene.preparation.environment_layer import prepare_environment
from simscene.physics_binding import validate_asset_binding

try:
    from pxr import Usd, UsdLux, UsdPhysics, UsdUtils
except ImportError:
    Usd=None


class EnvironmentParameterTests(unittest.TestCase):
    def test_nongeometric_role_has_explicit_bounded_illumination_only(self):
        self.assertEqual(validate_parameters('environment_v1',{}),{'intensity':300.,'exposure':0.,'texture_format':'latlong'})
        for p in ({'mass_kg':1},{'intensity':True},{'exposure':float('nan')},{'intensity':-1},{'exposure':11},{'texture_format':'unknown'}):
            with self.subTest(p=p),self.assertRaises(PreparationError):validate_parameters('environment_v1',p)


@unittest.skipIf(Usd is None,'USD unavailable')
class EnvironmentLayerTests(unittest.TestCase):
    def test_light_only_relative_hashed_package_does_not_invent_bounds_or_physics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'input'/'studio.exr';source.parent.mkdir();source.write_bytes(b'opaque-selected-EXR-fixture-not-a-render-test')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            acquired={'asset_type':'hdri','root':str(source),'files':[{'path':source.name,'sha256':digest,'size_bytes':source.stat().st_size}],
                      'source_ref':{'source_id':'polyhaven','asset_id':'studio','revision':'a'*64},'manifest_sha256':'b'*64,
                      'license':{'status':'known','license':'CC0-1.0'},'provenance':{'fixture':True}}
            result=prepare_environment(acquired,{}, {'engine':'physx','isaac_version':'fixture','usd_version':'.'.join(map(str,Usd.GetVersion())),'platform':'fixture'}, root/'out')
            pin={key:result[key] for key in ('manifest_path','manifest_sha256')}
            manifest=validate_asset_binding(pin,asset_path=result['asset_path'])
            self.assertIsNone(manifest['bounds']);self.assertEqual(manifest['body_map'],{})
            self.assertEqual(manifest['environment_report']['render_validation'],'not_run')
            stage=Usd.Stage.Open(result['asset_path']);light=UsdLux.DomeLight.Get(stage,'/Asset/Environment')
            self.assertTrue(light);self.assertEqual(light.GetTextureFileAttr().Get().path,'./source/studio.exr')
            self.assertFalse(any(prim.HasAPI(UsdPhysics.RigidBodyAPI) or prim.HasAPI(UsdPhysics.CollisionAPI) for prim in stage.Traverse()))
            self.assertEqual(UsdUtils.ComputeAllDependencies(result['asset_path'])[2],[])
            Path(result['asset_path']).write_text('tampered')
            with self.assertRaisesRegex(ValueError,'changed'):validate_asset_binding(pin)

    def test_material_is_not_silently_wrapped_as_an_environment(self):
        with self.assertRaisesRegex(PreparationError,'requires one selected HDRI'):
            prepare_environment({'asset_type':'material','root':'image.jpg'},{},{},'/not-created')


if __name__=='__main__':unittest.main()
