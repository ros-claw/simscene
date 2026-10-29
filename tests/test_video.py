import shutil
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from simscene.scene import SceneStore, SceneError

class VideoTest(unittest.TestCase):
    def test_recording_rate_requires_a_camera_and_regular_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            scene=SceneStore(directory);scene.open('scene')
            with self.assertRaises(SceneError):
                scene.apply('scene',0,'bad',[{'op':'add','id':'box','object':{'kind':'box','record_fps':10}}])
            with self.assertRaises(SceneError):
                scene.apply('scene',0,'bad2',[{'op':'add','id':'cam','object':{'kind':'camera','record_fps':7}}])
            scene.apply('scene',0,'ok',[{'op':'add','id':'cam','object':{'kind':'camera','record_fps':10}}])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and importlib.util.find_spec('numpy'),'ffmpeg and numpy required')
    def test_encoded_video_has_real_frames_and_timebase(self):
        import numpy as np
        from simscene.worker.video import VideoRecorder
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.mp4'
            recorder=VideoRecorder(path,10,width=16,height=16)
            for value in range(10):recorder.write(np.full((16,16,3),value*20,dtype=np.uint8))
            meta=recorder.close()
            self.assertEqual(meta['duration_s'],1.)
            duration=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],text=True)
            self.assertAlmostEqual(float(duration),1.,places=2)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and importlib.util.find_spec('numpy'),'ffmpeg and numpy required')
    def test_fragmented_video_keeps_completed_fragments_after_abort(self):
        import numpy as np
        import time
        from simscene.worker.video import VideoRecorder
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'interrupted.mp4';recorder=VideoRecorder(path,2,width=16,height=16)
            for value in range(30):recorder.write(np.full((16,16,3),value*5,dtype=np.uint8))
            recorder.process.stdin.flush()
            for _ in range(50):
                if path.exists() and path.stat().st_size>1000:break
                time.sleep(.02)
            recorder.abort()
            result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertGreater(float(result.stdout),0)
