import copy
import importlib.util
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


BASE = '/World/cabinet/Asset/Native/Links/base'
FIRST = '/World/cabinet/Asset/Native/Links/first'
SECOND = '/World/cabinet/Asset/Native/Links/second'
JOINT_A = '/World/cabinet/Asset/Native/Joints/a'
JOINT_B = '/World/cabinet/Asset/Native/Joints/b'
ROOT_TYPE = 'engine-articulation-root-link'


def joint(path, child, axis):
    return {'joint_path': path, 'parent_body': BASE, 'child_body': child,
            'type': 'prismatic', 'axis': axis, 'position_unit': 'm',
            'limits': [-1., 1.], 'local_pos0_m': [0., 0., 0.],
            'local_pos1_m': [0., 0., 0.], 'local_rot0_wxyz': [1., 0., 0., 0.],
            'local_rot1_wxyz': [1., 0., 0., 0.], 'passive': True, 'drive': None}


def binding():
    return {'profile_id': 'articulated_prop_v2', 'root_body': BASE, 'motion_bodies': [BASE, FIRST, SECOND],
            'articulation_roots': [BASE],
            'joints': {'alpha': joint(JOINT_A, FIRST, 'X'), 'beta': joint(JOINT_B, SECOND, 'Y')}}


def authored():
    return {'bodies': {
        BASE: {'position': [1., 2., 3.], 'orientation_wxyz': [1., 0., 0., 0.]},
        FIRST: {'position': [1.2, 2., 3.], 'orientation_wxyz': [1., 0., 0., 0.]},
        SECOND: {'position': [1., 2.3, 3.], 'orientation_wxyz': [1., 0., 0., 0.]},
    }}


class FakeArticulationView:
    def __init__(self):
        self.count = 1
        self.max_dofs = 2
        self.dof_count = 2
        self.link_count = 3
        # The tensor orders deliberately disagree with the frozen dictionary.
        self.dof_paths = [[JOINT_B, JOINT_A]]
        self.link_paths = [[FIRST, BASE, SECOND]]
        self.q = np.array([[.375, .125]], dtype=np.float32)
        self.v = np.array([[.02, -.01]], dtype=np.float32)
        self.root = np.array([[1., 2., 3., 0., 0., 0., 1.]], dtype=np.float32)
        self.root_v = np.zeros((1, 6), dtype=np.float32)
        self.link_velocities = np.zeros((1, 3, 6), dtype=np.float32)
        self.transforms = None
        self.calls = []
        self.ignore_dof_set = False
        self.ignore_root_velocity_set = False
        self.angular_B = False
        self.chain_B = False
        self.update()

    def get_metatype(self, index):
        assert index == 0
        return SimpleNamespace(dof_count=self.dof_count, link_count=self.link_count)

    def get_dof_positions(self): return self.q
    def get_dof_velocities(self): return self.v
    def get_link_transforms(self): return self.transforms
    def get_link_velocities(self): return self.link_velocities
    def get_root_transforms(self): return self.root
    def get_root_velocities(self): return self.root_v
    def get_masses(self): return np.array([[2., 10., 3.]], dtype=np.float32)
    def get_coms(self): return np.tile([0., 0., 0., 0., 0., 0., 1.], (1, 3, 1))
    def get_inertias(self): return np.tile(np.eye(3).reshape(9), (1, 3, 1))

    def set_root_transforms(self, values, indices):
        self.calls.append(('root_transform', values.copy(), indices.copy()))
        self.root = values.copy()

    def set_root_velocities(self, values, indices):
        self.calls.append(('root_velocity', values.copy(), indices.copy()))
        if not self.ignore_root_velocity_set:
            self.root_v = values.copy()

    def set_dof_positions(self, values, indices):
        self.calls.append(('dof_position', values.copy(), indices.copy()))
        if not self.ignore_dof_set:
            self.q = values.copy()

    def set_dof_velocities(self, values, indices):
        self.calls.append(('dof_velocity', values.copy(), indices.copy()))
        self.v = values.copy()

    def update(self):
        p = self.root[0, :3]
        values = {path: float(self.q[0, i]) for i, path in enumerate(self.dof_paths[0])}
        first = [p[0] + values.get(JOINT_A, 0.), p[1], p[2]]
        second_parent = first if self.chain_B else p
        if self.angular_B:
            angle = values.get(JOINT_B, 0.)
            second = [*second_parent, 0., 0., math.sin(angle / 2), math.cos(angle / 2)]
        else:
            second = [second_parent[0], second_parent[1] + values.get(JOINT_B, 0.),
                      second_parent[2], 0., 0., 0., 1.]
        by_link = {BASE: [*p, 0., 0., 0., 1.],
                   FIRST: [*first, 0., 0., 0., 1.], SECOND: second}
        self.transforms = np.asarray([[by_link.get(path, [0., 0., 0., 0., 0., 0., 1.])
                                       for path in self.link_paths[0]]], dtype=np.float32)
        self.link_velocities = np.zeros((1, len(self.link_paths[0]), 6), dtype=np.float32)


