import math,tempfile,unittest
from pathlib import Path
from simscene.scene import SceneStore,SceneError
from simscene.placement import measure

class ImportedPlacementTest(unittest.TestCase):
    def make_asset(self,path):
        from pxr import Usd,UsdGeom,Gf
        stage=Usd.Stage.CreateNew(str(path));UsdGeom.SetStageUpAxis(stage,'Y');UsdGeom.SetStageMetersPerUnit(stage,.01)
        root=UsdGeom.Xform.Define(stage,'/Part');stage.SetDefaultPrim(root.GetPrim());cube=UsdGeom.Cube.Define(stage,'/Part/visual');cube.CreateSizeAttr(1);cube.AddTranslateOp().Set(Gf.Vec3d(10,5,0));cube.AddScaleOp().Set(Gf.Vec3d(20,10,30));stage.GetRootLayer().Save()
    def test_offset_origin_unit_conversion_rotation_and_explicit_support(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'part.usda';self.make_asset(path)
            s=SceneStore(root);s.open('layout')
            s.apply('layout',0,'create',[{'op':'add','id':'desk','object':{'kind':'box','position':[1,2,1],'size':[2,2,.2],'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}},
              {'op':'add','id':'part','object':{'kind':'asset','asset_path':str(path),'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}},
              {'op':'place_on','id':'part','support':'desk','offset_xy':[.2,0]}])
            bound=measure(s.get('layout'),['part'])['objects']['part']['world_bounds_m']
            self.assertAlmostEqual(bound['min'][2],1.1,places=6)
            self.assertAlmostEqual((bound['min'][1]+bound['max'][1])/2,2.2,places=6)
            with self.assertRaisesRegex(SceneError,'explicit support'):
                s.apply('layout',1,'bad',[{'op':'place_on','id':'desk','support':'part'}])
    def test_grid_exclusions_clearance_and_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            s=SceneStore(root);s.open('layout')
            ops=[{'op':'add','id':'table','object':{'kind':'box','size':[1,1,.1],'support_surfaces':{'top':{'min_xy':[-.5,-.5],'max_xy':[.5,.5],'z_m':.05}}}}]
            ops.extend({'op':'add','id':f'p{i}','object':{'kind':'box','size':[.2,.2,.1]}} for i in range(4))
            ops.append({'op':'arrange_grid','ids':['p0','p1','p2','p3'],'support':'table','support_surface':'top','columns':2,'gap_m':.1})
            s.apply('layout',0,'grid',ops);objects=s.get('layout')['objects']
            self.assertAlmostEqual(objects['p3']['position'][0],.15);self.assertAlmostEqual(objects['p3']['position'][1],.15)
            before=s.get('layout')
            with self.assertRaisesRegex(SceneError,'reserved activity'):
                s.apply('layout',1,'blocked',[{'op':'place_on','id':'p0','support':'table','keepout_bounds':[{'min':[-1,-1,0],'max':[1,1,1]}]}])
            self.assertEqual(s.get('layout'),before)
            with self.assertRaisesRegex(SceneError,'exceeds'):
                s.apply('layout',1,'too_large',[{'op':'arrange_grid','ids':['p0','p1','p2','p3'],'support':'table','columns':2,'gap_m':1}])
    def test_explicit_visual_import_preserves_source_and_removes_physics(self):
        from pxr import Usd,UsdGeom,UsdPhysics
        from simscene.usd_export import export_scene
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=Usd.Stage.CreateNew(str(root/'source.usda'));UsdGeom.SetStageUpAxis(source,'Z')
            cube=UsdGeom.Cube.Define(source,'/Root');source.SetDefaultPrim(cube.GetPrim());UsdPhysics.CollisionAPI.Apply(cube.GetPrim());UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim());source.GetRootLayer().Save();original=(root/'source.usda').read_bytes()
            obj={'kind':'asset','asset_path':str(root/'source.usda'),'asset_physics':'visual_only','asset_metrics':{'meters_per_unit':1,'reason':'Source has no root unit metadata; metre dimensions independently inspected.'}}
            result=export_scene({'revision':0,'objects':{'prop':obj}},root/'visual.usda');stage=Usd.Stage.Open(result['path']);prim=stage.GetPrimAtPath('/World/prop/Asset')
            self.assertFalse(prim.HasAPI(UsdPhysics.RigidBodyAPI));self.assertFalse(prim.HasAPI(UsdPhysics.CollisionAPI));self.assertEqual(original,(root/'source.usda').read_bytes())
