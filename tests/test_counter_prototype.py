import unittest
from pxr import Usd,UsdGeom
from experiments.counter_display import create,set_value


class CounterPrototypeTest(unittest.TestCase):
    def test_value_controls_visible_segments_without_inventing_a_count(self):
        stage=Usd.Stage.CreateInMemory();create(stage,'/World/count',digits=3)
        def visible(digit):
            return {name for name in 'abcdefg' if UsdGeom.Imageable(stage.GetPrimAtPath(f'/World/count/digit_{digit}/{name}')).GetVisibilityAttr().Get()!='invisible'}
        self.assertEqual(visible(0),set());self.assertEqual(visible(1),set());self.assertEqual(visible(2),set('abcdef'))
        set_value(stage,'/World/count',3,12)
        self.assertEqual(visible(0),set());self.assertEqual(visible(1),set('bc'));self.assertEqual(visible(2),set('abdeg'))
        with self.assertRaises(ValueError):set_value(stage,'/World/count',3,1000)
        self.assertEqual(visible(2),set('abdeg'))
