"""Find complete cuMotion robot bundles in Isaac 6.0 and 6.2 layouts."""
import tempfile
import unittest
from pathlib import Path
from simscene.robotics.config_paths import cumotion_robot_config

class RobotConfigPathsTest(unittest.TestCase):
    def test_both_layouts_and_incomplete_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ext=root/'exts/isaacsim.robot_motion.cumotion'
            old=ext/'robot_configurations/franka'
            new=ext/'pip_prebundle/isaacsim/robot_motion/cumotion/robot_configurations/franka'
            new.mkdir(parents=True);old.mkdir(parents=True)
            for name in ('robot.urdf','robot.xrdf','rmp_flow.yaml'):(new/name).write_text(name)
            (old/'robot.urdf').write_text('partial')
            self.assertEqual(cumotion_robot_config(root,'franka'),new)
            for name in ('robot.xrdf','rmp_flow.yaml'):(old/name).write_text(name)
            self.assertEqual(cumotion_robot_config(root,'franka'),old)
            with self.assertRaises(FileNotFoundError):cumotion_robot_config(root,'ur10')
            with self.assertRaises(ValueError):cumotion_robot_config(root,'../franka')

if __name__=='__main__':unittest.main()
