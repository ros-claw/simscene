import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from simscene.robotics.profiles import prepare, suggest, pick_cycle


class ProfileTest(unittest.TestCase):
    def test_generation_uses_selected_asset_and_returns_published_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / 'chosen.usd'; asset.write_text('USD')
            runtime = root / 'python.sh'; runtime.touch()

            def run(command, **kwargs):
                self.assertEqual(command[command.index('--asset-usd') + 1], str(asset))
                self.assertIn('simscene', str(command[1]))
                self.assertIn('PYTHONPATH', kwargs['env'])
                output = Path(command[command.index('--output') + 1])
                for name in ('robot.urdf', 'robot.xrdf', 'rmp_flow.yaml'):
                    (output / name).write_text('generated')
                (output / 'profile.json').write_text(json.dumps({'status': 'experimental'}))
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch.dict(os.environ, {'SIMSCENE_HOME': str(root), 'SIMSCENE_ISAAC_PYTHON': str(runtime)}), patch('simscene.robotics.profiles.subprocess.run', side_effect=run):
                result = prepare('franka_panda', str(asset))
            self.assertEqual(result['status'], 'experimental')
            self.assertTrue((Path(result['model_directory']) / 'robot.urdf').is_file())
            self.assertFalse(list((root / 'profiles').glob('.profile-*')))

    def test_suggestion_rotates_target_into_world_and_preserves_profile(self):
        import math
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'profile.json').write_text(json.dumps({'model':'franka_panda','tool_frame':'tcp','tcp_prim':'hand','tcp_offset':[0,0,.1]}))
            result=suggest(directory,[2,-.05,0],[math.sqrt(.5),0,0,-math.sqrt(.5)])
            config=result['pose_follower']
            self.assertAlmostEqual(config['target_position'][0],2)
            self.assertAlmostEqual(config['target_position'][1],-.5)
            self.assertAlmostEqual(config['target_position'][2],.34)
            self.assertEqual(config['model_directory'],directory)
            self.assertTrue(config['experimental'])
            self.assertEqual(config['gripper_physics']['max_force'],20)
            self.assertTrue(any('experimental' in limitation for limitation in result['limitations']))
            with self.assertRaisesRegex(ValueError,'normalized'):
                suggest(directory,[0,0,0],[2,0,0,0])

    def test_pick_template_expands_workpiece_and_slot_without_claiming_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'profile.json').write_text(json.dumps({'model':'franka_panda'}))
            plan=pick_cycle(directory,'$slot',return_position=[0,0,1])
            self.assertEqual(plan['cycle'][0]['object'],'$item')
            self.assertEqual(plan['cycle'][3]['position'],'$slot')
            self.assertEqual(plan['cycle'][3]['rmp_max_joint_speed'],.4)
            self.assertEqual(plan['cycle'][-1]['position'],[0,0,1])
            self.assertNotIn('slot_offset',plan['cycle'][-1])
            self.assertTrue(any('validation' in x for x in plan['assumptions']))
            with self.assertRaises(ValueError):pick_cycle(directory,[0,0,float('nan')])

    def test_pick_template_composes_into_a_valid_dynamic_stream(self):
        from simscene.scene import SceneStore
        from simscene.composition import plan_stream
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'model';model.mkdir()
            (model/'profile.json').write_text(json.dumps({'model':'franka_panda','tool_frame':'tcp','tcp_prim':'hand','tcp_offset':[0,0,.1]}))
            cfg=suggest(str(model),[0,0,0],[1,0,0,0])['pose_follower']
            store=SceneStore(root/'state');store.open('scene')
            store.apply('scene',0,'arm',[{'op':'add','id':'arm','object':{'kind':'asset','asset_path':'/arm.usd','pose_follower':cfg}}])
            cycle=pick_cycle(str(model),'$slot',return_position=[.5,0,.6])['cycle']
            routes={'red':{'robot_id':'arm','wait':{'axis':'x','minimum':0,'maximum':1,'max_steps':500},'slots':[[.5,.3,.4]],'cycle':cycle}}
            proposal=plan_stream(store.get('scene'),'part',['red'],routes,[0,0,.3],[.04]*3,240)
            store.apply('scene',1,'stream',proposal['operations'])
            phases=store.get('scene')['objects']['arm']['pose_follower']['sequence']
            self.assertEqual(phases[1]['object'],'part0000')
            self.assertEqual(phases[4]['position'],[.5,.3,.53])

    def test_incompatible_asset_cleans_partial_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); asset=root/'chosen.usd'; asset.touch(); runtime=root/'python.sh'; runtime.touch()
            failed=subprocess.CompletedProcess([], 1, '', 'frames do not match')
            with patch.dict(os.environ, {'SIMSCENE_HOME':str(root),'SIMSCENE_ISAAC_PYTHON':str(runtime)}), patch('simscene.robotics.profiles.subprocess.run', return_value=failed):
                with self.assertRaisesRegex(ValueError, 'frames do not match'):
                    prepare('ur10_short_suction', str(asset))
            self.assertEqual(list((root/'profiles').iterdir()), [])