class FakeSimulationView:
    def __init__(self, view):
        self.view = view
        self.roots = {BASE}
        self.updates = 0

    def get_object_type(self, path):
        return ROOT_TYPE if path in self.roots else 'engine-articulation-link'

    def update_articulations_kinematic(self):
        self.updates += 1
        self.view.update()


V1_BASE = '/World/single/Asset/Native/Base'
V1_CHILD = '/World/single/Asset/Native/Door'
V1_JOINT = '/World/single/Asset/Native/Slide'
RIGID = '/World/ball'


def single_binding():
    entry = joint(V1_JOINT, V1_CHILD, 'X')
    entry['parent_body'] = V1_BASE
    return {'profile_id': 'articulated_prop_v1', 'motion_bodies': [V1_BASE, V1_CHILD],
            'articulation_roots': [V1_BASE], 'joints': {'main': entry}}


def all_authored():
    result = authored()
    result['phase'] = 'before_sdk_warmup'
    for body in result['bodies'].values(): body['local_ops'] = {}
    for path, p in ((V1_BASE, [4., 0., 0.]), (V1_CHILD, [4.4, 0., 0.]), (RIGID, [7., 0., 0.])):
        result['bodies'][path] = {'position': p, 'orientation_wxyz': [1., 0., 0., 0.], 'local_ops': {}}
    return result


class FakeSingleView:
    def __init__(self):
        self.count = 1
        self.max_dofs = 1
        self.link_paths = [[V1_BASE, V1_CHILD]]
        self.dof_paths = [[V1_JOINT]]
        self.root = np.array([[4., 0., 0., 0., 0., 0., 1.]], dtype=np.float32)
        self.q = np.array([[.4]], dtype=np.float32)
        self.v = np.zeros((1, 1), dtype=np.float32)
        self.calls = []
        self.update()

    def update(self):
        x = float(self.root[0, 0]); q = float(self.q[0, 0])
        self.transforms = np.array([[[x, 0., 0., 0., 0., 0., 1.], [x+q, 0., 0., 0., 0., 0., 1.]]], dtype=np.float32)
        self.velocities = np.zeros((1, 2, 6), dtype=np.float32)

    def get_link_transforms(self): return self.transforms
    def get_link_velocities(self): return self.velocities
    def get_dof_positions(self): return self.q
    def get_dof_velocities(self): return self.v
    def get_masses(self): return np.array([[10., 4.]], dtype=np.float32)
    def get_coms(self): return np.tile([0., 0., 0., 0., 0., 0., 1.], (1, 2, 1))
    def get_inertias(self): return np.tile(np.eye(3).reshape(9), (1, 2, 1))
    def set_root_transforms(self, data, indices): self.calls.append('root'); self.root = data.copy()
    def set_root_velocities(self, data, indices): self.calls.append('root_v')
    def set_dof_positions(self, data, indices): self.calls.append('q'); self.q = data.copy()
    def set_dof_velocities(self, data, indices): self.calls.append('v'); self.v = data.copy()


class FakeRigidView:
    def __init__(self, paths):
        self.prim_paths = list(reversed(paths))
        self.transforms = np.array([[7., 0., 0., 0., 0., 0., 1.] for _ in paths], dtype=np.float32)
        self.velocities = np.zeros((len(paths), 6), dtype=np.float32)
        self.calls = []
    def get_transforms(self): return self.transforms
    def get_velocities(self): return self.velocities
    def get_masses(self): return np.full(len(self.prim_paths), 5., dtype=np.float32)
    def get_coms(self): return np.tile([0., 0., 0., 0., 0., 0., 1.], (len(self.prim_paths), 1))
    def get_inertias(self): return np.tile(np.eye(3).reshape(9), (len(self.prim_paths), 1))
    def set_transforms(self, data, indices): self.calls.append('transforms'); self.transforms = data.copy()
    def set_velocities(self, data, indices): self.calls.append('velocities'); self.velocities = data.copy()


