import copy
import math
from pathlib import Path
import tempfile
import unittest

from simscene.d6 import AXES, read_limits, relative_observation, resolved_limits, validate_limits, validate_loaded
from simscene.scene import validate
from simscene.usd_export import export_scene


class PassiveD6Tests(unittest.TestCase):
    def scene(self):
        limits = {a: 'locked' for a in AXES}
        limits.update(rotX=[-15, 15], rotY=[-70, 70], rotZ=[-70, 70])
        return {'revision': 0, 'objects': {
            'link': {'kind': 'capsule', 'size': [.008, .008, .033],
                     'dynamic': True, 'mass_kg': .001},
            'joint': {'kind': 'joint', 'joint': {
                'type': 'd6', 'body1': 'link', 'dof_limits': limits}}}}

    def test_explicit_six_modes_are_required_and_legacy_injection_is_rejected(self):
        source = self.scene()
        self.assertEqual(validate(source), [])
        mutations = [
            lambda j: j.pop('dof_limits'),
            lambda j: j['dof_limits'].pop('transZ'),
            lambda j: j['dof_limits'].update(distance=[0, 1]),
            lambda j: j['dof_limits'].update(rotX=[1, -1]),
            lambda j: j['dof_limits'].update(rotX=[0, 0]),
            lambda j: j['dof_limits'].update(rotX=[-180, 180]),
            lambda j: j['dof_limits'].update(rotY=[float('nan'), 4]),
            lambda j: j['dof_limits'].update(transY=[0, float('inf')]),
            lambda j: j['dof_limits'].update(transZ=[False, 1]),
            lambda j: j['dof_limits'].update(transZ=[-1e39, 1e39]),
            lambda j: j['dof_limits'].update(transZ=[1, 1+1e-10]),
            lambda j: j['dof_limits'].update(rotX=[-180+1e-8, 180-1e-8]),
            lambda j: j['dof_limits'].update(rotZ='unlimited'),
            lambda j: j.update(axis='X'),
            lambda j: j.update(lower_limit=0, upper_limit=1),
            lambda j: j.update(drive={'target': 0}),
            lambda j: j.update(type='spherical'),
        ]
        for mutate in mutations:
            scene = copy.deepcopy(source)
            mutate(scene['objects']['joint']['joint'])
            with self.subTest(scene=scene):
                self.assertTrue(validate(scene))

    def test_native_usd_lock_sentinel_free_absence_and_finite_ranges(self):
        from pxr import Usd, UsdPhysics
        scene = self.scene()
        scene['objects']['joint']['joint']['dof_limits']['rotZ'] = 'free'
        scene['objects']['joint']['joint']['dof_limits']['rotX'] = [-.1, .1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.usda'
            export_scene(scene, path)
            stage = Usd.Stage.Open(str(path))
            prim = stage.GetPrimAtPath('/World/joint')
            self.assertEqual(prim.GetTypeName(), 'PhysicsJoint')
            actual = read_limits(prim)
            self.assertEqual(actual['dof_limits'], resolved_limits(scene['objects']['joint']['joint']['dof_limits']))
            self.assertEqual(actual['unregistered_limit_schemas'], [])
            validate_loaded(prim, scene['objects']['joint']['joint'])
            for axis in AXES[:3]:
                api = UsdPhysics.LimitAPI(prim, axis)
                self.assertGreater(api.GetLowAttr().Get(), api.GetHighAttr().Get())
            self.assertFalse(prim.HasAPI(UsdPhysics.LimitAPI, 'rotZ'))
            self.assertFalse(any('DriveAPI' in schema for schema in prim.GetAppliedSchemas()))
            self.assertFalse(any(a.GetName().startswith('drive:') for a in prim.GetAttributes()))
            self.assertTrue(UsdPhysics.Joint(prim).GetExcludeFromArticulationAttr().Get())

    def test_readback_keeps_unregistered_native_limit_instance_visible(self):
        from pxr import Usd, UsdPhysics
        stage = Usd.Stage.CreateInMemory()
        joint = UsdPhysics.Joint.Define(stage, '/joint')
        api = UsdPhysics.LimitAPI.Apply(joint.GetPrim(), 'distance')
        api.CreateHighAttr(1.)
        self.assertEqual(read_limits(joint.GetPrim())['unregistered_limit_schemas'], ['PhysicsLimitAPI:distance'])

    def test_relative_frames_with_rotated_world_and_coupled_swing_twist(self):
        from pxr import Gf, Usd
        from simscene.worker.joint_observation import sample
        scene = self.scene()
        cfg = scene['objects']['joint']['joint']
        q0 = Gf.Rotation(Gf.Vec3d(0, 0, 1), 90).GetQuat()
        swing = Gf.Rotation(Gf.Vec3d(0, 1, 0), 30).GetQuat()
        twist = Gf.Rotation(Gf.Vec3d(1, 0, 0), 20).GetQuat()
        q1 = q0*swing*twist
        cfg['local_rot0_wxyz'] = [q0.GetReal(), *q0.GetImaginary()]
        cfg['dof_limits']['transX'] = [-.3, .3]
        scene['objects']['link'].update(position=[0, .2, 0],
            orientation_wxyz=[q1.GetReal(), *q1.GetImaginary()])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.usda'
            export_scene(scene, path)
            stage = Usd.Stage.Open(str(path))
            result = sample(stage, scene['objects'])['joint']
        self.assertAlmostEqual(result['translation_in_frame0_m'][0], .2, places=6)
        self.assertAlmostEqual(result['translation_in_frame0_m'][1], 0, places=6)
        self.assertAlmostEqual(result['twist_x_degrees'], 20, places=4)
        self.assertAlmostEqual(result['swing_angle_degrees'], 30, places=4)
        self.assertAlmostEqual(result['frame_separation_m'], .2, places=6)
        self.assertLess(result['anchor_error_m'], 1e-6)
        self.assertFalse(result['drive_present'])

    def test_translation_error_uses_only_constraint_violation(self):
        limits = dict(zip(AXES, ['locked', [-.1, .2], 'free', 'free', 'free', 'free']))
        value = relative_observation([.003, .204, 2], [1, 0, 0, 0], limits)
        self.assertAlmostEqual(value['anchor_error_m'], .005)
        self.assertGreater(value['frame_separation_m'], 2)
        limits['transY'] = [-.1, .1]
        boundary = relative_observation([0, .1000000012, 0], [1, 0, 0, 0], limits)
        self.assertEqual(boundary['anchor_error_m'], 0)

    def test_singular_swing_reports_undefined_twist_and_keeps_quaternion(self):
        limits = {a: 'free' for a in AXES}
        value = relative_observation([0, 0, 0], [0, 0, -1, 0], limits)
        self.assertIsNone(value['twist_x_degrees'])
        self.assertEqual(value['swing_angle_degrees'], 180)
        self.assertEqual(value['relative_rotation_wxyz'], [0, 0, -1, 0])
        for q in ([0, 0, 0, 0], [float('inf'), 0, 0, 0], [1e308, 0, 0, 0]):
            with self.assertRaises(ValueError):
                relative_observation([0, 0, 0], q, limits)
        with self.assertRaises(ValueError):
            relative_observation([0, 0], [1, 0, 0, 0], limits)

    def test_observer_uses_loaded_frame_instead_of_stale_authored_configuration(self):
        from pxr import Gf, Usd, UsdPhysics
        from simscene.worker.joint_observation import sample
        scene = self.scene()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.usda';export_scene(scene, path)
            stage = Usd.Stage.Open(str(path));prim = stage.GetPrimAtPath('/World/joint')
            cfg = scene['objects']['joint']['joint']
            UsdPhysics.Joint(prim).GetLocalPos1Attr().Set(Gf.Vec3f(.01, 0, 0))
            observed = sample(stage, scene['objects'])['joint']
            self.assertAlmostEqual(observed['frame_separation_m'], .01, places=7)
            self.assertAlmostEqual(observed['anchor_error_m'], .01, places=7)
            with self.assertRaises(RuntimeError):validate_loaded(prim, cfg)
            UsdPhysics.Joint(prim).GetLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
            UsdPhysics.Joint(prim).GetJointEnabledAttr().Set(False)
            self.assertFalse(sample(stage, scene['objects'])['joint']['enabled'])
            with self.assertRaises(RuntimeError):validate_loaded(prim, cfg)

    def test_reject_changed_relations_sentinel_animation_soft_limits_and_drives(self):
        from pxr import Gf, Sdf, Usd, UsdPhysics
        mutations = [
            lambda p: UsdPhysics.Joint(p).GetBody1Rel().SetTargets(['/World/other']),
            lambda p: UsdPhysics.Joint(p).GetLocalRot1Attr().Set(Gf.Quatf(.99, Gf.Vec3f(.1, 0, 0))),
            lambda p: UsdPhysics.Joint(p).GetCollisionEnabledAttr().Set(True),
            lambda p: UsdPhysics.Joint(p).GetExcludeFromArticulationAttr().Set(False),
            lambda p: UsdPhysics.LimitAPI(p, 'transX').GetLowAttr().Set(2.),
            lambda p: UsdPhysics.LimitAPI(p, 'transX').GetLowAttr().Set(float('inf')),
            lambda p: UsdPhysics.LimitAPI(p, 'rotX').GetLowAttr().Set(-15., 1.),
            lambda p: UsdPhysics.Joint(p).GetLocalPos0Attr().Set(Gf.Vec3f(0), 1.),
            lambda p: p.AddAppliedSchema('PhysxLimitAPI:rotX'),
            lambda p: p.CreateAttribute('physxJoint:enableProjection', Sdf.ValueTypeNames.Bool).Set(True),
            lambda p: UsdPhysics.DriveAPI.Apply(p, 'rotX').CreateStiffnessAttr(1.),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation_index=index), tempfile.TemporaryDirectory() as directory:
                scene = self.scene();path = Path(directory)/'stage.usda';export_scene(scene, path)
                stage = Usd.Stage.Open(str(path));prim = stage.GetPrimAtPath('/World/joint')
                mutate(prim)
                with self.assertRaises(RuntimeError):validate_loaded(prim, scene['objects']['joint']['joint'])

    def test_nan_limit_is_reported_as_nan_and_never_as_infinity_or_a_valid_mode(self):
        from pxr import Usd, UsdPhysics
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene();path = Path(directory)/'stage.usda';export_scene(scene, path)
            stage = Usd.Stage.Open(str(path));prim = stage.GetPrimAtPath('/World/joint')
            UsdPhysics.LimitAPI(prim, 'rotX').GetLowAttr().Set(float('nan'))
            self.assertEqual(read_limits(prim)['dof_limit_attributes']['rotX']['low'], 'nan')
            with self.assertRaises(RuntimeError):validate_loaded(prim, scene['objects']['joint']['joint'])

    def test_same_sample_tensor_frames_take_precedence_without_changing_legacy_joint_reads(self):
        from pxr import Usd
        from simscene.worker.joint_observation import sample
        scene = self.scene()
        scene['objects']['joint']['joint']['dof_limits']['transX'] = [-1, 1]
        scene['objects']['link']['position'] = [.3, 0, 0]
        scene['objects']['legacy'] = {'kind': 'joint', 'joint': {
            'type': 'prismatic', 'body1': 'link', 'axis': 'X'}}
        native = {'positions': {'/World/link': [.05, 0, 0]},
                  'orientations_wxyz': {'/World/link': [1, 0, 0, 0]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.usda';export_scene(scene, path)
            stage = Usd.Stage.Open(str(path))
            measured = sample(stage, scene['objects'], native_state=native)
            self.assertEqual(measured['joint']['translation_in_frame0_m'], [.05, 0, 0])
            self.assertEqual(measured['joint']['pose_source'], 'same_sample_PhysX_rigid_body_tensors')
            self.assertAlmostEqual(measured['legacy']['position_m'], .3, places=6)
            fallback = sample(stage, scene['objects'])['joint']
            self.assertAlmostEqual(fallback['translation_in_frame0_m'][0], .3, places=6)
            self.assertEqual(fallback['pose_source'], 'loaded_USD_body_xforms')
            with self.assertRaises(RuntimeError):
                sample(stage, scene['objects'], native_state={'positions': {}, 'orientations_wxyz': {}})

    def test_each_tensor_endpoint_is_unit_even_when_two_bad_scales_would_cancel(self):
        from pxr import Usd
        from simscene.worker.joint_observation import sample
        scene = self.scene();scene['objects']['other'] = copy.deepcopy(scene['objects']['link'])
        scene['objects']['joint']['joint']['body0'] = 'other'
        valid = {'positions': {'/World/link': [0, 0, 0], '/World/other': [0, 0, 0]},
                 'orientations_wxyz': {'/World/link': [1, 0, 0, 0], '/World/other': [1, 0, 0, 0]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.usda';export_scene(scene, path);stage = Usd.Stage.Open(str(path))
            self.assertEqual(sample(stage, scene['objects'], native_state=valid)['joint']['anchor_error_m'], 0)
            bad = copy.deepcopy(valid)
            bad['orientations_wxyz'] = {p: [2, 0, 0, 0] for p in valid['positions']}
            with self.assertRaises(RuntimeError):sample(stage, scene['objects'], native_state=bad)
            for position in ([0, 0], [float('nan'), 0, 0], [1.7e308, 1.7e308, 1.7e308]):
                bad = copy.deepcopy(valid);bad['positions']['/World/link'] = position
                with self.assertRaises(RuntimeError):sample(stage, scene['objects'], native_state=bad)


if __name__ == '__main__':
    unittest.main()
