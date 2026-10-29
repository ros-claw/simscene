import unittest
import importlib.util
from unittest.mock import Mock
from simscene.worker.follow import PoseFollower
@unittest.skipUnless(importlib.util.find_spec('numpy'),'numpy required')
class FollowerSyncTest(unittest.TestCase):
    def test_workspace_guard_rejects_runaway_and_nonfinite_targets(self):
        bounds={'workspace_min':[3.8,-.7,.2],'workspace_max':[4.4,-.3,.6]}
        self.assertTrue(PoseFollower._inside_workspace([4,-.5,.32],bounds))
        self.assertFalse(PoseFollower._inside_workspace([4,-.5,-16000],bounds))
        self.assertFalse(PoseFollower._inside_workspace([float('nan'),0,0],{}))

    def test_runaway_target_does_not_reset_controller_or_command_motion(self):
        import numpy as np
        follower=PoseFollower.__new__(PoseFollower)
        follower.config={};follower.controller=Mock();follower.sequence_error=None;follower.sequence_index=0
        follower.sequence=[{'type':'track','object':'part','offset':[0,0,0],'steps':10,
                            'workspace_min':[3.8,-.7,.2],'workspace_max':[4.4,-.3,.6]}]
        follower._object_position=Mock(return_value=np.asarray([4,-.5,-16000]))
        follower._new_phase()
        self.assertIn('outside workspace',follower.sequence_error)
        follower.controller.reset.assert_not_called()
        follower.step(0)
        follower.controller.forward.assert_not_called()

    def test_move_phase_soft_cap_is_restored_on_next_phase(self):
        follower=PoseFollower.__new__(PoseFollower)
        config=Mock();follower.controller=Mock(get_rmp_flow_config=Mock(return_value=config))
        follower.config={'max_joint_speed':.5};follower.sequence=[{'type':'move','position':[0,0,0],'rmp_max_joint_speed':.3},{'type':'wait_object'}]
        follower.sequence_index=0;follower._state=Mock();follower._setpoint=Mock()
        follower._new_phase();follower.sequence_index=1;follower._new_phase()
        self.assertEqual(config.set_param.call_args_list[0].args,('joint_velocity_cap_rmp/max_velocity',.3))
        self.assertEqual(config.set_param.call_args_list[1].args,('joint_velocity_cap_rmp/max_velocity',.5))

    def test_static_base_is_not_reuploaded_but_motion_is_detected(self):
        import numpy as np
        class Array:
            def __init__(self,value):self.value=np.asarray(value,dtype=float)
            def numpy(self):return self.value
        follower=PoseFollower.__new__(PoseFollower);follower._last_root_pose=None
        pos=Array([[0,0,0]]);quat=Array([[1,0,0,0]])
        follower.robot=Mock(get_world_poses=Mock(return_value=(pos,quat)))
        world=Mock();follower.binding=Mock(get_world_interface=Mock(return_value=world))
        follower._sync();follower._sync()
        self.assertEqual(world.update_world_to_robot_root_transforms.call_count,1)
        pos.value[0,0]=.01;follower._sync()
        self.assertEqual(world.update_world_to_robot_root_transforms.call_count,2)
        self.assertEqual(follower.binding.synchronize_transforms.call_count,3)
