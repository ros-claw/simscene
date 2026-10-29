"""Move a bin and its explicitly selected waypoints without touching others."""
import unittest
from simscene.scene_edits.translate_group import translate_group
from simscene.scene import SceneError


class TranslateGroupTest(unittest.TestCase):
    def test_proposal_moves_only_requested_objects_and_waypoints(self):
        scene = {'objects': {
            'floor': {'kind': 'box', 'position': [1, 1, 0], 'size': [1, 1, .1]},
            'wall': {'kind': 'box', 'position': [1, 1.5, .5], 'size': [1, .1, 1]},
            'arm': {'kind': 'asset', 'asset_path': '/robot.usda', 'pose_follower': {
                'experimental': True, 'model_directory': '/profile', 'tool_frame': 'tip', 'tcp_prim': 'tip',
                'target_position': [0, 0, 0], 'sequence': [
                    {'type': 'move', 'position': [1, 1, .8]},
                    {'type': 'move', 'position': [1, 1, .4]},
                    {'type': 'move', 'position': [-2, -2, .8]}]}}}}
        proposal = translate_group(scene, ['floor', 'wall'], [0, -2, 0],
                                   {'robot_id': 'arm', 'center_xy': [1, 1], 'radius_m': .2})
        self.assertEqual(proposal['changed_move_phases'], {'arm': [0, 1]})
        self.assertEqual(proposal['operations'][0]['changes']['position'], [1, -1, 0])
        phases = proposal['operations'][2]['changes']['pose_follower']['sequence']
        self.assertEqual(phases[0]['position'], [1, -1, .8])
        self.assertEqual(phases[2]['position'], [-2, -2, .8])
        self.assertEqual(scene['objects']['floor']['position'], [1, 1, 0])
        with self.assertRaises(SceneError):
            translate_group(scene, ['floor'], [0, -2, 0],
                            {'robot_id': 'arm', 'center_xy': [10, 10], 'radius_m': .2})


if __name__ == '__main__':
    unittest.main()
