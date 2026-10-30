import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from simscene.worker.video import VideoRecorder
from simscene.video_tools import export,inspect

class VideoRetimeTest(unittest.TestCase):
 def test_slow_segments_preserve_last_hold_and_exact_cut_audio_clock(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);run=root/'run';run.mkdir();recorder=VideoRecorder(run/'native.mp4',30,160,90)
   for i in range(6):recorder.write(np.full((90,160,3),60+i*10,np.uint8))
   record=recorder.close();(run/'result.json').write_text(json.dumps({'videos':{'cam':record}}))
   for name in ('run-lock.json','evidence-lock.json'):(run/name).write_text('{}')
   segment={'run_directory':str(run),'camera':'cam','start_sim_time_s':1/30,'end_sim_time_s':7/30,'speed':.5}
   # Real codec/clock test; lock authenticity has its own independent tests.
   with patch('simscene.run_integrity.verify',return_value={'passed':True}),patch('simscene.evidence_integrity.verify',return_value={'passed':True}):
    result=export([segment,segment],root/'edited.mp4',output_resolution=[160,90]);report=inspect(result['path'])
   self.assertEqual(report['decoded_frame_count'],24)
   self.assertEqual([s['output_frames'] for s in result['segments']],[12,12])
   self.assertAlmostEqual(result['segments'][1]['output_start_s'],.4)
   self.assertAlmostEqual(report['duration_s'],result['segments'][-1]['output_end_s'])
   self.assertTrue(report['simulation_timeline']['passed'])
   for speed in (.1,.5,1,1.3,2,8):
    with self.subTest(speed=speed),patch('simscene.run_integrity.verify',return_value={'passed':True}),patch('simscene.evidence_integrity.verify',return_value={'passed':True}):
     changed={**segment,'speed':speed}
     edited=export([changed],root/f'speed-{speed}.mp4',output_resolution=[160,90])
     checked=inspect(edited['path'])
     self.assertEqual(checked['decoded_frame_count'],max(1,round(6/speed)))
     self.assertTrue(checked['simulation_timeline']['passed'])
