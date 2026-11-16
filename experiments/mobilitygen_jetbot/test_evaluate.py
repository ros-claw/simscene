import unittest

from evaluate import evaluate


def sample(step, x, *, target=0.0, arrived=None, collision=False):
    return {
        "step": step,
        "physics_callback_count": step + 30,
        "time_s": step / 60,
        "base_position_m": [x, 0.0, 0.04],
        "base_orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
        "base_com_linear_velocity_m_s": [0.0, 0.0, 0.0],
        "base_angular_velocity_rad_s": [0.0, 0.0, 0.0],
        "wheel_positions_rad": [step * .01, step * .01],
        "wheel_targets_rad_s": [target, target],
        "wheel_velocities_rad_s": [target, target],
        "goal_distance_m": abs(0.8 - x),
        "arrived": abs(0.8 - x) <= .08 if arrived is None else arrived,
        "obstacle_collision": collision,
        "map_out_of_bounds": False,
        "map_collision": False,
        "ground_contact": True,
        "contact_actor_pairs": [['/World/Jetbot/chassis', '/World/Ground'],
                                ['/World/Jetbot/left_wheel', '/World/Ground'],
                                ['/World/Jetbot/right_wheel', '/World/Ground']] +
                               ([['/World/Jetbot/chassis', '/World/WallEast']] if collision else []),
    }


class EvaluationTests(unittest.TestCase):
    def test_positive_requires_real_displacement_and_arrival(self):
        path = [sample(i, i * .75 / 200, target=0 if i == 0 else 1) for i in range(201)]
        self.assertTrue(evaluate(path, "positive")["passed"])
        self.assertFalse(evaluate([sample(0, 0), sample(1, 0.01, target=1)], "positive")["passed"])

    def test_zero_requires_zero_targets_and_little_displacement(self):
        self.assertTrue(evaluate([sample(0, 0), sample(1, 0.001)], "zero")["passed"])
        self.assertFalse(evaluate([sample(0, 0), sample(1, 0.001, target=0.1)], "zero")["passed"])
        self.assertFalse(evaluate([sample(0, 0), sample(1, 0.2)], "zero")["passed"])

    def test_collision_and_incomplete_or_nonfinite_readback_fail_closed(self):
        self.assertFalse(evaluate([sample(0, 0), sample(1, 0.75, arrived=True, collision=True)], "positive")["passed"])
        self.assertFalse(evaluate([sample(0, 0), sample(2, 0.75, arrived=True)], "positive")["passed"])
        self.assertFalse(evaluate([sample(0, 0), sample(1, float('nan'), arrived=True)], "positive")["passed"])
        no_contact = [sample(0, 0), sample(1, 0.001)]
        for item in no_contact:
            item['ground_contact'] = False
        self.assertFalse(evaluate(no_contact, "zero")["passed"])

    def test_rejects_teleport_and_missing_physics_callback(self):
        self.assertFalse(evaluate([sample(0, 0), sample(1, 0.75, target=1, arrived=True)], "positive")["passed"])
        values = [sample(0, 0), sample(1, 0.001)]
        values[-1]['physics_callback_count'] = values[0]['physics_callback_count']
        self.assertFalse(evaluate(values, "zero")["passed"])

    def test_zero_control_cannot_move_away_and_return(self):
        values = [sample(0, 0), sample(1, .2), sample(2, 0)]
        self.assertFalse(evaluate(values, "zero")["passed"])


if __name__ == "__main__":
    unittest.main()
