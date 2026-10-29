"""Static-camera scenes need a real timeline for Isaac 6.2 sensors."""
import tempfile
import unittest
from pathlib import Path
from pxr import Usd
from simscene.scene import SceneStore
from simscene.usd_export import export_scene

class StageTimelineTest(unittest.TestCase):
    def test_static_scene_has_full_physics_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SceneStore(root/'state');store.open('s')
            store.apply('s',0,'camera',[{'op':'add','id':'camera','object':{'kind':'camera'}}])
            path=root/'scene.usda';export_scene(store.get('s'),path);stage=Usd.Stage.Open(str(path))
            self.assertTrue(stage.HasAuthoredTimeCodeRange())
            self.assertEqual(stage.GetStartTimeCode(),0)
            self.assertGreaterEqual(stage.GetEndTimeCode(),72000)
            self.assertEqual(stage.GetFramesPerSecond(),60)
            self.assertEqual(stage.GetTimeCodesPerSecond(),60)

if __name__=='__main__':unittest.main()
