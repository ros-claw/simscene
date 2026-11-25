import copy
import math
import unittest

from pair_check import check_pair
from test_pair import records


def valid_records():
    positive, control = records()
    for run in (positive, control):
        meta = run['metadata']
        meta['case'].update(seed=20261116, wheel_names=['left_wheel_joint', 'right_wheel_joint'],
                            spawn_orientation_wxyz=[1., 0., 0., 0.], initial_orientation_tolerance_rad=.02,
                            spawn_position_m=[0., 0., .05], initial_xy_tolerance_m=.02,
                            initial_z_range_m=[.02, .06],
                            initial_pair_wheel_position_tolerance_rad=.001,
                            initial_pair_wheel_velocity_tolerance_rad_s=.001,
                            initial_linear_speed_tolerance_m_s=.05, initial_angular_speed_tolerance_rad_s=.1,
                            initial_pair_linear_velocity_tolerance_m_s=.005,
                            initial_pair_angular_velocity_tolerance_rad_s=.02,
                            minimum_driven_steps=10)
        meta['seed'] = 20261116
        meta['seeded_rngs'] = ['python.random', 'numpy.random']
        for row in run['rows']:
            row['time_s'] = row['step'] / 60
            row['wheel_positions_rad'] = [row['step'] * .01, row['step'] * .01]
            row['base_com_linear_velocity_m_s'] = [0., 0., 0.]
            row['base_angular_velocity_rad_s'] = [0., 0., 0.]
            row['contact_actor_pairs'] = [['/World/Jetbot/chassis', '/World/Ground'],
                                          ['/World/Jetbot/left_wheel', '/World/Ground'],
                                          ['/World/Jetbot/right_wheel', '/World/Ground']]
    return positive, control


