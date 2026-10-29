"""Observed pickup delays must produce a reviewable, source-bound proposal."""
import hashlib
import json
import unittest

from simscene.scene import SceneError
from simscene.scene_edits.synchronize import synchronize


class SynchronizeTests(unittest.TestCase):
    def setUp(self):
        self.ids = ['b0', 'g0', 'r0', 'b1', 'g1', 'r1']
        labels = ['blue', 'green', 'red', 'blue', 'green', 'red']
        self.scene = {'objects': {name: {'kind': 'box', 'dynamic': True, 'class_label': label,
                                         'spawn_step': 10 + 100*i}
                                  for i, (name, label) in enumerate(zip(self.ids, labels))}}
        digest = hashlib.sha256(json.dumps(self.scene, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.case = {'source_scene_sha256': digest, 'expected_spawn_order': self.ids, 'objects': []}
        followers = {name: {'transitions': []} for name in ('far', 'middle', 'near')}
        delays = {'blue': ('far', 1200), 'green': ('middle', 800), 'red': ('near', 400)}
        events = []
        for i, (name, label) in enumerate(zip(self.ids, labels)):
            robot, delay = delays[label]
            phase = 4*(i//3)
            step = 10 + 100*i
            self.case['objects'].append({'part_id': name, 'class_label': label, 'robot_id': robot,
                                         'tracking_phase': phase, 'release_phase': phase+1})
            followers[robot]['transitions'].extend([{'index': phase, 'physics_step': step+delay},
                                                    {'index': phase+2, 'physics_step': step+delay+300}])
            events.append({'id': name, 'class_label': label, 'physics_step': step})
        self.run = {'actual_physics_steps': 3000, 'requested_physics_steps': 3000,
                    'followers': followers, 'spawn_events': events}

    def test_observed_delays_align_first_cycles_and_preserve_per_class_order(self):
        result = synchronize(self.scene, self.run, self.case, self.ids)
        self.assertEqual(result['class_order'], ['blue', 'green', 'red'])
        self.assertEqual(result['interval_steps'], 400)
        self.assertEqual([entry['id'] for entry in result['schedule']], self.ids)
        arrivals = [entry['spawn_step'] + result['observed_first_cycles'][entry['class_label']]['delay_steps']
                    for entry in result['schedule'][:3]]
        self.assertEqual(len(set(arrivals)), 1)
        self.assertEqual(self.scene['objects']['g0']['spawn_step'], 110)

    def test_rejects_stale_scene_incomplete_run_and_missing_cycle(self):
        self.scene['objects']['g0']['spawn_step'] += 1
        with self.assertRaisesRegex(SceneError, 'current scene'):
            synchronize(self.scene, self.run, self.case, self.ids)
        self.scene['objects']['g0']['spawn_step'] -= 1
        self.run['actual_physics_steps'] = 100
        with self.assertRaisesRegex(SceneError, 'complete'):
            synchronize(self.scene, self.run, self.case, self.ids)
        self.run['actual_physics_steps'] = 3000
        self.run['followers']['middle']['transitions'].pop(0)
        with self.assertRaisesRegex(SceneError, 'pickup cycle'):
            synchronize(self.scene, self.run, self.case, self.ids)


if __name__ == '__main__':
    unittest.main()
