"""Scene-local grip tuning must leave the selected asset untouched."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from pxr import Usd, UsdGeom, UsdPhysics
from simscene.gripper_physics import apply, validate


class GripPhysicsTest(unittest.TestCase):
    def test_override_is_authored_on_the_scene_and_validates_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.usda'
            original = Usd.Stage.CreateNew(str(source)); original.SetDefaultPrim(UsdGeom.Xform.Define(original, '/Robot').GetPrim())
            for name in ('left', 'right'):
                UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(original, '/Robot/'+name).GetPrim())
            joint = UsdPhysics.PrismaticJoint.Define(original, '/Robot/joint').GetPrim()
            UsdPhysics.DriveAPI.Apply(joint, 'linear').CreateMaxForceAttr().Set(5)
            original.GetRootLayer().Save(); digest = hashlib.sha256(source.read_bytes()).hexdigest()
            stage = Usd.Stage.CreateNew(str(root/'scene.usda'))
            UsdGeom.Xform.Define(stage, '/World/arm')
            stage.OverridePrim('/World/arm/Asset').GetReferences().AddReference(str(source))
            config = {'joint_path': 'joint', 'body_paths': ['left', 'right'], 'drive_type': 'linear',
                      'max_force': 20, 'friction': 1}
            self.assertFalse(validate(config))
            apply(stage, '/World/arm', config); stage.GetRootLayer().Save()
            self.assertEqual(UsdPhysics.DriveAPI(stage.GetPrimAtPath('/World/arm/Asset/joint'), 'linear').GetMaxForceAttr().Get(), 20)
            rel = stage.GetPrimAtPath('/World/arm/Asset/left').GetRelationship('material:binding:physics')
            self.assertEqual([str(p) for p in rel.GetTargets()], ['/World/arm/SimSceneGripMaterial'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            self.assertEqual(UsdPhysics.DriveAPI(original.GetPrimAtPath('/Robot/joint'), 'linear').GetMaxForceAttr().Get(), 5)
            self.assertTrue(validate(dict(config, joint_path='../joint')))
            with self.assertRaises(ValueError):
                apply(stage, '/World/arm', dict(config, body_paths=['missing']))


if __name__ == '__main__':
    unittest.main()
