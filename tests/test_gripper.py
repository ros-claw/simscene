import tempfile
import unittest
from pathlib import Path
from simscene.robotics.gripper import mimic_commands

class MimicTests(unittest.TestCase):
    def test_coupling_and_limits(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'robot.urdf'
            path.write_text('<robot name="r"><joint name="drive" type="revolute"><limit lower="-1" upper="1"/></joint><joint name="other" type="revolute"><limit lower="-1" upper="1"/><mimic joint="drive" multiplier="-1" offset="0.1"/></joint><joint name="chain" type="revolute"><mimic joint="other" multiplier="2"/></joint></robot>')
            values=mimic_commands(path,'drive',.2)
            self.assertAlmostEqual(values['other'],-.1)
            self.assertAlmostEqual(values['chain'],-.2)
            with self.assertRaises(ValueError): mimic_commands(path,'drive',2)

    def test_independent_coupling_respects_limits(self):
        from simscene.robotics.gripper import coupled_commands
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.urdf'
            p.write_text('<robot name="r"><joint name="left" type="prismatic"><limit lower="0" upper="0.04"/></joint><joint name="right" type="prismatic"><limit lower="0" upper="0.04"/></joint></robot>')
            self.assertEqual(coupled_commands(p,'left',.03,{'right':1}),{'left':.03,'right':.03})
            with self.assertRaises(ValueError): coupled_commands(p,'left',.03,{'right':2})
