"""Passive scene settings evidence, without an Isaac process."""
import unittest
from simscene.worker.physics_readback import read_physics_settings, SCENE_PATH, TIMESTEP_ATTRIBUTE


class Attribute:
    def __init__(self, value, authored=True):
        self.value = value; self.authored = authored
    def Get(self):
        return self.value
    def HasAuthoredValueOpinion(self):
        return self.authored
    def Set(self, value):
        raise AssertionError('readback must never mutate physics')


class Stage:
    def __init__(self, attributes):
        self.attributes = attributes
    def GetPrimAtPath(self, path):
        assert path == SCENE_PATH
        return self
    def GetAttribute(self, name):
        return self.attributes.get(name)


class PhysicsReadbackTests(unittest.TestCase):
    def stage(self, gpu=False, timestep=None):
        attributes = {'physxScene:enableGPUDynamics': Attribute(gpu),
                      'physxScene:broadphaseType': Attribute('GPU' if gpu else 'MBP'),
                      'physics:gravityDirection': Attribute([0, 0, -1]),
                      'physics:gravityMagnitude': Attribute(9.81)}
        if timestep is not None:
            attributes[TIMESTEP_ATTRIBUTE] = timestep
        return Stage(attributes)

    def test_explicit_cpu_readback_and_no_invented_timestep(self):
        stage = self.stage(timestep=Attribute(60, authored=False))
        observed = read_physics_settings(stage, 'cpu')
        self.assertIs(observed['enable_gpu_dynamics'], False)
        self.assertEqual(observed['broadphase_type'], 'MBP')
        self.assertEqual(observed['gravity_direction'], [0., 0., -1.])
        self.assertEqual(observed['gravity_magnitude_m_s2'], 9.81)
        self.assertIsNone(observed['authored_time_steps_per_second'])
        self.assertIsNone(observed['timestep_attribute'])
        self.assertTrue(observed['request_matches_observation'])
        self.assertEqual(stage.attributes[TIMESTEP_ATTRIBUTE].Get(), 60)

    def test_gpu_and_authored_timestep_are_actual_values(self):
        observed = read_physics_settings(self.stage(True, Attribute(120)), 'gpu')
        self.assertIs(observed['enable_gpu_dynamics'], True)
        self.assertEqual(observed['authored_time_steps_per_second'], 120)
        self.assertEqual(observed['timestep_attribute'], TIMESTEP_ATTRIBUTE)
        self.assertEqual(observed['broadphase_type'], 'GPU')

    def test_explicit_device_mismatch_or_unknown_fails_with_observation(self):
        for requested, stage in [('cpu', self.stage(True)), ('gpu', self.stage(False)),
                                 ('cpu', Stage({})), ('gpu', Stage({'physxScene:enableGPUDynamics': Attribute(1)}))]:
            with self.subTest(requested=requested), self.assertRaises(ValueError) as caught:
                read_physics_settings(stage, requested)
            self.assertFalse(caught.exception.physics_settings['request_matches_observation'])
        with self.assertRaises(ValueError):
            read_physics_settings(self.stage(), 'automatic')

    def test_default_missing_values_stay_unknown_and_snapshots_do_not_alias(self):
        observed = read_physics_settings(Stage({}), 'default')
        for key in ('enable_gpu_dynamics', 'broadphase_type', 'gravity_direction',
                    'gravity_magnitude_m_s2', 'authored_time_steps_per_second', 'request_matches_observation'):
            self.assertIsNone(observed[key], key)
        stage = self.stage(); first = read_physics_settings(stage, 'cpu')
        stage.attributes['physics:gravityDirection'].value[2] = -2
        second = read_physics_settings(stage, 'cpu')
        self.assertEqual(first['gravity_direction'], [0., 0., -1.])
        self.assertEqual(second['gravity_direction'], [0., 0., -2.])

    def test_actual_cpu_usd_attributes_without_physx_schema(self):
        try:
            from pxr import Usd, UsdPhysics, Sdf
        except ImportError:
            self.skipTest('OpenUSD is optional on the CPU host')
        stage = Usd.Stage.CreateInMemory()
        scene = UsdPhysics.Scene.Define(stage, SCENE_PATH)
        scene.CreateGravityDirectionAttr((0, 0, -1)); scene.CreateGravityMagnitudeAttr(9.81)
        prim = scene.GetPrim()
        prim.CreateAttribute('physxScene:enableGPUDynamics', Sdf.ValueTypeNames.Bool).Set(False)
        prim.CreateAttribute('physxScene:broadphaseType', Sdf.ValueTypeNames.Token).Set('MBP')
        timestep = prim.CreateAttribute(TIMESTEP_ATTRIBUTE, Sdf.ValueTypeNames.UInt)
        self.assertIsNone(read_physics_settings(stage, 'cpu')['authored_time_steps_per_second'])
        timestep.Set(90)
        before = stage.GetRootLayer().ExportToString()
        observed = read_physics_settings(stage, 'cpu')
        self.assertEqual(observed['authored_time_steps_per_second'], 90)
        self.assertEqual(before, stage.GetRootLayer().ExportToString())


if __name__ == '__main__':
    unittest.main()
