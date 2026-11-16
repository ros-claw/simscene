import copy
import unittest
from evaluate import evaluate_horizon, validate_drive_snapshot
from test_evaluate import sample


def fixed_rows(mode):
    rows = []
    for step in range(601):
        x = min(.75, step * .75 / 200) if mode == 'positive' else 0.
        arrived = abs(.8 - x) <= .08
        target = 1. if mode == 'positive' and step and not arrived else 0.
        row = sample(step, x, target=target, arrived=arrived)
        row['native_wheel_targets_rad_s'] = list(row['wheel_targets_rad_s'])
        rows.append(row)
    return rows


class FixedHorizonTests(unittest.TestCase):
    def test_fixed_horizon_positive_and_zero(self):
        self.assertTrue(evaluate_horizon(fixed_rows('positive'), 'positive')['passed'])
        self.assertTrue(evaluate_horizon(fixed_rows('zero'), 'zero')['passed'])

    def test_partial_run_or_nonzero_terminal_target_rejected(self):
        values = fixed_rows('positive')
        self.assertFalse(evaluate_horizon(values[:-1], 'positive')['passed'])
        values[-1]['wheel_targets_rad_s'] = [1., 1.]
        values[-1]['native_wheel_targets_rad_s'] = [1., 1.]
        self.assertFalse(evaluate_horizon(values, 'positive')['passed'])

    def test_native_drive_target_mismatch_rejected(self):
        values = fixed_rows('zero')
        values[10]['native_wheel_targets_rad_s'] = [1., 0.]
        self.assertFalse(evaluate_horizon(values, 'zero')['passed'])

    def test_both_native_force_drives_require_finite_effort_and_gains(self):
        good = {'drive_type_codes': [1, 1], 'max_effort_nm': [1., 1.],
                'stiffness': [0., 0.], 'damping': [1., 1.]}
        self.assertEqual(validate_drive_snapshot(good), [])
        for key, bad in [('max_effort_nm', [1., float('inf')]),
                         ('max_effort_nm', [1., 2.]), ('damping', [1., 0.]),
                         ('drive_type_codes', [1, 2])]:
            value = copy.deepcopy(good); value[key] = bad
            self.assertTrue(validate_drive_snapshot(value))


if __name__ == '__main__':
    unittest.main()
