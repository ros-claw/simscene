import unittest
from pxr import Gf,Usd,UsdGeom
from simscene.worker.object_pose import position
class ObjectPoseTest(unittest.TestCase):
    def test_reads_current_world_pose_and_missing_object(self):
        stage=Usd.Stage.CreateInMemory();parent=UsdGeom.Xform.Define(stage,'/World')
        parent.AddTranslateOp().Set(Gf.Vec3d(1,2,3))
        child=UsdGeom.Cube.Define(stage,'/World/box_a');child.AddTranslateOp().Set(Gf.Vec3d(.5,0,0))
        self.assertEqual(position(stage,'box-a'),[1.5,2.0,3.0])
        with self.assertRaises(RuntimeError):position(stage,'missing')
