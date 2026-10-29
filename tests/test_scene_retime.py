"""A retime must preserve order and reject physically ambiguous schedules."""
import unittest
from simscene.scene_edits.retime import retime
from simscene.scene import SceneError


class RetimeTest(unittest.TestCase):
    def test_preserves_origin_and_builds_reviewable_operations(self):
        scene = {'objects': {name: {'kind': 'box', 'dynamic': True, 'spawn_step': step}
                             for name, step in [('a', 1), ('b', 601), ('c', 1201)]}}
        result = retime(scene, ['c', 'a', 'b'], 1.5)
        self.assertEqual([x['spawn_step'] for x in result['schedule']], [1, 901, 1801])
        self.assertEqual([x['id'] for x in result['operations']], ['a', 'b', 'c'])
        self.assertEqual(scene['objects']['c']['spawn_step'], 1201)

    def test_rejects_collapsed_times_and_non_scheduled_objects(self):
        scene = {'objects': {'a': {'kind': 'box', 'dynamic': True, 'spawn_step': 1},
                             'b': {'kind': 'box', 'dynamic': True, 'spawn_step': 2},
                             'c': {'kind': 'box', 'dynamic': False, 'spawn_step': 3}}}
        with self.assertRaises(SceneError):
            retime(scene, ['a', 'b'], .1)
        with self.assertRaises(SceneError):
            retime(scene, ['a', 'c'], 2)
        scene['objects']['b']['spawn_step'] = 2000
        with self.assertRaises(SceneError):
            retime(scene, ['a', 'b'], 100)


if __name__ == '__main__':
    unittest.main()
