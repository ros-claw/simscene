"""Measure an experimental Kawa RMPflow motion without obstacle claims.

The generated XRDF lacks validated self-collision and this diagnostic must not
be used as a task controller. Only joint drives are commanded after start.
"""
import json, os, sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import numpy as np
    import warp as wp
    import omni.usd
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import isaacsim.robot_motion.experimental.motion_generation as mg
    from isaacsim.core.experimental.prims import Articulation, GeomPrim
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot_motion.cumotion import load_cumotion_robot, CumotionWorldInterface, RmpFlowController
    stage_utils.create_new_stage()
    stage_utils.add_reference_to_stage(usd_path=os.environ['SIMSCENE_ROBOT_USD'],path='/World/robot')
    robot=Articulation('/World/robot')
    robot.set_default_state(dof_positions=[0,-.2,-1.7,-1.507,0,0,0,0,0,0,0,0])
    SimulationManager.setup_simulation(dt=1/60, device='cpu')
    app_utils.play();app.update()
    robot.reset_to_default_state();app.update()
    model=load_cumotion_robot(directory=os.environ['SIMSCENE_XRDF_DIR'])
    binding=mg.WorldBinding(world_interface=CumotionWorldInterface(), obstacle_strategy=mg.ObstacleStrategy(), tracked_prims=[], tracked_collision_api=mg.TrackableApi.PHYSICS_COLLISION)
    binding.initialize()
    binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses())
    binding.synchronize_transforms()
    tool='gripper_center'
    controller=RmpFlowController(cumotion_robot=model,cumotion_world_interface=binding.get_world_interface(),robot_joint_space=robot.dof_names,robot_site_space=[tool],tool_frame=tool)
    controller.get_rmp_flow_config().set_param('cspace_target_rmp/metric_scalar',1.0)
    tcp=GeomPrim('/World/robot/gripper_center')
    position,orientation=tcp.get_world_poses()
    initial=position.numpy()[0].copy(); target=initial+np.array([0.1,0.0,0.05])
    def state():
        names=robot.dof_names
        return mg.RobotState(joints=mg.JointState.from_name(robot_joint_space=names,positions=(names,robot.get_dof_positions()),velocities=(names,robot.get_dof_velocities())))
    def setpoint():
        return mg.RobotState(sites=mg.SpatialState.from_name(spatial_space=[tool],positions=([tool],wp.array([target.tolist()],dtype=wp.float32)),orientations=([tool],orientation)))
    if not controller.reset(state(),setpoint(),t=0.0): raise RuntimeError('controller reset failed')
    samples=[]
    for step in range(600):
        binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses());binding.synchronize_transforms()
        desired=controller.forward(state(),setpoint(),step/60)
        if desired is not None and desired.joints.positions is not None:
            robot.set_dof_position_targets(positions=desired.joints.positions,dof_indices=desired.joints.position_indices)
        app.update()
        if step%30==0 or step==599:
            measured=tcp.get_world_poses()[0].numpy()[0]
            samples.append({'step':step,'tcp_position':measured.tolist(),'error_m':float(np.linalg.norm(measured-target))})
    print('SIMSCENE_RESULT='+json.dumps({'initial':initial.tolist(),'target':target.tolist(),'samples':samples,'scope':'isolated RMPflow diagnostic; no path/collision/grasp validation'}),flush=True)
    app_utils.stop()
except Exception:
    import traceback;traceback.print_exc();sys.stderr.flush()
finally:
    app.close()
