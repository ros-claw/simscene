import hashlib
import importlib.util
import math
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.preparation.profiles import PreparationError

try:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
except ImportError:
    Usd = None


@unittest.skipIf(Usd is None, 'requires OpenUSD')
class TwoDofInspectionTests(unittest.TestCase):
    def stage(self, *, chain=False):
        stage = Usd.Stage.CreateInMemory()
        root = UsdGeom.Xform.Define(stage, '/Asset').GetPrim()
        stage.SetDefaultPrim(root)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.Xform.Define(stage, '/Asset/Links')
        UsdGeom.Xform.Define(stage, '/Asset/Joints')
        for name, mass in (('Base', 10.0), ('First', 2.0), ('Second', 3.0)):
            prim = UsdGeom.Xform.Define(stage, '/Asset/Links/' + name).GetPrim()
            UsdPhysics.RigidBodyAPI.Apply(prim)
            UsdPhysics.MassAPI.Apply(prim).CreateMassAttr(mass)
            shape = UsdGeom.Cube.Define(stage, str(prim.GetPath()) + '/Collider')
            UsdPhysics.CollisionAPI.Apply(shape.GetPrim())
        UsdPhysics.ArticulationRootAPI.Apply(stage.GetPrimAtPath('/Asset/Links/Base'))
        slide = UsdPhysics.PrismaticJoint.Define(stage, '/Asset/Joints/Slide')
        slide.CreateBody0Rel().SetTargets(['/Asset/Links/Base'])
        slide.CreateBody1Rel().SetTargets(['/Asset/Links/First'])
        slide.CreateAxisAttr('X')
        slide.CreateLowerLimitAttr(0.0)
        slide.CreateUpperLimitAttr(0.5)
        slide.CreateLocalPos0Attr(Gf.Vec3f(0.1, 0.2, 0.3))
        drive = UsdPhysics.DriveAPI.Apply(slide.GetPrim(), 'linear')
        drive.CreateTypeAttr('force')
        drive.CreateStiffnessAttr(12.0)
        drive.CreateDampingAttr(4.0)
        drive.CreateMaxForceAttr(150.0)
        drive.CreateTargetPositionAttr(0.25)
        hinge = UsdPhysics.RevoluteJoint.Define(stage, '/Asset/Joints/Hinge')
        hinge.CreateBody0Rel().SetTargets(['/Asset/Links/First' if chain else '/Asset/Links/Base'])
        hinge.CreateBody1Rel().SetTargets(['/Asset/Links/Second'])
        hinge.CreateAxisAttr('Z')
        hinge.CreateLowerLimitAttr(-90.0)
        hinge.CreateUpperLimitAttr(90.0)
        hinge.CreateLocalRot0Attr(Gf.Quatf(0.70710678, Gf.Vec3f(0, 0, 0.70710678)))
        return stage

    def inspect(self, stage):
        spec = importlib.util.find_spec('simscene.preparation.articulation_v2')
        self.assertIsNotNone(spec, 'two-DOF static inspector is not implemented')
        from simscene.preparation.articulation_v2 import inspect_articulation_v2
        return inspect_articulation_v2(stage)

    def test_branch_records_actual_endpoints_limits_frames_and_raw_drive_without_mutating_stage(self):
        stage = self.stage()
        before = stage.GetRootLayer().ExportToString()
        report = self.inspect(stage)
        self.assertEqual(stage.GetRootLayer().ExportToString(), before)
        self.assertEqual(report.get('schema'), 'simscene.articulation_inspection.v2')
        self.assertEqual(report.get('schema_version'), 2)
        self.assertEqual(len(report['body_map']), 3)
        self.assertEqual(len(report['joint_map']), 2)
        joints = {j['relative_prim_path']: j for j in report['joint_map'].values()}
        self.assertEqual(set(joints), {'Joints/Slide', 'Joints/Hinge'})
        slide, hinge = joints['Joints/Slide'], joints['Joints/Hinge']
        for item, child in ((slide, 'Links/First'), (hinge, 'Links/Second')):
            self.assertEqual(report['body_map'][item['parent_body_id']]['relative_prim_path'], 'Links/Base')
            self.assertEqual(report['body_map'][item['child_body_id']]['relative_prim_path'], child)
        self.assertEqual(slide['type'], 'prismatic')
        self.assertIs(slide.get('joint_enabled'), True)
        self.assertIs(slide.get('exclude_from_articulation'), False)
        self.assertEqual(slide['limits'], [0.0, 0.5])
        self.assertEqual(slide['position_unit'], 'm')
        self.assertAlmostEqual(slide['local_pos0_m'][1], 0.2, places=6)
        self.assertEqual(slide['drive']['type'], 'force')
        self.assertEqual(slide['drive']['stiffness'], 12.0)
        self.assertEqual(slide['drive']['max_force'], 150.0)
        self.assertEqual(slide['drive']['target_position'], 0.25)
        self.assertEqual(hinge['type'], 'revolute')
        self.assertEqual(hinge['position_unit'], 'rad')
        self.assertAlmostEqual(hinge['limits'][0], -math.pi / 2)
        self.assertAlmostEqual(hinge['limits'][1], math.pi / 2)
        self.assertAlmostEqual(hinge['local_rot0_wxyz'][3], math.sqrt(0.5), places=6)
        self.assertIsNone(hinge['drive'])
        self.assertIn('not runtime', report['scope'].lower())

    def test_series_graph_keeps_the_intermediate_body_as_parent(self):
        report = self.inspect(self.stage(chain=True))
        hinge = next(j for j in report['joint_map'].values() if j['relative_prim_path'] == 'Joints/Hinge')
        self.assertEqual(report['body_map'][hinge['parent_body_id']]['relative_prim_path'], 'Links/First')
        self.assertEqual(report['body_map'][hinge['child_body_id']]['relative_prim_path'], 'Links/Second')

    def test_world_fixed_base_is_reported_but_is_not_a_dof(self):
        stage = self.stage()
        anchor = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Anchor')
        anchor.CreateBody1Rel().SetTargets(['/Asset/Links/Base'])
        report = self.inspect(stage)
        self.assertEqual(len(report['joint_map']), 2)
        self.assertEqual(report['fixed_joint_paths'], ['Joints/Anchor'])

    def test_world_fixed_joint_can_carry_the_articulation_root_api(self):
        stage = self.stage()
        anchor = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Anchor')
        anchor.CreateBody1Rel().SetTargets(['/Asset/Links/Base'])
        stage.GetPrimAtPath('/Asset/Links/Base').RemoveAPI(UsdPhysics.ArticulationRootAPI)
        UsdPhysics.ArticulationRootAPI.Apply(anchor.GetPrim())
        report = self.inspect(stage)
        self.assertEqual(report['articulation_root_paths'], ['Joints/Anchor'])

    def test_fixed_anchor_with_drive_is_not_misreported_as_undriven(self):
        stage = self.stage()
        anchor = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Anchor')
        anchor.CreateBody1Rel().SetTargets(['/Asset/Links/Base'])
        UsdPhysics.DriveAPI.Apply(anchor.GetPrim(), 'angular')
        with self.assertRaises(PreparationError):
            self.inspect(stage)

    def test_external_constraint_cannot_silently_change_the_selected_graph(self):
        stage = self.stage()
        UsdGeom.Xform.Define(stage, '/Outside')
        foreign = UsdPhysics.FixedJoint.Define(stage, '/Outside/Anchor')
        foreign.CreateBody1Rel().SetTargets(['/Asset/Links/Base'])
        with self.assertRaises(PreparationError):
            self.inspect(stage)
        foreign.GetBody1Rel().SetTargets(['/Outside/Unrelated'])
        self.assertEqual(len(self.inspect(stage)['joint_map']), 2)

    def test_rejects_graph_with_cycle_duplicate_child_world_endpoint_or_external_body(self):
        for mutation in ('cycle', 'duplicate_child', 'world_endpoint', 'missing_body', 'self_edge', 'extra_joint'):
            with self.subTest(mutation=mutation):
                stage = self.stage()
                hinge = UsdPhysics.Joint(stage.GetPrimAtPath('/Asset/Joints/Hinge'))
                if mutation == 'cycle':
                    hinge.GetBody0Rel().SetTargets(['/Asset/Links/First'])
                    hinge.GetBody1Rel().SetTargets(['/Asset/Links/Base'])
                elif mutation == 'duplicate_child':
                    hinge.GetBody1Rel().SetTargets(['/Asset/Links/First'])
                elif mutation == 'world_endpoint':
                    hinge.GetBody0Rel().ClearTargets(True)
                elif mutation == 'missing_body':
                    hinge.GetBody0Rel().SetTargets(['/Outside'])
                elif mutation == 'self_edge':
                    hinge.GetBody1Rel().SetTargets(['/Asset/Links/Base'])
                else:
                    extra = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Extra')
                    extra.CreateBody0Rel().SetTargets(['/Asset/Links/First'])
                    extra.CreateBody1Rel().SetTargets(['/Asset/Links/Second'])
                with self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_rejects_world_fixed_joint_to_nonroot_or_multiple_world_anchors(self):
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                stage = self.stage()
                anchor = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Anchor')
                anchor.CreateBody1Rel().SetTargets(['/Asset/Links/Base' if multiple else '/Asset/Links/First'])
                if multiple:
                    extra = UsdPhysics.FixedJoint.Define(stage, '/Asset/Joints/Anchor2')
                    extra.CreateBody1Rel().SetTargets(['/Asset/Links/Base'])
                with self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_rejects_disabled_excluded_invalid_limits_and_missing_axis(self):
        for mutation in ('disabled', 'excluded', 'axis_missing', 'axis_invalid', 'limit_missing',
                         'limit_infinite', 'limit_reversed', 'locked'):
            with self.subTest(mutation=mutation):
                stage = self.stage()
                prim = stage.GetPrimAtPath('/Asset/Joints/Slide')
                joint = UsdPhysics.PrismaticJoint(prim)
                if mutation == 'disabled':
                    joint.CreateJointEnabledAttr(False)
                elif mutation == 'excluded':
                    joint.CreateExcludeFromArticulationAttr(True)
                elif mutation == 'axis_missing':
                    prim.RemoveProperty('physics:axis')
                elif mutation == 'axis_invalid':
                    joint.GetAxisAttr().Set('Q')
                elif mutation == 'limit_missing':
                    prim.RemoveProperty('physics:upperLimit')
                elif mutation == 'limit_infinite':
                    joint.GetUpperLimitAttr().Set(float('inf'))
                elif mutation == 'limit_reversed':
                    joint.GetUpperLimitAttr().Set(-1.0)
                else:
                    joint.GetUpperLimitAttr().Set(0.0)
                with self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_rejects_coupling_markers_and_unsupported_multi_axis_joints(self):
        for mutation in ('mimic_schema', 'gear_attribute', 'coupling_relationship', 'spherical', 'extra_axis_drive'):
            with self.subTest(mutation=mutation):
                stage = self.stage()
                prim = stage.GetPrimAtPath('/Asset/Joints/Slide')
                if mutation == 'mimic_schema':
                    schemas = list(prim.GetMetadata('apiSchemas').GetAppliedItems())
                    schemas.append('PhysxMimicJointAPI:linear')
                    prim.SetMetadata('apiSchemas', Sdf.TokenListOp.CreateExplicit(schemas))
                elif mutation == 'gear_attribute':
                    prim.CreateAttribute('physxGear:ratio', Sdf.ValueTypeNames.Float, custom=True).Set(2.0)
                elif mutation == 'coupling_relationship':
                    prim.CreateRelationship('physxCoupling:joint', custom=True).SetTargets(['/Asset/Joints/Hinge'])
                elif mutation == 'spherical':
                    UsdPhysics.SphericalJoint.Define(stage, '/Asset/Joints/Slide')
                else:
                    UsdPhysics.DriveAPI.Apply(prim, 'angular')
                with self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_rejects_missing_mass_disabled_body_missing_collision_or_unsafe_ancestors(self):
        for mutation in ('mass_missing', 'mass_zero', 'body_disabled', 'kinematic', 'collider_missing',
                         'collider_disabled', 'body_scaled', 'joint_ancestor_scaled', 'stage_units', 'nan_units'):
            with self.subTest(mutation=mutation):
                stage = self.stage()
                prim = stage.GetPrimAtPath('/Asset/Links/First')
                if mutation == 'mass_missing':
                    prim.RemoveProperty('physics:mass')
                elif mutation == 'mass_zero':
                    UsdPhysics.MassAPI(prim).GetMassAttr().Set(0.0)
                elif mutation == 'body_disabled':
                    UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr(False)
                elif mutation == 'kinematic':
                    UsdPhysics.RigidBodyAPI(prim).CreateKinematicEnabledAttr(True)
                elif mutation == 'collider_missing':
                    stage.RemovePrim('/Asset/Links/First/Collider')
                elif mutation == 'collider_disabled':
                    UsdPhysics.CollisionAPI(stage.GetPrimAtPath('/Asset/Links/First/Collider')).CreateCollisionEnabledAttr(False)
                elif mutation == 'body_scaled':
                    UsdGeom.Xformable(prim).AddScaleOp().Set(Gf.Vec3f(2, 1, 1))
                elif mutation == 'joint_ancestor_scaled':
                    UsdGeom.Xformable(stage.GetPrimAtPath('/Asset/Joints')).AddScaleOp().Set(Gf.Vec3f(2, 1, 1))
                elif mutation == 'stage_units':
                    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
                else:
                    UsdGeom.SetStageMetersPerUnit(stage, float('nan'))
                with self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_rejects_non_normalized_joint_frame(self):
        stage = self.stage()
        joint = UsdPhysics.Joint(stage.GetPrimAtPath('/Asset/Joints/Slide'))
        joint.CreateLocalRot0Attr(Gf.Quatf(2.0, Gf.Vec3f(0, 0, 0)))
        with self.assertRaises(PreparationError):
            self.inspect(stage)

    def test_mass_values_are_not_mislabeled_as_kg_with_noncanonical_stage_units(self):
        for kilograms_per_unit in (0.1, 10.0, float('nan')):
            with self.subTest(kilograms_per_unit=kilograms_per_unit):
                stage = self.stage()
                UsdPhysics.SetStageKilogramsPerUnit(stage, kilograms_per_unit)
                # The legacy v1 canonical check did not validate mass units;
                # v2 must retain this guard independently of that helper.
                with patch('simscene.preparation.articulation_v2.canonical_stage'), self.assertRaises(PreparationError):
                    self.inspect(stage)

    def test_blocked_physics_defaults_are_rejected_as_unsupported(self):
        for mutation in ('excluded', 'kinematic', 'joint_rotation', 'inertia', 'drive_target'):
            with self.subTest(mutation=mutation):
                stage = self.stage()
                joint = UsdPhysics.Joint(stage.GetPrimAtPath('/Asset/Joints/Slide'))
                link = stage.GetPrimAtPath('/Asset/Links/First')
                if mutation == 'excluded':
                    joint.GetExcludeFromArticulationAttr().Block()
                elif mutation == 'kinematic':
                    UsdPhysics.RigidBodyAPI(link).GetKinematicEnabledAttr().Block()
                elif mutation == 'joint_rotation':
                    joint.GetLocalRot0Attr().Block()
                elif mutation == 'inertia':
                    UsdPhysics.MassAPI(link).GetDiagonalInertiaAttr().Block()
                else:
                    UsdPhysics.DriveAPI(joint.GetPrim(), 'linear').GetTargetPositionAttr().Block()
                try:
                    self.inspect(stage)
                except PreparationError:
                    pass
                except Exception as error:
                    self.fail('unsupported blocked value raised wrong error: ' + repr(error))
                else:
                    self.fail('blocked native physics value was accepted')

    def test_rejects_animated_ancestor_outside_selected_root(self):
        source = self.stage()
        stage = Usd.Stage.CreateInMemory()
        world = UsdGeom.Xform.Define(stage, '/World')
        stage.SetDefaultPrim(world.GetPrim())
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        world.AddTranslateOp().Set(Gf.Vec3d(2, 0, 0), Usd.TimeCode(1))
        selected = UsdGeom.Xform.Define(stage, '/World/Asset').GetPrim()
        selected.GetReferences().AddReference(source.GetRootLayer().identifier)
        from simscene.preparation.articulation_v2 import inspect_articulation_v2
        with self.assertRaises(PreparationError):
            inspect_articulation_v2(stage, selected)

    def test_real_pinned_two_drawer_sample_remains_unchanged(self):
        selected = os.environ.get('SIMSCENE_TWO_DOF_SAMPLE')
        if not selected:
            self.skipTest('set SIMSCENE_TWO_DOF_SAMPLE to the pinned USDCraft model.usdc')
        path = Path(selected)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, 'e5070e0690c183629f0d24d2465d5ff0b53b88cd71b3682200650e05e009c7d0')
        stage = Usd.Stage.Open(str(path))
        report = self.inspect(stage)
        self.assertEqual(len(report['body_map']), 3)
        joints = {j['relative_prim_path']: j for j in report['joint_map'].values()}
        self.assertEqual(set(joints), {'Joints/slide_lower', 'Joints/slide_upper'})
        for joint in joints.values():
            self.assertEqual(joint['limits'], [0.0, 0.5])
            self.assertEqual(joint['drive']['type'], 'force')
            self.assertEqual(joint['drive']['stiffness'], 0.0)
        self.assertEqual(sum(len(b['collider_relative_prim_paths']) for b in report['body_map'].values()), 33)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
