"""Opt-in Isaac validation of a time-sampled moving camera."""
import json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.evidence_integrity import verify

@unittest.skipUnless(os.getenv('SIMSCENE_ISAAC_PYTHON'),'requires Isaac Sim')
class OrbitCameraTest(unittest.TestCase):
    def test_camera_moves_during_physics_and_recording_is_sealed(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'SIMSCENE_HOME':root}):
            store=SceneStore();store.open('orbit')
            store.apply('orbit',0,'setup',[
                {'op':'add','id':'cube','object':{'kind':'box','size':[.4,.4,.4],'position':[0,0,.2],'color':[.8,.1,.1]}},
                {'op':'add','id':'light','object':{'kind':'light','intensity':1500}},
                {'op':'add','id':'view','object':{'kind':'camera','record_fps':6,'camera_orbit':{'center':[0,0,.2],'radius_m':2,'height_m':1,'duration_s':4}}}])
            job=start('orbit',120,17)
            for _ in range(180):
                state=status(job['job_id'])
                if state['state']!='running':break
                time.sleep(1)
            self.assertEqual(state['state'],'completed',str(state))
            directory=Path(root)/'runs'/job['run_id'];run=json.loads((directory/'result.json').read_text())
            poses=[s['cameras']['view']['position'] for s in run['samples'] if 'view' in s.get('cameras',{})]
            self.assertGreater(len(poses),2);self.assertGreater(poses[0][0]-poses[-1][0],3.0)
            self.assertEqual(run['videos']['view']['frames'],12)
            self.assertTrue(verify(directory)['passed'])