class ReviewRegressionTests(unittest.TestCase):
    def test_matching_enriched_records_pass(self):
        self.assertTrue(check_pair(*valid_records())['passed'])

    def test_wall_contact_cannot_be_hidden_by_false_flag(self):
        a, b = valid_records()
        a['rows'][10]['contact_actor_pairs'].append(['/World/Jetbot/chassis', '/World/WallEast'])
        a['rows'][10]['obstacle_collision'] = False
        self.assertFalse(check_pair(a, b)['passed'])

    def test_invalid_time_and_missing_or_nonfinite_joint_positions_fail(self):
        for field, value in [('time_s', -987), ('time_s', float('nan')),
                             ('wheel_positions_rad', None), ('wheel_positions_rad', [0., float('inf')])]:
            a, b = valid_records()
            for row in a['rows']:
                row[field] = value
            self.assertFalse(check_pair(a, b)['passed'], field)

    def test_wheel_index_name_mapping_is_not_just_equal_across_runs(self):
        a, b = valid_records()
        for run in (a, b):
            run['metadata']['wheel_dof_indices'] = [1, 0]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_swapped_native_paths_fail_even_when_names_match(self):
        a, b = valid_records()
        for run in (a, b):
            run['metadata']['native_dof_paths'].reverse()
        self.assertFalse(check_pair(a, b)['passed'])

    def test_native_drive_configuration_must_match_both_runs_and_times(self):
        a, b = valid_records()
        b['metadata']['native_drive_before']['damping'] = [2., 2.]
        b['metadata']['native_drive_after']['damping'] = [2., 2.]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_common_180_degree_initial_yaw_is_not_accepted(self):
        a, b = valid_records()
        for run in (a, b):
            run['rows'][0]['base_orientation_wxyz'] = [0., 0., 0., 1.]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_common_wrong_initial_height_is_not_accepted(self):
        a, b = valid_records()
        for run in (a, b):
            for row in run['rows']:
                row['base_position_m'][2] = .5
        self.assertFalse(check_pair(a, b)['passed'])

    def test_only_step_zero_nonzero_does_not_establish_task_driving(self):
        a, b = valid_records()
        for row in a['rows']:
            value = [1., 1.] if row['step'] == 0 else [0., 0.]
            row['wheel_targets_rad_s'] = value
            row['native_wheel_targets_rad_s'] = list(value)
        self.assertFalse(check_pair(a, b)['passed'])

    def test_arrival_flag_must_match_observed_distance(self):
        a, b = valid_records()
        a['rows'][0]['arrived'] = True
        a['rows'][0]['wheel_targets_rad_s'] = [1., 1.]
        a['rows'][0]['native_wheel_targets_rad_s'] = [1., 1.]
        for row in a['rows'][1:]:
            row['wheel_targets_rad_s'] = [0., 0.]
            row['native_wheel_targets_rad_s'] = [0., 0.]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_seed_must_be_recorded_and_agree_with_frozen_case(self):
        a, b = valid_records()
        del a['metadata']['seed']; del b['metadata']['seed']
        self.assertFalse(check_pair(a, b)['passed'])
        a, b = valid_records()
        b['metadata']['seed'] = 7
        self.assertFalse(check_pair(a, b)['passed'])

    def test_matching_paths_must_still_be_the_frozen_route(self):
        a, b = valid_records()
        for run in (a, b):
            run['metadata']['path_xy_m'] = [[100., 100.], [200., 200.]]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_native_pose_cannot_leave_physical_walls_with_false_map_flags(self):
        a, b = valid_records()
        for row in a['rows']:
            x = row['base_position_m'][0]
            y = 2.1 * math.sin(math.pi * row['step'] / 600)
            row['base_position_m'][1] = y
            row['goal_distance_m'] = math.hypot(.8 - x, y)
            row['arrived'] = row['goal_distance_m'] <= .08
        self.assertFalse(check_pair(a, b)['passed'])

    def test_chassis_contact_does_not_replace_wheel_contacts(self):
        for side in ('left', 'right'):
            with self.subTest(side=side):
                a, b = valid_records()
                for run in (a, b):
                    for row in run['rows'][1:]:
                        row['contact_actor_pairs'] = [pair for pair in row['contact_actor_pairs']
                                                      if '/World/Jetbot/' + side + '_wheel' not in pair]
                self.assertFalse(check_pair(a, b)['passed'])

    def test_settling_contacts_cannot_stand_in_for_task_contacts(self):
        a, b = valid_records()
        for run in (a, b):
            for row in run['rows'][1:]:
                row['contact_actor_pairs'] = []
                row['ground_contact'] = False
        self.assertFalse(check_pair(a, b)['passed'])

    def test_missing_or_disabled_tgs_solver_configuration_is_rejected(self):
        a, b = valid_records()
        for run in (a, b):
            run['metadata']['observed_solver_settings_usd']['enable_external_forces_every_iteration'] = False
        self.assertFalse(check_pair(a, b)['passed'])

    def test_pair_result_explicitly_declares_native_velocity_unverified(self):
        result = check_pair(*valid_records())
        self.assertEqual(result.get('native_velocity_consistency'), 'not_verified')

    def test_uniformly_wrong_native_drive_damping_is_rejected(self):
        a, b = valid_records()
        for run in (a, b):
            for key in ('native_drive_before', 'native_drive_after'):
                run['metadata'][key]['damping'] = [1e-12, 1e12]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_ten_initial_commands_cannot_explain_the_recorded_motion_interval(self):
        a, b = valid_records()
        for row in a['rows'][11:]:
            row['wheel_targets_rad_s'] = [0., 0.]
            row['native_wheel_targets_rad_s'] = [0., 0.]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_constant_sampled_wheel_positions_do_not_show_wheel_motion(self):
        a, b = valid_records()
        for row in a['rows']:
            row['wheel_positions_rad'] = [0., 0.]
        self.assertFalse(check_pair(a, b)['passed'])

    def test_callback_clock_must_start_after_exact_frozen_settling_steps(self):
        a, b = valid_records()
        for run in (a, b):
            for row in run['rows']:
                row['physics_callback_count'] += 7
        self.assertFalse(check_pair(a, b)['passed'])

    def test_initial_native_velocities_and_wheel_positions_are_paired_and_bounded(self):
        for field, value in [('wheel_positions_rad', [.1, 0.]),
                             ('wheel_velocities_rad_s', [.01, 0.]),
                             ('base_com_linear_velocity_m_s', [.02, 0., 0.]),
                             ('base_angular_velocity_rad_s', [.04, 0., 0.])]:
            a, b = valid_records()
            b['rows'][0][field] = value
            self.assertFalse(check_pair(a, b)['passed'], field)
        for field, value in [('base_com_linear_velocity_m_s', [.1, 0., 0.]),
                             ('base_angular_velocity_rad_s', [.2, 0., 0.])]:
            a, b = valid_records()
            a['rows'][0][field] = value; b['rows'][0][field] = value
            self.assertFalse(check_pair(a, b)['passed'], field)

    def test_missing_or_nonfinite_native_chassis_velocity_fails(self):
        a, b = valid_records()
        del a['rows'][1]['base_com_linear_velocity_m_s']
        self.assertFalse(check_pair(a, b)['passed'])
        a, b = valid_records()
        a['rows'][1]['base_angular_velocity_rad_s'] = [float('nan'), 0., 0.]
        self.assertFalse(check_pair(a, b)['passed'])


if __name__ == '__main__':
    unittest.main()
