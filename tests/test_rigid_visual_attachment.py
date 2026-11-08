import copy,hashlib,math,tempfile,unittest
from pathlib import Path
from simscene.scene import validate
from simscene.usd_export import export_scene

class RigidVisualAttachmentTests(unittest.TestCase):
    def fixture(self,directory):
        from pxr import Usd,UsdGeom,UsdPhysics
        path=Path(directory)/'selected.usda';stage=Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage,.01);UsdGeom.SetStageUpAxis(stage,'Y')
        cube=UsdGeom.Cube.Define(stage,'/Selected');cube.CreateSizeAttr(10)
        UsdGeom.Xformable(cube).AddScaleOp().Set((2,1,1));UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim());UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        stage.SetDefaultPrim(cube.GetPrim());stage.GetRootLayer().Save()
        return {'revision':0,'objects':{
            'selected':{'kind':'asset','asset_path':str(path),'asset_physics':'visual_only','asset_lights':'disabled','rigid_attachment':{'body':'lever'},'position':[.2,0,0]},
            'lever':{'kind':'compound','position':[1,2,3],'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)],'dynamic':True,'mass_kg':.1,'parts':[{'kind':'box','size':[.1,.1,.1],'visible':False}]},
            'pivot':{'kind':'joint','joint':{'type':'revolute','body1':'lever','axis':'Z','local_pos0':[1,2,3]}}}}

    def test_imported_visual_follows_rigid_parent_with_metric_frames_and_source_intact(self):
        from pxr import Usd,UsdGeom,UsdPhysics,Gf
        from simscene.placement import measure
        with tempfile.TemporaryDirectory() as directory:
            scene=self.fixture(directory);source=Path(scene['objects']['selected']['asset_path']);before=hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(validate(scene),[]);dest=Path(directory)/'composed.usda';export_scene(scene,dest);stage=Usd.Stage.Open(str(dest))
            selected=stage.GetPrimAtPath('/World/lever/_visuals/selected')
            self.assertTrue(selected);self.assertFalse(stage.GetPrimAtPath('/World/selected'))
            self.assertEqual([str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)],['/World/lever'])
            box=measure(scene,['selected'])['objects']['selected']['world_bounds_m']
            parent_box=measure(scene,['lever'])['objects']['lever']['world_bounds_m']
            for edge in ('min','max'):
                for value,expected in zip(parent_box[edge],box[edge]):self.assertAlmostEqual(value,expected,places=6)
            for value,expected in zip(box['min'],[.95,2.1,2.95]):self.assertAlmostEqual(value,expected,places=5)
            for value,expected in zip(box['max'],[1.05,2.3,3.05]):self.assertAlmostEqual(value,expected,places=5)
            parent=UsdGeom.Xformable(stage.GetPrimAtPath('/World/lever'));parent.GetOrderedXformOps()[0].Set(Gf.Vec3d(2,2,3))
            center=UsdGeom.XformCache().GetLocalToWorldTransform(selected).ExtractTranslation()
            for value,expected in zip(center,[2,2.2,3]):self.assertAlmostEqual(value,expected,places=5)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertEqual(UsdGeom.Imageable(stage.GetPrimAtPath('/World/lever/part_0/Shape')).GetVisibilityAttr().Get(),'invisible')
            self.assertTrue(stage.GetPrimAtPath('/World/lever/part_0/Shape').HasAPI(UsdPhysics.CollisionAPI))

    def test_invalid_parent_controller_physics_or_visibility_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original=self.fixture(directory)
            changes=[lambda s:s['objects']['selected'].update(asset_physics='preserve'),lambda s:s['objects']['selected'].update(asset_lights='preserve'),lambda s:s['objects']['selected']['rigid_attachment'].update(body='missing'),lambda s:s['objects']['lever'].update(spawn_step=60),lambda s:s['objects']['lever'].update(dynamic=False),lambda s:s['objects']['lever']['parts'][0].update(visible=1),lambda s:s['objects']['selected'].update(spawn_step=60)]
            for mutate in changes:
                scene=copy.deepcopy(original);mutate(scene)
                with self.subTest(mutate=mutate):self.assertTrue(validate(scene))

if __name__=='__main__':unittest.main()
