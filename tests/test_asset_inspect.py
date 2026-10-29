import tempfile
import unittest
from pathlib import Path
from pxr import Usd, UsdGeom, UsdPhysics
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