class FakeMixedSimulation(FakeSimulationView):
    def __init__(self):
        super().__init__(FakeArticulationView())
        self.single = FakeSingleView()
        self.rigid = None

    def create_articulation_view(self, root):
        if root == BASE: return self.view
        if root == V1_BASE: return self.single
        raise AssertionError('unexpected articulation root: ' + root)

    def create_rigid_body_view(self, paths):
        self.rigid = FakeRigidView(paths)
        return self.rigid

    def update_articulations_kinematic(self):
        self.updates += 1
        self.view.update()
        self.single.update()


class FakePrim:
    def GetAttributes(self): return []


class FakeStage:
    def GetPrimAtPath(self, path): return FakePrim()
    def GetLayerStack(self): return []


class TwoDofTensorTests(unittest.TestCase):
    def adapter(self, view=None, frozen=None, simulation=None):
        spec = importlib.util.find_spec('simscene.worker.mechanism_v2')
        self.assertIsNotNone(spec, 'two-DOF tensor adapter is not implemented')
        from simscene.worker.mechanism_v2 import TwoDofTensorState
        view = view or FakeArticulationView()
        simulation = simulation or FakeSimulationView(view)
        return TwoDofTensorState(view, frozen or binding(), simulation_view=simulation, root_link_type=ROOT_TYPE)

    def test_read_uses_tensor_dof_order_and_explicit_link_paths(self):
        state = self.adapter().read()
        self.assertAlmostEqual(state['native_joint_positions'][JOINT_A], .125)
        self.assertAlmostEqual(state['native_joint_positions'][JOINT_B], .375)
        self.assertAlmostEqual(state['native_joint_velocities'][JOINT_A], -.01, places=6)
        self.assertAlmostEqual(state['native_joint_velocities'][JOINT_B], .02, places=6)
        self.assertEqual(state['positions'][BASE], [1., 2., 3.])
        self.assertEqual(state['orientations_wxyz'][BASE], [1., 0., 0., 0.])
        self.assertEqual(state['native_joint_measurement_source'], 'PhysX_articulation_tensor_DOF_readback_SI')

    def test_rejects_bad_actual_dof_count_duplicate_missing_or_extra_paths(self):
        for mutation in ('view_count', 'max_dofs', 'actual_dofs', 'missing', 'extra', 'duplicate', 'wrong_path'):
            with self.subTest(mutation=mutation):
                view = FakeArticulationView()
                if mutation == 'view_count': view.count = 2
                elif mutation == 'max_dofs': view.max_dofs = 3
                elif mutation == 'actual_dofs': view.dof_count = 1
                elif mutation == 'missing': view.dof_paths = [[JOINT_A]]
                elif mutation == 'extra': view.dof_paths = [[JOINT_A, JOINT_B, '/World/other']]
                elif mutation == 'duplicate': view.dof_paths = [[JOINT_A, JOINT_A]]
                else: view.dof_paths = [[JOINT_A, '/World/other']]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.adapter(view)

    def test_rejects_invalid_frozen_joint_and_body_graph(self):
        for mutation in ('duplicate_joint_path', 'bad_type', 'same_child', 'bad_parent', 'bad_root', 'duplicate_link'):
            with self.subTest(mutation=mutation):
                frozen = binding()
                if mutation == 'duplicate_joint_path': frozen['joints']['beta']['joint_path'] = JOINT_A
                elif mutation == 'bad_type': frozen['joints']['beta']['type'] = 'spherical'
                elif mutation == 'same_child': frozen['joints']['beta']['child_body'] = FIRST
                elif mutation == 'bad_parent': frozen['joints']['beta']['parent_body'] = '/World/elsewhere'
                elif mutation == 'bad_root': frozen['root_body'] = FIRST
                else: frozen['motion_bodies'] = [BASE, FIRST, FIRST]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.adapter(frozen=frozen)

    def test_actual_root_is_not_inferred_from_first_link_or_static_binding(self):
        view = FakeArticulationView()
        sim = FakeSimulationView(view)
        self.adapter(view, simulation=sim)  # root is link_paths[0][1], not [0]
        for roots in ({FIRST}, set(), {BASE, SECOND}):
            with self.subTest(roots=roots):
                sim.roots = roots
                with self.assertRaises((ValueError, RuntimeError)):
                    self.adapter(view, simulation=sim)

    def test_rejects_wrong_or_duplicate_tensor_link_paths(self):
        for paths in ([FIRST, BASE], [FIRST, BASE, SECOND, '/World/extra'],
                      [FIRST, BASE, FIRST], [FIRST, BASE, '/World/elsewhere']):
            with self.subTest(paths=paths):
                view = FakeArticulationView()
                view.link_paths = [paths]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.adapter(view)

    def test_rejects_nonfinite_wrong_shape_and_nonunit_quaternion_readbacks(self):
        for mutation in ('q_shape', 'v_shape', 'q_nan', 'v_inf', 'links_shape', 'links_nan',
                         'velocities_shape', 'root_shape', 'root_nan', 'quaternion'):
            with self.subTest(mutation=mutation):
                view = FakeArticulationView()
                adapter = self.adapter(view)
                if mutation == 'q_shape': view.q = np.zeros((2,))
                elif mutation == 'v_shape': view.v = np.zeros((1, 3))
                elif mutation == 'q_nan': view.q[0, 0] = np.nan
                elif mutation == 'v_inf': view.v[0, 1] = np.inf
                elif mutation == 'links_shape': view.transforms = np.zeros((3, 7))
                elif mutation == 'links_nan': view.transforms[0, 0, 0] = np.nan
                elif mutation == 'velocities_shape': view.link_velocities = np.zeros((1, 2, 6))
                elif mutation == 'root_shape': view.root = np.zeros((7,))
                elif mutation == 'root_nan': view.root[0, 0] = np.nan
                else: view.transforms[0, 0, 6] = 2.
                with self.assertRaises((ValueError, RuntimeError)):
                    adapter.read()

    def test_sleeping_root_getter_can_be_stale_and_both_raw_velocities_are_preserved(self):
        view = FakeArticulationView()
        # Observed Isaac 6.2 sleeping-root behavior: link state is zero while
        # the independent root getter retains its last nonzero six-vector.
        view.root_v[0] = [9.8421653e-5, -8.3967261e-6, .002321278,
                          -1.6199634e-5, .0001086288, -.00020209]
        try:
            result = self.adapter(view).read()
        except RuntimeError as error:
            self.fail('stale root getter should remain recorded, not abort sampling: ' + str(error))
        raw = result['native_root_velocities'][BASE]
        self.assertAlmostEqual(raw['linear_velocity_m_s'][2], .002321278, places=8)
        self.assertEqual(result['linear_velocities_m_s'][BASE], [0., 0., 0.])
        self.assertIn('stale', raw['scope'])

    def test_rejects_changed_tensor_order_after_binding(self):
        view = FakeArticulationView()
        adapter = self.adapter(view)
        view.dof_paths = [[JOINT_A, JOINT_B]]
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.read()

    def test_reset_uses_frozen_frames_but_writes_tensor_order_and_reads_back_once(self):
        view = FakeArticulationView()
        sim = FakeSimulationView(view)
        adapter = self.adapter(view, simulation=sim)
        state = authored()
        before = copy.deepcopy(state)
        result = adapter.reset_before_task(state, is_paused=lambda: True)
        self.assertEqual(state, before)
        self.assertEqual(sim.updates, 1)
        writes = {name: values for name, values, indices in view.calls}
        np.testing.assert_allclose(writes['root_transform'], [[1., 2., 3., 0., 0., 0., 1.]])
        np.testing.assert_allclose(writes['dof_position'], [[.3, .2]], atol=1e-6)
        np.testing.assert_allclose(writes['root_velocity'], np.zeros((1, 6)))
        np.testing.assert_allclose(writes['dof_velocity'], np.zeros((1, 2)))
        self.assertAlmostEqual(result['native_joint_positions'][JOINT_A], .2, places=6)
        self.assertAlmostEqual(result['native_joint_positions'][JOINT_B], .3, places=6)
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.reset_before_task(state, is_paused=lambda: True)
        self.assertEqual(len(view.calls), 4)

    def test_reset_requires_paused_pre_task_state_and_cannot_repeat_after_task_start(self):
        view = FakeArticulationView()
        adapter = self.adapter(view)
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.reset_before_task(authored(), is_paused=lambda: False)
        self.assertEqual(view.calls, [])
        adapter.mark_task_started()
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.reset_before_task(authored(), is_paused=lambda: True)
        self.assertEqual(view.calls, [])

    def test_failed_reset_readback_cannot_be_retried_after_partial_write(self):
        view = FakeArticulationView()
        view.ignore_dof_set = True
        adapter = self.adapter(view)
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.reset_before_task(authored(), is_paused=lambda: True)
        calls = len(view.calls)
        self.assertGreater(calls, 0)
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.reset_before_task(authored(), is_paused=lambda: True)
        self.assertEqual(len(view.calls), calls)

    def test_reset_rejects_nonzero_root_velocity_even_if_link_velocity_is_zero(self):
        for speed in (.25, .000001):
            with self.subTest(speed=speed):
                view = FakeArticulationView()
                view.root_v[0, 0] = speed
                view.ignore_root_velocity_set = True
                adapter = self.adapter(view)
                with self.assertRaises((ValueError, RuntimeError)):
                    adapter.reset_before_task(authored(), is_paused=lambda: True)

    def test_mixed_serial_slider_and_hinge_reset_in_tensor_order(self):
        view = FakeArticulationView()
        view.angular_B = True
        view.chain_B = True
        view.update()
        frozen = binding()
        frozen['joints']['beta'].update(parent_body=FIRST, type='revolute', axis='Z', position_unit='rad')
        pose = authored()
        pose['bodies'][SECOND]['position'] = [1.2, 2., 3.]
        pose['bodies'][SECOND]['orientation_wxyz'] = [math.cos(.15), 0., 0., math.sin(.15)]
        state = self.adapter(view, frozen=frozen).reset_before_task(pose, is_paused=lambda: True)
        self.assertAlmostEqual(state['native_joint_positions'][JOINT_A], .2, places=6)
        self.assertAlmostEqual(state['native_joint_positions'][JOINT_B], .3, places=6)

    def test_revolute_initialization_finds_unique_representative_across_many_turns(self):
        for limits, angle in (([10., 11.], 10.5), ([-15., -14.], -14.5)):
            with self.subTest(limits=limits):
                view = FakeArticulationView(); view.angular_B = True; view.update()
                frozen = binding()
                frozen['joints']['beta'].update(type='revolute', axis='Z', position_unit='rad', limits=limits)
                pose = authored(); pose['bodies'][SECOND]['position'] = [1., 2., 3.]
                pose['bodies'][SECOND]['orientation_wxyz'] = [math.cos(angle / 2), 0., 0., math.sin(angle / 2)]
                try:
                    state = self.adapter(view, frozen=frozen).reset_before_task(pose, is_paused=lambda: True)
                except ValueError as error:
                    self.fail('valid multi-turn initial angle was rejected: ' + str(error))
                self.assertAlmostEqual(state['native_joint_positions'][JOINT_B], angle, places=5)

    def test_revolute_unwraps_across_pi_and_rejects_an_initial_pose_with_no_solution(self):
        from simscene.worker.mechanism import measure_joint
        item = joint(JOINT_B, SECOND, 'Z')
        item.update(type='revolute', position_unit='rad', limits=[9.3, 9.8])
        def state(angle):
            return {'positions': {BASE: [0., 0., 0.], SECOND: [0., 0., 0.]},
                    'orientations_wxyz': {BASE: [1., 0., 0., 0.],
                                          SECOND: [math.cos(angle/2), 0., 0., math.sin(angle/2)]}}
        first = measure_joint(item, state(9.4), physics_step=0, physics_dt_s=.1)
        second = measure_joint(item, state(9.5), first, physics_step=1, physics_dt_s=.1)
        self.assertAlmostEqual(first['position'], 9.4)
        self.assertAlmostEqual(second['position'], 9.5)
        self.assertAlmostEqual(second['velocity'], 1.)
        item['limits'] = [10., 11.]
        view = FakeArticulationView(); view.angular_B = True; view.update()
        graph = binding(); graph['joints']['beta'].update(item)
        pose = authored(); pose['bodies'][SECOND]['position'] = [1., 2., 3.]
        pose['bodies'][SECOND]['orientation_wxyz'] = [math.cos(8./2), 0., 0., math.sin(8./2)]
        with self.assertRaises(ValueError):
            self.adapter(view, frozen=graph).reset_before_task(pose, is_paused=lambda: True)
        self.assertEqual(view.calls, [])

    def test_exact_unique_angle_near_single_turn_boundary_is_not_made_ambiguous_by_tolerance(self):
        angle = math.pi - 2e-5
        view = FakeArticulationView(); view.angular_B = True; view.update()
        graph = binding()
        graph['joints']['beta'].update(type='revolute', axis='Z', position_unit='rad',
                                       limits=[-math.pi + 1e-5, math.pi - 1e-5])
        pose = authored(); pose['bodies'][SECOND]['position'] = [1., 2., 3.]
        pose['bodies'][SECOND]['orientation_wxyz'] = [math.cos(angle/2), 0., 0., math.sin(angle/2)]
        try:
            result = self.adapter(view, frozen=graph).reset_before_task(pose, is_paused=lambda: True)
        except ValueError as error:
            self.fail('one exactly admissible angle should not be ambiguous: ' + str(error))
        self.assertAlmostEqual(result['native_joint_positions'][JOINT_B], angle, places=5)

    def test_tolerance_cannot_choose_between_two_near_limit_angle_representatives(self):
        view = FakeArticulationView(); view.angular_B = True; view.update()
        graph = binding()
        graph['joints']['beta'].update(type='revolute', axis='Z', position_unit='rad',
                                       limits=[-math.pi + 1e-5, math.pi - 1e-5])
        pose = authored(); pose['bodies'][SECOND]['position'] = [1., 2., 3.]
        pose['bodies'][SECOND]['orientation_wxyz'] = [0., 0., 0., 1.]
        with self.assertRaisesRegex(ValueError, 'unique initial angle'):
            self.adapter(view, frozen=graph).reset_before_task(pose, is_paused=lambda: True)
        self.assertEqual(view.calls, [])

    def test_locked_rotation_error_reports_slider_rotation_and_hinge_swing_in_radians(self):
        from simscene.worker.mechanism import measure_joint
        item = joint(JOINT_B, SECOND, 'Z')
        frames = {'positions': {BASE: [0., 0., 0.], SECOND: [0., 0., 0.]},
                  'orientations_wxyz': {BASE: [1., 0., 0., 0.], SECOND: [math.sqrt(.5), math.sqrt(.5), 0., 0.]}}
        slider = measure_joint(item, frames, physics_step=0, physics_dt_s=.1)
        self.assertAlmostEqual(slider.get('locked_rotation_error_rad', -1.), math.pi/2)
        item.update(type='revolute', axis='Z', position_unit='rad', limits=[-2., 2.])
        frames['orientations_wxyz'][SECOND] = [math.cos(.6), 0., 0., math.sin(.6)]
        hinge = measure_joint(item, frames, physics_step=0, physics_dt_s=.1)
        self.assertAlmostEqual(hinge.get('locked_rotation_error_rad', -1.), 0.)
        # q = swing_x(0.4) * twist_z(1.2), independently expanded.
        c, s, ct, st = math.cos(.2), math.sin(.2), math.cos(.6), math.sin(.6)
        frames['orientations_wxyz'][SECOND] = [c*ct, s*ct, -s*st, c*st]
        hinge = measure_joint(item, frames, physics_step=0, physics_dt_s=.1)
        self.assertAlmostEqual(hinge.get('locked_rotation_error_rad', -1.), .4)
        frames['orientations_wxyz'][SECOND] = [-v for v in frames['orientations_wxyz'][SECOND]]
        antipodal = measure_joint(item, frames, physics_step=0, physics_dt_s=.1)
        self.assertAlmostEqual(antipodal.get('locked_rotation_error_rad', -1.), .4)

    def test_reset_rejects_slider_rotation_and_hinge_swing_before_any_write(self):
        for kind in ('slider', 'hinge'):
            with self.subTest(kind=kind):
                view = FakeArticulationView(); frozen = binding(); pose = authored()
                path = FIRST if kind == 'slider' else SECOND
                if kind == 'hinge':
                    frozen['joints']['beta'].update(type='revolute', axis='Z', position_unit='rad')
                    pose['bodies'][SECOND]['position'] = [1., 2., 3.]
                pose['bodies'][path]['orientation_wxyz'] = [math.sqrt(.5), math.sqrt(.5), 0., 0.]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.adapter(view, frozen=frozen).reset_before_task(pose, is_paused=lambda: True)
                self.assertEqual(view.calls, [])


