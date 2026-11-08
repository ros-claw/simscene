import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from simscene.replay import prepare, status, sha


class ReplayTests(unittest.TestCase):
    def fixture(self, d):
        run = Path(d)/'source'; run.mkdir()
        for name in ['scene.usda', 'run-lock.json', 'evidence-lock.json']:(run/name).write_text('{}')
        (run/'spec.json').write_text(json.dumps({'objects': {'box': {'dynamic': True}}}))
        def row(step):return {'physics_steps': step, 'simulation_time_s': step/60,
            'positions': {'/World/box': [step*.1, 0, 1]}, 'orientations_wxyz': {'/World/box': [1, 0, 0, 0]}}
        data = {'initial_observation': row(0), 'samples': [row(1), row(2)]}
        (run/'result.json').write_text(json.dumps(data))
        shots = Path(d)/'shots.json'; shots.write_text(json.dumps([{'id': 'detail', 'start_step': 0,
            'end_step': 3, 'stride': 1, 'camera': {'position': [1, -2, 1], 'target': [0, 0, 1]}}]))
        return run, shots, data

    @patch('simscene.run_integrity.verify', return_value={'passed': True})
    @patch('simscene.evidence_integrity.verify', return_value={'passed': True})
    def test_exact_source_steps_and_half_speed_without_interpolation(self, *_):
        with tempfile.TemporaryDirectory() as d:
            run, shots, _ = self.fixture(d); dest = Path(d)/'replay'; prepare(run, shots, dest)
            archive = np.load(dest/'poses.npz', allow_pickle=False)
            np.testing.assert_array_equal(archive['steps'], [0, 1, 2])
            np.testing.assert_array_equal(archive['poses'][:, 0, 0], [0, .1, .2])
            req = json.loads((dest/'request.json').read_text())
            self.assertEqual(req['shots'][0]['playback_speed'], .5)
            self.assertEqual(req['source_sha256']['result.json'], sha(run/'result.json'))

    @patch('simscene.run_integrity.verify', return_value={'passed': True})
    @patch('simscene.evidence_integrity.verify', return_value={'passed': True})
    def test_missing_middle_sample_is_never_filled(self, *_):
        with tempfile.TemporaryDirectory() as d:
            run, shots, data = self.fixture(d); data['samples'] = data['samples'][1:]
            (run/'result.json').write_text(json.dumps(data)); dest = Path(d)/'replay'
            with self.assertRaisesRegex(ValueError, 'missing source steps'):prepare(run, shots, dest)
            self.assertFalse(dest.exists())

    def test_changed_camera_request_cannot_reuse_old_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); p = root/'request.json'; p.write_text('{}')
            (root/'process-exit.json').write_text('{"exit_code":0}')
            (root/'render-complete.json').write_text(json.dumps({'request_sha256': sha(p), 'new_physics_steps': 0, 'new_physics_runs': 0}))
            self.assertEqual(status(p)['state'], 'rendered')
            p.write_text('{"changed_camera":true}')
            self.assertEqual(status(p)['state'], 'stale_request')
