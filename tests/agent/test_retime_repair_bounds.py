"""A timing repair may move a waypoint slightly, but not change the task."""
import ast
import copy
import math
from pathlib import Path
import unittest


class RetimeRepairBoundsTests(unittest.TestCase):
    def test_bounded_waypoint_and_reject_other_changes(self):
        path = Path(__file__).resolve().parents[2]/'experiments/verify_agent_retime_repair.py'
        tree = ast.parse(path.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('functional_objects', 'bounded_motion_repairs')]
        module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
        ns = {'copy': copy, 'math': math, 'case': {'maximum_move_target_shift_m': .05,
                                                   'maximum_move_timeout_factor': 2.0}}
        exec(compile(module, str(path), 'exec'), ns)
        check = ns['bounded_motion_repairs']
        old = {'arm': {'kind': 'asset', 'pose_follower': {'sequence': [
            {'type': 'move', 'position': [0., 0., 1.], 'max_steps': 600}]}},
            'part': {'kind': 'box', 'spawn_step': 100, 'class_label': 'red'}}
        new = copy.deepcopy(old)
        new['arm']['pose_follower']['sequence'][0]['position'][0] = .03
        new['part']['spawn_step'] = 150
        self.assertTrue(check(old, new))
        new['arm']['pose_follower']['sequence'][0]['position'][0] = .06
        self.assertFalse(check(old, new))
        new['arm']['pose_follower']['sequence'][0]['position'][0] = .03
        new['part']['class_label'] = 'blue'
        self.assertFalse(check(old, new))


if __name__ == '__main__':
    unittest.main()
