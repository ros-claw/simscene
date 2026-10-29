"""Warm-up waits are bounded and never fabricate camera frames."""
import unittest
from simscene.worker.camera_frames import MAX_WARMUP_UPDATES, read_rgb

class Frame:
    def __init__(self,shape):self.shape=shape
class Sensor:
    def __init__(self,frames):self.frames=list(frames);self.calls=0
    def get_data(self,name,tiled=False):
        assert name=='rgb' and tiled
        self.calls+=1
        return self.frames.pop(0) if self.frames else None,{}
class CameraFramesTest(unittest.TestCase):
    def test_pumps_until_nonempty_frame_or_limit(self):
        ready=Frame((480,640,3));sensor=Sensor([None,Frame((0,)),ready]);ticks=[]
        self.assertIs(read_rgb(sensor,lambda:ticks.append(1),3),ready)
        self.assertEqual(len(ticks),2)
        sensor=Sensor([None,None,None]);ticks=[]
        self.assertIsNone(read_rgb(sensor,lambda:ticks.append(1),2))
        self.assertEqual(len(ticks),2)
        with self.assertRaises(ValueError):read_rgb(Sensor([None]),max_updates=1)

    def test_late_renderer_frame_is_not_dropped(self):
        ready=Frame((480,640,3));sensor=Sensor([None]*121+[ready]);ticks=[]
        self.assertIs(read_rgb(sensor,lambda:ticks.append(1),MAX_WARMUP_UPDATES),ready)
        self.assertEqual(len(ticks),121)

if __name__=='__main__':unittest.main()
