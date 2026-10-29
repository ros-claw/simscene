"""Adversarial checks for the independent workbench composition evaluator."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkbenchVerifierTest(unittest.TestCase):
    def test_rows_and_camera_are_checked_from_observed_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            objects = {'arm': {'kind': 'asset', 'asset_path': '/FrankaRobotics/FrankaPanda/franka.usd'},
                       'light': {'kind': 'light'},
                       'camera': {'kind': 'camera', 'camera_orbit': {'center': [0, 0, 0]}}}
            for row, y in enumerate((-.3, .3)):
                for col, x in enumerate((-.2, .2)):
                    for side, center, size in [
                        ('base', [x, y, 0], [.2, .2, .02]),
                        ('left', [x-.1, y, .08], [.01, .2, .12]),
                        ('right', [x+.1, y, .08], [.01, .2, .12]),
                        ('front', [x, y-.1, .08], [.18, .01, .12]),
                        ('back', [x, y+.1, .08], [.18, .01, .12])]:
                        objects[f'{row}_{col}_{side}'] = {'kind': 'box', 'position': center, 'size': size}
            spec = {'objects': objects}
            samples = [{'cameras': {'camera': {'position': [math.cos(i*.6), math.sin(i*.6), 1]}}} for i in range(12)]
            result = {'positions': {'/World/arm/Asset/link': [0, 0, 0]}, 'samples': samples,
                      'actual_physics_steps': 120, 'requested_physics_steps': 120, 'videos': {'camera': {}}}
            (path/'spec.json').write_text(json.dumps(spec))
            (path/'result.json').write_text(json.dumps(result))
            case = path/'case.json'
            case.write_bytes((ROOT/'tests/fixtures/agent_workbench_case.json').read_bytes())
            import hashlib
            case.with_suffix('.sha256').write_text(hashlib.sha256(case.read_bytes()).hexdigest())
            def report():
                env = dict(os.environ, PYTHONPATH=str(ROOT/'src'))
                run = subprocess.run([sys.executable, str(ROOT/'experiments/verify_workbench_eval.py'), str(path), str(case)],
                                     capture_output=True, text=True, env=env, check=False)
                return json.loads(run.stdout)
            initial = report()['checks']
            self.assertTrue(initial['two_rows_of_open_bins'])
            self.assertTrue(initial['orbit_observed'])
            self.assertTrue(initial['case_copy_hash_matches'])
            # The missing hash locks keep this synthetic run from being accepted.
            self.assertFalse(initial['input_integrity'])
            for sample in result['samples']:
                sample['cameras']['camera']['position'] = [1, 0, 1]
            (path/'result.json').write_text(json.dumps(result))
            for key in list(objects):
                if key.startswith('1_'):
                    del objects[key]
            (path/'spec.json').write_text(json.dumps(spec))
            case.with_suffix('.sha256').write_text('incorrect')
            failed = report()['checks']
            self.assertFalse(failed['two_rows_of_open_bins'])
            self.assertFalse(failed['orbit_observed'])
            self.assertFalse(failed['case_copy_hash_matches'])


if __name__ == '__main__':
    unittest.main()
