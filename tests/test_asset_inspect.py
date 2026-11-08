import tempfile
import unittest
from pathlib import Path
from pxr import Usd, UsdGeom, UsdPhysics, Gf
from simscene.asset_inspect import inspect_local

class InspectionTest(unittest.TestCase):
    def test_reports_geometry_and_authored_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'asset.usda'); stage=Usd.Stage.CreateNew(path)
            UsdGeom.SetStageMetersPerUnit(stage,1.0); UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
            cube=UsdGeom.Cube.Define(stage,'/cube'); cube.CreateSizeAttr(2)
            stage.SetDefaultPrim(cube.GetPrim()); UsdPhysics.CollisionAPI.Apply(cube.GetPrim()); stage.GetRootLayer().Save()
            report=inspect_local(path)
            self.assertEqual(report['bounds']['dimensions_units'],[2,2,2])
            self.assertEqual(report['bounds']['dimensions_m_in_source_axes'],[2,2,2])
            self.assertTrue(report['meters_per_unit_authored'])
            self.assertEqual(report['collision_prims'],['/cube'])
            self.assertEqual(report['behavior_validation'],'not verified')

    def test_existing_hinge_reports_source_units_and_active_drive(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'cabinet.usda');stage=Usd.Stage.CreateNew(path)
            UsdGeom.SetStageMetersPerUnit(stage,.01)
            cabinet=UsdGeom.Xform.Define(stage,'/Cabinet');stage.SetDefaultPrim(cabinet.GetPrim())
            door=UsdGeom.Cube.Define(stage,'/Cabinet/Door');UsdPhysics.RigidBodyAPI.Apply(door.GetPrim())
            hinge=UsdPhysics.RevoluteJoint.Define(stage,'/Cabinet/Hinge')
            hinge.CreateBody1Rel().SetTargets([door.GetPath()]);hinge.CreateAxisAttr('Y')
            hinge.CreateLocalPos0Attr(Gf.Vec3f(10,0,0));hinge.CreateLowerLimitAttr(-90);hinge.CreateUpperLimitAttr(0)
            drive=UsdPhysics.DriveAPI.Apply(hinge.GetPrim(),'angular');drive.CreateTargetPositionAttr(-30)
            stage.GetRootLayer().Save()
            report=inspect_local(path);joint=report['joints'][0]
            self.assertEqual(report['joint_count'],1)
            self.assertEqual(joint['body1'],['/Cabinet/Door'])
            self.assertEqual(joint['local_pos0_units'],[10,0,0])
            self.assertEqual(report['meters_per_unit'],.01)
            self.assertEqual(joint['physics:axis'],'Y')
            self.assertEqual(joint['physics:lowerLimit'],-90)
            self.assertIn('PhysicsDriveAPI:angular',joint['drives'])
