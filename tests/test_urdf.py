import math
import tempfile
import unittest
from pathlib import Path
from simscene.robotics.urdf import link_transform

class UrdfTest(unittest.TestCase):
    def test_two_joint_chain(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'robot.urdf'
            p.write_text('<robot name="test"><joint name="turn" type="revolute"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/></joint><joint name="tip" type="fixed"><parent link="arm"/><child link="tip"/><origin xyz="1 0 0"/></joint></robot>')
            transform=link_transform(p,'base','tip',{'turn':math.pi/2})
            self.assertAlmostEqual(transform[0][3],0,places=6)
            self.assertAlmostEqual(transform[1][3],1,places=6)
            with self.assertRaises(ValueError): link_transform(p,'tip','base')
