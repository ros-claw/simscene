import copy
import unittest
from pair_check import check_pair
from test_sixty import fixed_rows


def records():
    drive = {'drive_type_codes': [1, 1], 'max_effort_nm': [1., 1.],
             'stiffness': [0., 0.], 'damping': [1., 1.]}
    repair = [{'collider': '/World/Jetbot/chassis/geometry/caster_ball_' + end + '/caster_ball_front',
               'original_resolved_targets': [], 'new_material': '/World/Jetbot/caster_material',
               'source_coefficients': {'dynamic_friction': .01}} for end in ('front', 'back')]
    override = [{'joint_path': '/World/Jetbot/chassis/' + side + '_wheel_joint',
                 'original_max_effort_nm': 'infinity', 'scene_max_effort_nm': 1., 'type': 'force'}
                for side in ('left', 'right')]
    meta = {'case_sha256': 'a', 'script_sha256': 'b', 'asset_sha256': 'c', 'isaac_version': 'v',
            'case': {'dt': 1 / 60, 'seed': 20261116, 'settling_steps': 30,
                     'solver_type': 'TGS', 'enable_external_forces_every_iteration': True,
                     'native_wheel_damping': [1., 1.], 'native_wheel_damping_tolerance': 1e-5,
                     'wheel_names': ['left_wheel_joint', 'right_wheel_joint'],
                     'spawn_orientation_wxyz': [1., 0., 0., 0.], 'initial_orientation_tolerance_rad': .02,
                     'spawn_position_m': [0., 0., .05], 'initial_xy_tolerance_m': .02,
                     'initial_z_range_m': [.02, .06]},
            'seed': 20261116, 'seeded_rngs': ['python.random', 'numpy.random'],
            'observed_physics_device': 'cpu', 'observed_physics_dt_s': 1 / 60,
            'observed_solver_settings_usd': {'solver_type': 'TGS', 'enable_external_forces_every_iteration': True},
            'wheel_dof_indices': [0, 1], 'dof_names': ['left_wheel_joint', 'right_wheel_joint'],
            'native_dof_paths': ['/World/Jetbot/chassis/left_wheel_joint', '/World/Jetbot/chassis/right_wheel_joint'],
            'native_link_paths': ['/World/Jetbot/chassis', '/World/Jetbot/left_wheel', '/World/Jetbot/right_wheel'],
            'path_xy_m': [[0., 0.], [.8, 0.]], 'requested_steps': 600, 'actual_task_steps': 600,
            'stage_physics_repairs': repair, 'stage_drive_effort_overrides': override,
            'native_drive_before': drive, 'native_drive_after': drive}
    log = ('Simulation App Startup Complete isaacsim.replicator.experimental.mobility_gen-0.5.0 '
           'isaacsim.replicator.mobility_gen.examples-0.4.1')
    a = {'metadata': {**copy.deepcopy(meta), 'mode': 'positive', 'terminal_status': 'arrived'},
         'rows': fixed_rows('positive'), 'process': {'exit_code': 0}, 'log': log}
    b = {'metadata': {**copy.deepcopy(meta), 'mode': 'zero', 'terminal_status': 'zero_target_duration_complete'},
         'rows': fixed_rows('zero'), 'process': {'exit_code': 0}, 'log': log}
    return a, b


class PairedEvidenceTests(unittest.TestCase):
    def test_matching_pair_passes(self):
        self.assertTrue(check_pair(*records())['passed'])

    def test_different_case_and_missing_repair_fail(self):
        a, b = records(); b['metadata']['case_sha256'] = 'different'
        self.assertFalse(check_pair(a, b)['passed'])
        a, b = records(); b['metadata']['stage_physics_repairs'] = []
        self.assertFalse(check_pair(a, b)['passed'])

    def test_wrong_effort_or_failed_process_fail(self):
        a, b = records(); b['metadata']['native_drive_after']['max_effort_nm'][0] = float('inf')
        self.assertFalse(check_pair(a, b)['passed'])
        a, b = records(); b['process']['exit_code'] = 1
        self.assertFalse(check_pair(a, b)['passed'])


if __name__ == '__main__':
    unittest.main()
