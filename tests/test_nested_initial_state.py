import unittest
try:
    import numpy as np
except ImportError:
    np=None
try:
    from pxr import Usd,UsdGeom,UsdPhysics,Gf
except ImportError:
    Usd=None
if np is not None:
    from simscene.worker.initial_state import capture_authored_state,restore_local_ops,visual_bounds,PassiveState

@unittest.skipUnless(Usd and np is not None,'OpenUSD and NumPy are optional on the CPU host')
class NestedInitialStateTests(unittest.TestCase):
    def stage(self):
        stage=Usd.Stage.CreateInMemory();UsdGeom.Xform.Define(stage,'/World')
        parent=UsdGeom.Xform.Define(stage,'/World/item');parent.AddTranslateOp().Set((1,2,3));parent.AddRotateZOp().Set(90)
        body=UsdGeom.Xform.Define(stage,'/World/item/Asset/Body');UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
        local=body.AddTranslateOp();local.Set((.2,0,0))
        cube=UsdGeom.Cube.Define(stage,'/World/item/Asset/Body/Visual');cube.CreateSizeAttr(.2)
        objects={'item':{'kind':'asset','dynamic':True,'position':[1,2,3]}}
        bindings={'item':{'motion_body':'/World/item/Asset/Body','visual_roots':['/World/item/Asset/Body/Visual']}}
        return stage,objects,bindings

    def test_capture_world_and_restore_local_without_world_translation(self):
        stage,objects,bindings=self.stage();snapshot=capture_authored_state(stage,objects,bindings)
        body=snapshot['bodies']['/World/item/Asset/Body']
        np.testing.assert_allclose(body['position'],[1,2.2,3],atol=1e-6)
        prim=stage.GetPrimAtPath('/World/item/Asset/Body');prim.GetAttribute('xformOp:translate').Set((8,9,10));UsdGeom.Xformable(prim).AddOrientOp().Set(Gf.Quatf(1))
        restore_local_ops(stage,snapshot)
        self.assertEqual(tuple(prim.GetAttribute('xformOp:translate').Get()),(.2,0,0))
        self.assertFalse(prim.GetAttribute('xformOp:orient'))
        measured=capture_authored_state(stage,objects,bindings)
        np.testing.assert_allclose(measured['bodies'][str(prim.GetPath())]['position'],[1,2.2,3],atol=1e-6)

    def test_fresh_visual_bounds_follow_nested_parent_and_exclude_other_geometry(self):
        stage,objects,bindings=self.stage();first=visual_bounds(stage,objects,bindings)
        extra=UsdGeom.Cube.Define(stage,'/World/item/Asset/Unrelated');extra.CreateSizeAttr(100)
        self.assertEqual(first,visual_bounds(stage,objects,bindings))
        stage.GetPrimAtPath('/World/item').GetAttribute('xformOp:translate').Set((1,2,4))
        second=visual_bounds(stage,objects,bindings)
        self.assertAlmostEqual(second['item']['min'][2]-first['item']['min'][2],1)

    def test_single_tensor_reset_uses_world_targets_and_preserves_local_ops(self):
        stage,objects,bindings=self.stage();snapshot=capture_authored_state(stage,objects,bindings)
        class View:
            def __init__(self):self.transforms=np.zeros((1,7));self.transforms[:,6]=1;self.velocities=np.ones((1,6))
            def get_transforms(self):return self.transforms
            def get_velocities(self):return self.velocities
            def set_transforms(self,data,indices):self.transforms=data.copy()
            def set_velocities(self,data,indices):self.velocities=data.copy()
        state=PassiveState.__new__(PassiveState);state.stage=stage;state.objects=objects;state.body_bindings=bindings;state.authored_state=snapshot;state._reset_count=0;state.paths=['/World/item/Asset/Body'];state.view=View()
        report=state.reset_before_task();self.assertTrue(report['local_xform_ops_restored'])
        np.testing.assert_allclose(state.view.transforms[0,:3],[1,2.2,3],atol=1e-6)
        self.assertEqual(tuple(stage.GetPrimAtPath(state.paths[0]).GetAttribute('xformOp:translate').Get()),(.2,0,0))
        with self.assertRaises(RuntimeError):state.reset_before_task()

if __name__=='__main__':unittest.main()
