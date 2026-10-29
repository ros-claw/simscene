"""Regression checks for inline, frozen case support."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from simscene import jobs
from simscene.scene import SceneError, SceneStore


class InlineCaseTest(unittest.TestCase):
    def test_incomplete_collision_policy_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); executable=root/'python.sh'; executable.touch()
            with patch.dict('os.environ',{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(executable)}):
                store=SceneStore();store.open('s')
                follower={'experimental':True,'model_directory':'/tmp/model','tool_frame':'tcp','tcp_prim':'tcp',
                          'target_position':[0,0,1],'monitor_collisions':True,'self_collision_enabled':True,'diagnose_overlaps':True}
                operations=[{'op':'add','id':name,'object':{'kind':'asset','asset_path':'/tmp/robot.usd','pose_follower':follower}} for name in ('a','b')]
                store.apply('s',0,'robots',operations)
                case={'expected_spawn_order':['one','two'],'objects':[{'robot_id':'a'},{'robot_id':'b'}],
                      'collision_policy':{'mechanical_pairs':{'a':[]},'allowed_mechanical_contacts':{'a':[]},'grasp_bodies':{'a':['finger']}}}
                with patch('simscene.jobs.export_scene') as export:
                    with self.assertRaisesRegex(SceneError,'cover exactly all case robots'):
                        jobs.start('s',10,case=case)
                    export.assert_not_called()
                    self.assertFalse((root/'runs').exists())

    def test_case_is_snapshotted_and_stale_scene_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);executable=root/'python.sh';executable.touch()
            with patch.dict('os.environ',{'SIMSCENE_HOME':directory,'SIMSCENE_ISAAC_PYTHON':str(executable)}):
                scene=SceneStore().open('s')
                digest=hashlib.sha256(json.dumps(scene,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                case={'source_scene_sha256':digest,'threshold':.9}
                with patch('simscene.jobs.export_scene',side_effect=lambda scene,path:path.write_text('stage')),patch('simscene.jobs.subprocess.Popen',return_value=Mock(pid=123456789)):
                    job=jobs.start('s',10,case=case)
                    run=root/'runs'/job['run_id'];lock=json.loads((run/'run-lock.json').read_text())
                    case['threshold']=.1
                    saved=run/lock['acceptance_case_file']
                    self.assertEqual(json.loads(saved.read_text())['threshold'],.9)
                    self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(),lock['acceptance_case_sha256'])
                    del jobs._jobs[job['job_id']]
                    with self.assertRaises(SceneError):
                        jobs.start('s',10,case={'source_scene_sha256':'0'*64})
                    with self.assertRaises(SceneError):
                        jobs.start('s',10,case={'threshold':float('nan')})
                    with self.assertRaises(SceneError):
                        jobs.start('s',10,case_path='some-file.json',case={})


if __name__ == '__main__':
    unittest.main()
