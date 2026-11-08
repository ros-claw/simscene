import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from simscene.scene import validate
from simscene.placement import bounds
from simscene.usd_export import export_scene
try:
    from pxr import Usd,UsdGeom,UsdPhysics
except ImportError:
    Usd=None


class VisibilityContract(unittest.TestCase):
    def test_visibility_changes_neither_geometric_bounds_nor_collision_declaration(self):
        box={'kind':'box','size':[1,.5,.03],'position':[0,0,1],'collision':True}
        self.assertEqual(bounds(box),bounds(dict(box,visible=False)))
        self.assertEqual(validate({'objects':{'proxy':dict(box,visible=False)}}),[])
        for obj in (dict(box,visible=0),{'kind':'light','visible':False},{'kind':'asset','asset_path':'local.usda','visible':False}):
            self.assertTrue(any('visible must be boolean' in item['message'] for item in validate({'objects':{'bad':obj}})))

    @unittest.skipIf(Usd is None,'USD unavailable')
    def test_actual_usd_hides_the_proxy_while_retaining_physics_and_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scene.usda'
            scene={'revision':0,'objects':{'proxy':{'kind':'box','size':[1,.5,.03],'position':[0,0,1],'collision':True,'visible':False},
                              'reference':{'kind':'box','size':[1,.5,.03],'position':[2,0,1],'collision':True}}}
            export_scene(scene,path);stage=Usd.Stage.Open(str(path))
            prim=stage.GetPrimAtPath('/World/proxy');other=stage.GetPrimAtPath('/World/reference')
            self.assertEqual(UsdGeom.Imageable(prim).GetVisibilityAttr().Get(),UsdGeom.Tokens.invisible)
            self.assertEqual(UsdGeom.Imageable(other).GetVisibilityAttr().Get(),UsdGeom.Tokens.inherited)
            self.assertTrue(prim.HasAPI(UsdPhysics.CollisionAPI));self.assertFalse(prim.HasAPI(UsdPhysics.RigidBodyAPI))
            self.assertEqual(UsdGeom.Xformable(prim).GetOrderedXformOps()[0].Get(),UsdGeom.Xformable(other).GetOrderedXformOps()[0].Get()-type(UsdGeom.Xformable(other).GetOrderedXformOps()[0].Get())(2,0,0))

    @unittest.skipIf(Usd is None,'USD unavailable')
    def test_scheduled_geometry_obeys_the_same_visibility_and_explicit_collision_flags(self):
        import pxr
        from simscene.worker.spawn import spawn
        # Only SDK-specific contact-report registration is a stub. The tested
        # imageability, rigid body and collision APIs are actual OpenUSD data.
        report=SimpleNamespace(Apply=lambda prim:SimpleNamespace(CreateThresholdAttr=lambda:SimpleNamespace(Set=lambda value:None)))
        with patch.object(pxr,'PhysxSchema',SimpleNamespace(PhysxContactReportAPI=report),create=True):
            for collision in (None,True,False):
                stage=Usd.Stage.CreateInMemory()
                obj={'kind':'box','size':[.1,.1,.1],'dynamic':True,'visible':False}
                if collision is not None:obj['collision']=collision
                path=spawn(stage,'late',obj);prim=stage.GetPrimAtPath(path)
                self.assertTrue(prim.HasAPI(UsdPhysics.RigidBodyAPI))
                self.assertEqual(prim.HasAPI(UsdPhysics.CollisionAPI),collision is not False)
                self.assertEqual(UsdGeom.Imageable(prim).GetVisibilityAttr().Get(),UsdGeom.Tokens.invisible)


if __name__=='__main__':unittest.main()
