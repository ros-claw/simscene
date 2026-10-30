import copy,json,tempfile,unittest
from pathlib import Path
from simscene.presentation import plan,events
from simscene.scene import SceneError
class PresentationTest(unittest.TestCase):
 def test_subject_framing_independent_of_scene_and_robot_names(self):
  scene={'revision':3,'objects':{'widget':{'kind':'box','position':[4,2,1],'size':[2,.5,1]}}}
  original=copy.deepcopy(scene);r=plan(scene,['widget'],[{'id':'inspection','min':[3.8,1.8,.8],'max':[4.2,2.2,1.2],'action':'fall'}])
  self.assertEqual(scene,original);self.assertEqual(r['base_revision'],3);self.assertEqual(len(r['cameras']),2)
  self.assertEqual(r['cameras'][0]['target_m'],[4,2,1]);self.assertEqual(r['cameras'][1]['action'],'fall')
 def test_semantic_event_kind_is_from_frozen_sequence(self):
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);(root/'spec.json').write_text(json.dumps({'objects':{'arbitrary_owner':{'pose_follower':{'sequence':[{'type':'move','object':'piece'},{'type':'gripper','state':'open'}]}}}}))
   (root/'result.json').write_text(json.dumps({'followers':{'arbitrary_owner':{'transitions':[{'index':0,'physics_step':10},{'index':1,'physics_step':60}]}},'spawn_events':[]}))
   r=events(root);self.assertEqual(r[0]['kind'],'move');self.assertEqual(r[0]['object_id'],'piece');self.assertEqual(r[1]['gripper_state'],'open')
 def test_source_capture_manifest_mismatch_rejected(self):
  import numpy as np
  from simscene.worker.video import VideoRecorder
  from simscene.video_tools import inspect
  with tempfile.TemporaryDirectory() as root:
   r=VideoRecorder(Path(root)/'test.mp4',30,160,90)
   for _ in range(3):r.write(np.full((90,160,3),80,np.uint8))
   record=r.close();path=Path(record['frame_manifest']);rows=[json.loads(l) for l in path.read_text().splitlines()];rows[1]['physics_step']=6
   path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
   self.assertFalse(inspect(record['path'],record=record)['simulation_timeline']['passed'])
