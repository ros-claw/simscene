"""Lighting edits must validate and export actual USD light schemas."""
import tempfile
import unittest
from pathlib import Path
from pxr import Usd,UsdLux
from simscene.scene import SceneStore,validate
from simscene.usd_export import export_scene

class SceneLightTest(unittest.TestCase):
    def test_light_types_export_with_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SceneStore(Path(directory)/'scenes');store.open('s')
            objects={'sun':{'kind':'light','intensity':500},
                     'ambient':{'kind':'light','intensity':300,'light':{'type':'dome','color':[.8,.9,1], 'exposure':1}},
                     'fill':{'kind':'light','intensity':1200,'light':{'type':'sphere','radius_m':.15}},
                     'panel':{'kind':'light','intensity':1000,'light':{'type':'rect','width_m':2,'height_m':.5}}}
            store.apply('s',0,'lights',[{'op':'add','id':k,'object':v} for k,v in objects.items()])
            path=Path(directory)/'scene.usda';export_scene(store.get('s'),path);stage=Usd.Stage.Open(str(path))
            for name,kind in [('sun',UsdLux.DistantLight),('ambient',UsdLux.DomeLight),('fill',UsdLux.SphereLight),('panel',UsdLux.RectLight)]:
                self.assertTrue(stage.GetPrimAtPath('/World/'+name).IsA(kind))
            self.assertAlmostEqual(UsdLux.DomeLight(stage.GetPrimAtPath('/World/ambient')).GetExposureAttr().Get(),1)
            self.assertAlmostEqual(UsdLux.SphereLight(stage.GetPrimAtPath('/World/fill')).GetRadiusAttr().Get(),.15,places=6)
            rect=UsdLux.RectLight(stage.GetPrimAtPath('/World/panel'))
            self.assertAlmostEqual(rect.GetWidthAttr().Get(),2);self.assertAlmostEqual(rect.GetHeightAttr().Get(),.5)
    def test_invalid_light_inputs_fail_before_export(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SceneStore(Path(directory));store.open('s')
            for value in [{'type':'ambient'}, {'type':[]}, {'type':'dome','radius_m':1},
                          {'type':'rect','width_m':0}, {'type':'sphere','radius_m':float('nan')},
                          {'type':'distant','color':[1,2,3]}, {'type':'dome','exposure':float('inf')}]:
                self.assertTrue(validate({'objects':{'lamp':{'kind':'light','light':value}}}))
                with self.subTest(value=value),self.assertRaises(ValueError):
                    store.apply('s',0,'bad',[{'op':'add','id':'lamp','object':{'kind':'light','light':value}}])

if __name__=='__main__':unittest.main()
