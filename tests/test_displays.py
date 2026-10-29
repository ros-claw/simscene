import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from pxr import Usd,UsdGeom,UsdShade
from simscene.scene import SceneStore,SceneError
from simscene.usd_export import export_scene
from simscene.display_runtime import update


class DisplayTest(unittest.TestCase):
    def test_scene_counters_and_status_follow_measured_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SceneStore(root/'data');store.open('s')
            cfg={'experimental':True,'model_directory':'/m','tool_frame':'tcp','tcp_prim':'tcp','target_position':[0,0,1]}
            # Use a real local USD asset because export checks source units.
            source=Usd.Stage.CreateNew(str(root/'robot.usda'));prim=UsdGeom.Xform.Define(source,'/Robot').GetPrim()
            source.SetDefaultPrim(prim);UsdGeom.SetStageMetersPerUnit(source,1);UsdGeom.SetStageUpAxis(source,'Z');source.GetRootLayer().Save()
            ops=[{'op':'add','id':'arm','object':{'kind':'asset','asset_path':str(root/'robot.usda'),'pose_follower':cfg}},
                 {'op':'add','id':'status','object':{'kind':'box','indicator':{'robot_id':'arm'}}},
                 {'op':'add','id':'counts','object':{'kind':'counter','counter':{'source':'verified_archives','class_label':'red','digits':2}}},
                 {'op':'add','id':'feed','object':{'kind':'counter','counter':{'source':'spawned','digits':2,'scale':2}}}]
            store.apply('s',0,'create',ops);scene=store.get('s')
            export_scene(scene,root/'scene.usda');stage=Usd.Stage.Open(str(root/'scene.usda'))
            self.assertEqual(list(UsdGeom.Xformable(stage.GetPrimAtPath('/World/feed')).GetOrderedXformOps()[-1].Get()),[2,2,2])
            follower=SimpleNamespace(sequence=[{'type':'wait_object'},{'type':'move'}],sequence_index=0,sequence_error=None)
            last={};data=update(stage,scene,{'arm':follower},[{'class_label':'red'}],{},False,last)
            self.assertEqual(data['feed']['value'],1);self.assertFalse(data['counts']['available'])
            self.assertEqual(data['status']['controller_phase_state'],'waiting')
            self.assertEqual(UsdGeom.Imageable(stage.GetPrimAtPath('/World/counts')).GetVisibilityAttr().Get(),'invisible')
            follower.sequence_index=1
            data=update(stage,scene,{'arm':follower},[{'class_label':'red'}],{'one':{'class_label':'red'}},True,last)
            self.assertEqual(data['counts']['value'],1);self.assertEqual(data['status']['controller_phase_state'],'active')
            self.assertEqual(UsdGeom.Imageable(stage.GetPrimAtPath('/World/counts')).GetVisibilityAttr().Get(),'inherited')
            color=UsdShade.Shader(stage.GetPrimAtPath('/World/Looks/status/PreviewSurface')).GetInput('emissiveColor').Get()
            self.assertGreater(color[1],color[0]);follower.sequence_error='stopped'
            update(stage,scene,{'arm':follower},[],{},True,last)
            color=UsdShade.Shader(stage.GetPrimAtPath('/World/Looks/status/PreviewSurface')).GetInput('emissiveColor').Get()
            self.assertGreater(color[0],color[1])
            data=update(stage,scene,{'arm':follower},[{'class_label':'red'}]*100,{},True,last)
            self.assertTrue(data['feed']['overflow']);self.assertEqual(data['feed']['value'],100)
            for index in range(2):
                middle=stage.GetPrimAtPath(f'/World/feed/digit_{index}/g')
                self.assertEqual(UsdGeom.Imageable(middle).GetVisibilityAttr().Get(),'inherited')

    def test_indicator_requires_real_robot_and_noncolliding_geometry(self):
        with tempfile.TemporaryDirectory() as root:
            store=SceneStore(root);store.open('s')
            with self.assertRaises(SceneError):store.apply('s',0,'bad',[{'op':'add','id':'light','object':{'kind':'box','indicator':{'robot_id':'missing'}}}])
