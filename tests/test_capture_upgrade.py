import json,tempfile,unittest
from pathlib import Path
from simscene.scene import SceneStore,SceneError,validate
from simscene.capture import camera_config

class CaptureUpgradeTest(unittest.TestCase):
    def test_profile_optics_native_aspect_and_units(self):
        from simscene.usd_export import export_scene
        from pxr import Usd,UsdGeom
        scene={'revision':0,'presentation':{'profile':'technical_showcase_1080p'},'objects':{'cam':{'kind':'camera','camera':{'focal_length_mm':50,'focus_distance_m':2}}}}
        self.assertFalse(validate(scene));self.assertEqual(camera_config(scene,scene['objects']['cam'])['fps'],30)
        with tempfile.TemporaryDirectory() as root:
            result=export_scene(scene,Path(root)/'scene.usda');stage=Usd.Stage.Open(result['path']);cam=UsdGeom.Camera(stage.GetPrimAtPath('/World/cam'))
            self.assertAlmostEqual(cam.GetFocalLengthAttr().Get(),.5)
            self.assertAlmostEqual(cam.GetHorizontalApertureAttr().Get()/cam.GetVerticalApertureAttr().Get(),16/9,places=6)
            self.assertEqual(cam.GetFocusDistanceAttr().Get(),2)
            self.assertEqual(cam.GetFStopAttr().Get(),0)
    def test_invalid_and_atomic_configuration(self):
        for config in ({'resolution':[1920,1081]},{'focal_length_mm':float('nan')},{'capture_window':{'start_step':1}}):
            self.assertTrue(validate({'objects':{'cam':{'kind':'camera','record_fps':30,'camera':config}}}))
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('scene')
            with self.assertRaises(SceneError):s.apply('scene',0,'bad',[{'op':'set_presentation','presentation':{'profile':'unknown'}}])
            self.assertEqual(s.get('scene')['revision'],0)
    def test_real_encoder_native_frame_clock_and_evidence(self):
        import numpy as np
        from simscene.worker.video import VideoRecorder
        from simscene.video_tools import inspect
        from simscene.evidence_integrity import seal,verify
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);r=VideoRecorder(root/'native.mp4',30,320,180,start_step=60)
            frame=np.full((180,320,3),100,np.uint8)
            with self.assertRaisesRegex(RuntimeError,'clock'):r.write(frame,61)
            for i in range(6):r.write(frame,62+2*i)
            video=r.close();report=inspect(video['path'],record=video)
            self.assertTrue(report['simulation_timeline']['passed']);self.assertEqual(report['decoded_frame_count'],6)
            (root/'result.json').write_text(json.dumps({'videos':{'cam':video}}));seal(root)
            self.assertTrue(verify(root)['passed'])
            Path(video['frame_manifest']).write_text('{}\n');self.assertFalse(verify(root)['passed'])
    def test_camera_motion_and_embedded_light_control_are_authored(self):
        from pxr import Usd,UsdGeom,UsdLux
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=Usd.Stage.CreateNew(str(root/'light.usda'));UsdGeom.SetStageMetersPerUnit(source,1);UsdGeom.SetStageUpAxis(source,'Z');model=UsdGeom.Xform.Define(source,'/Model');source.SetDefaultPrim(model.GetPrim());UsdLux.DiskLight.Define(source,'/Model/Light').CreateIntensityAttr(5000);source.GetRootLayer().Save()
            scene={'revision':0,'objects':{'device':{'kind':'asset','asset_path':str(root/'light.usda'),'asset_lights':'disabled'},'cam':{'kind':'camera','camera_path':[{'time_s':0,'position':[0,-2,1],'target':[0,0,0]},{'time_s':1,'position':[2,0,1],'target':[0,0,0]}]}}}
            result=export_scene(scene,root/'out.usda');stage=Usd.Stage.Open(result['path']);self.assertEqual(UsdLux.DiskLight(stage.GetPrimAtPath('/World/device/Asset/Light')).GetIntensityAttr().Get(),0)
            transform=UsdGeom.Xformable(stage.GetPrimAtPath('/World/cam'));self.assertEqual(list(transform.GetLocalTransformation(Usd.TimeCode(60)).ExtractTranslation()),[2,0,1])
            self.assertEqual(UsdLux.DiskLight(source.GetPrimAtPath('/Model/Light')).GetIntensityAttr().Get(),5000)