class RuntimeIntegrationTests(unittest.TestCase):
    @staticmethod
    def command(joint_id, target, step=0):
        return {'joint_id': joint_id, 'trigger': {'type': 'at_step', 'physics_step': step},
                'target_position': target, 'position_unit': 'm',
                'stiffness': 20., 'damping': 3., 'max_effort': 50.}

    def mixed_state(self, *, paused=lambda: True, sim=None, bindings=None, root_type=ROOT_TYPE):
        from simscene.worker.mechanism import PreparedArticulationState
        sim = sim or FakeMixedSimulation()
        if bindings is None: bindings = {'double': binding(), 'single': single_binding()}
        try:
            state = PreparedArticulationState(FakeStage(), {}, bindings, all_authored(),
                                              simulation_view=sim, root_link_type=root_type, is_paused=paused)
        except TypeError as error:
            self.fail('prepared state cannot accept an injected tensor view: ' + str(error))
        return state, sim

    def test_v2_allows_two_commands_and_records_their_exact_joint_paths(self):
        from simscene.worker.mechanism import MechanismController, validate_binding
        class Backend:
            def __init__(self): self.calls = []
            def apply_drive(self, selected, command):
                self.calls.append((selected['joint_path'], command['target_position']))
                return {'target_position': command['target_position']}
            def observe(self, selected, step, native_state=None):
                return {name: {'physics_step': step, 'joint_path': item['joint_path']}
                        for name, item in selected['joints'].items()}
        graph = binding()
        try:
            validate_binding(graph)
            backend = Backend()
            control = MechanismController(graph, {'commands': [self.command('beta', .3), self.command('alpha', .2)]}, backend=backend)
        except ValueError as error:
            self.fail('explicit v2 binding was rejected: ' + str(error))
        events = control.step(0)
        self.assertEqual(backend.calls, [(JOINT_B, .3), (JOINT_A, .2)])
        self.assertEqual([(e['joint_id'], e.get('joint_path')) for e in events], [('beta', JOINT_B), ('alpha', JOINT_A)])
        self.assertEqual(set(control.observe(0)['joints']), {'alpha', 'beta'})
        single = MechanismController(single_binding(), {'commands': [self.command('main', .1)]}, backend=Backend())
        self.assertNotIn('joint_path', single.step(0)[0])

    def test_only_explicit_v2_can_accept_two_joints(self):
        from simscene.worker.mechanism import validate_binding
        for profile in ('articulated_prop_v1', 'unknown', None):
            graph = binding()
            if profile is None: graph.pop('profile_id')
            else: graph['profile_id'] = profile
            with self.subTest(profile=profile), self.assertRaises(ValueError): validate_binding(graph)

    def test_v2_observation_requires_actual_native_q_and_v_for_both_joints(self):
        from simscene.worker.mechanism import UsdMechanismBackend
        graph = binding()
        actual = self.adapter_state_for_observation()
        backend = UsdMechanismBackend(None, None)
        result = backend.observe(graph, 0, native_state=actual)
        self.assertEqual(set(result), {'alpha', 'beta'})
        self.assertAlmostEqual(result['alpha']['native_position'], .125)
        broken = copy.deepcopy(actual)
        broken['native_joint_velocities'].pop(JOINT_B)
        try:
            UsdMechanismBackend(None, None).observe(graph, 0, native_state=broken)
        except (ValueError, RuntimeError):
            pass
        except Exception as error:
            self.fail('missing native readback raised the wrong error: ' + repr(error))
        else:
            self.fail('missing native joint velocity was accepted')

    @staticmethod
    def adapter_state_for_observation():
        from simscene.worker.mechanism_v2 import TwoDofTensorState
        view = FakeArticulationView(); sim = FakeSimulationView(view)
        return TwoDofTensorState(view, binding(), simulation_view=sim, root_link_type=ROOT_TYPE).read()

    def test_mixed_v1_v2_and_rigid_state_resets_once_then_reads_by_path(self):
        state, sim = self.mixed_state()
        initial = state.reset_before_task()
        observed = state.read()
        self.assertEqual(set(observed['positions']), {BASE, FIRST, SECOND, V1_BASE, V1_CHILD, RIGID})
        self.assertEqual(set(observed['native_joint_positions']), {JOINT_A, JOINT_B, V1_JOINT})
        self.assertAlmostEqual(observed['native_joint_positions'][JOINT_A], .2, places=6)
        self.assertAlmostEqual(observed['native_joint_positions'][JOINT_B], .3, places=6)
        self.assertAlmostEqual(observed['native_joint_positions'][V1_JOINT], .4, places=6)
        masses = state.mass_properties(0)
        self.assertEqual({p: masses[p]['mass_kg'] for p in (BASE, FIRST, SECOND, V1_BASE, V1_CHILD, RIGID)},
                         {BASE: 10., FIRST: 2., SECOND: 3., V1_BASE: 10., V1_CHILD: 4., RIGID: 5.})
        self.assertEqual(initial['reset_count'], 1)
        calls = (len(sim.view.calls), len(sim.single.calls), len(sim.rigid.calls))
        state.mark_task_started()
        state.read()
        with self.assertRaises(RuntimeError): state.reset_before_task()
        self.assertEqual((len(sim.view.calls), len(sim.single.calls), len(sim.rigid.calls)), calls)

    def test_mixed_reset_fails_before_any_write_unless_actually_paused(self):
        state, sim = self.mixed_state(paused=lambda: False)
        with self.assertRaises(RuntimeError): state.reset_before_task()
        self.assertEqual(sim.view.calls, [])
        self.assertEqual(sim.single.calls, [])
        self.assertEqual(sim.rigid.calls, [])

    def test_mixed_graph_rejects_duplicate_dof_and_link_paths(self):
        for mutation in ('joint', 'link'):
            sim = FakeMixedSimulation()
            second = single_binding()
            if mutation == 'joint':
                second['joints']['main']['joint_path'] = JOINT_A
                sim.single.dof_paths = [[JOINT_A]]
            else:
                second['motion_bodies'] = [BASE, V1_CHILD]
                second['joints']['main']['parent_body'] = BASE
                sim.single.link_paths = [[BASE, V1_CHILD]]
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, RuntimeError)):
                self.mixed_state(sim=sim, bindings={'double': binding(), 'single': second})

    def test_mixed_read_rejects_wrong_v1_or_rigid_tensor_shapes(self):
        for mutation in ('v1_extra_q', 'v1_missing_link', 'rigid_extra_body'):
            with self.subTest(mutation=mutation):
                state, sim = self.mixed_state()
                if mutation == 'v1_extra_q': sim.single.q = np.zeros((1, 2))
                elif mutation == 'v1_missing_link': sim.single.transforms = np.zeros((1, 1, 7))
                else: sim.rigid.transforms = np.zeros((2, 7))
                try:
                    state.read()
                except (ValueError, RuntimeError):
                    pass
                except Exception as error:
                    self.fail('invalid mixed tensor raised the wrong error: ' + repr(error))
                else:
                    self.fail('invalid mixed tensor shape was accepted')

    def test_mixed_runtime_retains_root_getter_separately_from_link_velocity(self):
        state, sim = self.mixed_state()
        state.reset_before_task(); state.mark_task_started()
        sim.view.root_v[0, 2] = .002321278
        try:
            result = state.read()
        except RuntimeError as error:
            self.fail('sleeping root raw readback aborted the mixed run: ' + str(error))
        self.assertAlmostEqual(result['native_root_velocities'][BASE]['linear_velocity_m_s'][2], .002321278, places=8)
        self.assertEqual(result['linear_velocities_m_s'][BASE], [0., 0., 0.])
        self.assertEqual(set(result['native_joint_positions']), {JOINT_A, JOINT_B, V1_JOINT})

    def test_missing_real_root_enum_fails_closed_for_v2(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.mixed_state(root_type=None)

    def test_missing_paused_query_fails_closed_for_v2(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.mixed_state(paused=None)

    def test_v2_only_state_resets_and_reads_without_rigid_or_v1_views(self):
        from simscene.worker.mechanism import PreparedArticulationState
        sim = FakeMixedSimulation(); pose = authored(); pose['phase'] = 'before_sdk_warmup'
        for body in pose['bodies'].values(): body['local_ops'] = {}
        state = PreparedArticulationState(FakeStage(), {}, {'double': binding()}, pose,
                 simulation_view=sim, root_link_type=ROOT_TYPE, is_paused=lambda: True)
        self.assertIsNone(sim.rigid)
        state.reset_before_task(); state.mark_task_started()
        self.assertEqual(set(state.read()['positions']), {BASE, FIRST, SECOND})

    def test_passive_state_forwards_pause_query_and_task_start_to_delegate(self):
        from simscene.worker.initial_state import PassiveState
        delegate, _ = self.mixed_state()
        paused = lambda: True
        with patch('simscene.worker.mechanism.PreparedArticulationState', return_value=delegate) as factory:
            state = PassiveState(FakeStage(), {}, body_bindings={'double': binding()},
                                 authored_state=all_authored(), is_paused=paused)
            self.assertIs(factory.call_args.kwargs['is_paused'], paused)
            state.reset_before_task()
            state.mark_task_started()
            with self.assertRaises(RuntimeError): state.reset_before_task()


if __name__ == '__main__':
    unittest.main()
