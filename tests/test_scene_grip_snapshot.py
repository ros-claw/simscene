"""Scene-local tuning must work with evictable cached asset snapshots."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from pxr import Usd, UsdGeom, UsdPhysics
from simscene import jobs
from simscene.usd_export import export_scene


class SceneGripSnapshotTest(unittest.TestCase):
    def test_cached_source_stays_usable_after_scene_local_tuning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); digest = 'a'*64; package = root/'cache'/digest; package.mkdir(parents=True)
            source = package/'robot.usda'; stage = Usd.Stage.CreateNew(str(source))
            stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/Robot').GetPrim())
            UsdGeom.SetStageMetersPerUnit(stage, 1); UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            for name in ('left', 'right'):
                UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(stage, '/Robot/'+name).GetPrim())
            joint = UsdPhysics.PrismaticJoint.Define(stage, '/Robot/joint').GetPrim()
            UsdPhysics.DriveAPI.Apply(joint, 'linear').CreateMaxForceAttr().Set(5)
            stage.GetRootLayer().Save(); data = source.read_bytes()
            metadata = {'source': 'https://example.com/robot.usda', 'package_sha256': digest,
                        'files': [{'path': 'robot.usda', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}],
                        'dependency_status': 'resolved_locally'}
            (package/'simscene-lock.json').write_text(json.dumps(metadata))
            config = {'experimental': True, 'model_directory': '/profile', 'tool_frame': 'tip',
                      'tcp_prim': 'tip', 'target_position': [0, 0, 0],
                      'gripper_physics': {'joint_path': 'joint', 'body_paths': ['left', 'right'],
                                          'drive_type': 'linear', 'max_force': 20, 'friction': 1}}
            scene = {'revision': 0, 'objects': {'arm': {'kind': 'asset', 'asset_path': str(source), 'pose_follower': config}}}
            import copy
            from simscene.scene import SceneError
            invalid = copy.deepcopy(scene)
            invalid['objects']['arm']['pose_follower']['gripper_physics']['joint_path'] = 'missing'
            with self.assertRaises(SceneError):
                export_scene(invalid, root/'invalid.usda')
            self.assertFalse((root/'invalid.usda').exists())
            run = root/'run'; run.mkdir()
            record = jobs._snapshot_cached_assets(scene, run)
            export_scene(scene, run/'scene.usda')
            self.assertEqual(record['arm']['kind'], 'snapshot')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(data).hexdigest())
            self.assertIn('./assets/', (run/'scene.usda').read_text())
            shutil.rmtree(root/'cache')
            # The run must refer to its own locked snapshot, not the evicted source.
            loaded = Usd.Stage.Open(str(run/'scene.usda'))
            self.assertEqual(UsdPhysics.DriveAPI(loaded.GetPrimAtPath('/World/arm/Asset/joint'), 'linear').GetMaxForceAttr().Get(), 20)
            rel = loaded.GetPrimAtPath('/World/arm/Asset/left').GetRelationship('material:binding:physics')
            self.assertEqual([str(x) for x in rel.GetTargets()], ['/World/arm/SimSceneGripMaterial'])


if __name__ == '__main__':
    unittest.main()
