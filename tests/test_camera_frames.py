"""Warm-up waits are bounded and never fabricate camera frames."""
import unittest
from simscene.worker.camera_frames import MAX_WARMUP_UPDATES, read_rgb, paused_render_barrier

class Frame:
    def __init__(self,shape):self.shape=shape
class Sensor:
    def __init__(self,frames):self.frames=list(frames);self.calls=0
    def get_data(self,name,tiled=False):
        assert name=='rgb' and tiled
        self.calls+=1
        return self.frames.pop(0) if self.frames else None,{}
class CameraFramesTest(unittest.TestCase):
    def barrier(self, clock, pump=None):
        return paused_render_barrier(read_state=lambda:(clock['step'],clock['time']),
            is_playing=lambda:clock['playing'],pause=lambda:clock.update(playing=False),
            play=lambda:clock.update(playing=True),pump=pump or (lambda:None))

    def test_nonempty_stale_rgb_is_flushed_without_physics_or_duplicate_detection(self):
        clock={'playing':True,'step':52,'time':52/60}
        old=Frame((540,960,3));current=Frame((540,960,3))
        sensor=Sensor([old]);pipeline=[old,old,current]
        def pump():
            self.assertFalse(clock['playing'])
            pipeline.pop(0);sensor.frames=[pipeline[0]]
        with self.barrier(clock,pump) as receipt:
            self.assertIs(read_rgb(sensor),current)
            self.assertEqual(receipt['absolute_physics_step'],52)
            self.assertTrue(receipt['physics_unchanged'])
        self.assertTrue(clock['playing'])
        self.assertEqual((clock['step'],clock['time']),(52,52/60))

    def test_render_pump_cannot_advance_physics(self):
        clock={'playing':True,'step':52,'time':52/60}
        def pump():clock['step']+=1
        with self.assertRaisesRegex(RuntimeError,'physics advanced'):
            with self.barrier(clock,pump):self.fail('invalid frame was admitted')
        self.assertTrue(clock['playing'])

    def test_readback_cannot_advance_physics_and_original_pause_is_preserved(self):
        clock={'playing':False,'step':52,'time':52/60}
        with self.assertRaisesRegex(RuntimeError,'batch readback'):
            with self.barrier(clock):clock['time']+=1/60
        self.assertFalse(clock['playing'])

    def test_pump_failure_restores_timeline(self):
        clock={'playing':True,'step':52,'time':52/60}
        def pump():raise RuntimeError('renderer unavailable')
        with self.assertRaisesRegex(RuntimeError,'renderer unavailable'):
            with self.barrier(clock,pump):self.fail('failed renderer was admitted')
        self.assertTrue(clock['playing'])

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
