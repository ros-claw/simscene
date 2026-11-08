import copy
import hashlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.mechanism_modules import compile_plan, save_plan, apply_plan
from simscene.scene import SceneError, SceneStore


class ModuleTests(unittest.TestCase):
    def test_rigid_frame_covariance_and_no_drives(self):
        base = compile_plan('domino_line', 'tiles', {'count': 12})
        q = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
        moved = compile_plan('domino_line', 'tiles', {'count': 12, 'origin': [3, -2, 1], 'orientation_wxyz': q})
        for a, b in zip(base['operations'], moved['operations']):
            x, y, z = a['object']['position']
            self.assertAlmostEqual(b['object']['position'][0], 3-y)
            self.assertAlmostEqual(b['object']['position'][1], -2+x)
            self.assertAlmostEqual(b['object']['position'][2], 1+z)
            self.assertNotIn('pose_follower', b['object'])
        self.assertFalse(moved['validation']['physics_tested'])

    def test_arc_rejects_overlap_and_unreachable_gaps(self):
        with self.assertRaises(SceneError):
            compile_plan('domino_arc', 'bad', {'count': 100, 'radius_m': .1, 'sweep_degrees': 20})
        with self.assertRaises(SceneError):
            compile_plan('domino_arc', 'bad', {'count': 3, 'radius_m': 1})
        self.assertEqual(len(compile_plan('domino_arc', 'arc', {'count': 20})['operations']), 40)

    def test_door_metric_joint_anchor_and_passive_limits(self):
        from pxr import Usd
        from simscene.usd_export import export_scene
        from simscene.worker.joint_observation import sample
        plan = compile_plan('door_bridge', 'bridge', {'origin': [2, 1, .8], 'raised_angle_degrees': 70})
        scene = {'revision': 0, 'objects': {op['id']: op['object'] for op in plan['operations']}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'scene.usda'; export_scene(scene, p)
            stage = Usd.Stage.Open(str(p)); state = sample(stage, scene['objects'])['bridge_hinge']
            self.assertLess(state['anchor_error_m'], 1e-6)
            self.assertFalse(state['drive_present'])
            self.assertAlmostEqual(state['angle_degrees'], -70, places=4)

    def test_apply_hash_revision_and_idempotency(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'SIMSCENE_HOME': d}):
            store = SceneStore(); store.open('probe')
            plan = compile_plan('domino_line', 'row', {'count': 4})
            p = Path(d)/'plan.json'; summary = save_plan(plan, p)
            result = apply_plan('probe', p, summary['sha256'], 0, 'apply')
            self.assertEqual(result['revision'], 1)
            self.assertEqual(apply_plan('probe', p, summary['sha256'], 0, 'apply'), result)
            altered = copy.deepcopy(plan); altered['operations'][0]['object']['mass_kg'] = 99
            p.write_text(json.dumps(altered)); digest = hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(SceneError):
                apply_plan('probe', p, digest, 1, 'tamper')
