import math,tempfile,unittest
from pathlib import Path
from simscene.robotics.ik import solve_ik

class IKTest(unittest.TestCase):
    def test_candidate_and_unreachable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.urdf'
            p.write_text('<robot name="r"><joint name="j" type="revolute"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/><limit lower="-3.14" upper="3.14"/></joint><joint name="tip" type="fixed"><parent link="arm"/><child link="tip"/><origin xyz="1 0 0"/></joint></robot>')
            r=solve_ik(p,'base','tip',['j'],[0,1,0],seed=[1.0]);self.assertTrue(r['success']);self.assertAlmostEqual(r['joint_positions']['j'],math.pi/2,places=3)
            self.assertFalse(solve_ik(p,'base','tip',['j'],[3,0,0])['success'])
            self.assertEqual(r['collision_check'],'not performed')
