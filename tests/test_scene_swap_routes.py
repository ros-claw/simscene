"""Verify route swaps update item references while preserving scene data."""
import unittest
from simscene.scene_edits.swap_routes import swap_routes
from simscene.scene import SceneError


def robot(items):
    sequence = []
    for item in items:
        sequence += [{'type': 'wait_object', 'object': item, 'axis': 'x', 'minimum': 0,
                      'maximum': 1, 'max_steps': 100},
                     {'type': 'track', 'object': item, 'required_object': item,
                      'offset': [0, 0, 0], 'steps': 10},
                     {'type': 'move', 'object': item, 'offset': [0, 0, .2]}]
    return {'kind': 'asset', 'asset_path': '/robot.usda', 'pose_follower': {
        'experimental': True, 'model_directory': '/profile', 'tool_frame': 'tip',
        'tcp_prim': 'tip', 'target_position': [0, 0, 0], 'sequence': sequence}}


class SwapRoutesTest(unittest.TestCase):
    def test_changes_wait_track_and_move_references_without_mutating_scene(self):
        scene = {'objects': {'arm_a': robot(['red1', 'red2']), 'arm_b': robot(['green1', 'green2'])}}
        for name, label, step in [('red1', 'red', 3), ('red2', 'red', 7),
                                  ('green1', 'green', 2), ('green2', 'green', 6)]:
            scene['objects'][name] = {'kind': 'box', 'dynamic': True, 'class_label': label, 'spawn_step': step}
        proposal = swap_routes(scene, 'arm_a', 'arm_b')
        phases = proposal['operations'][0]['changes']['pose_follower']['sequence']
        self.assertEqual([phases[i]['object'] for i in (0, 1, 2, 3, 4, 5)],
                         ['green1', 'green1', 'green1', 'green2', 'green2', 'green2'])
        self.assertEqual(phases[1]['required_object'], 'green1')
        self.assertEqual(scene['objects']['arm_a']['pose_follower']['sequence'][0]['object'], 'red1')
        self.assertEqual(proposal['assignments']['arm_a']['after'], 'green')
        scene['objects']['arm_b']['pose_follower']['sequence'] = scene['objects']['arm_b']['pose_follower']['sequence'][:3]
        with self.assertRaises(SceneError):
            swap_routes(scene, 'arm_a', 'arm_b')


if __name__ == '__main__':
    unittest.main()
