"""Contact-based static grip, transfer and release diagnostic; no task-time teleportation."""
import json,os,sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import numpy as np
    import warp as wp
    import omni.usd
    import omni.physx
    from pxr import PhysxSchema, PhysicsSchemaTools
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import isaacsim.robot_motion.experimental.motion_generation as mg
    from isaacsim.core.experimental.prims import Articulation,GeomPrim,RigidPrim
    from isaacsim.core.experimental.objects import Cube
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot_motion.cumotion import load_cumotion_robot,CumotionWorldInterface,RmpFlowController
    from simscene.robotics.gripper import mimic_commands
    stage_utils.create_new_stage()
    stage_utils.add_reference_to_stage(usd_path=os.environ['SIMSCENE_ROBOT_USD'],path='/World/robot')
    robot=Articulation('/World/robot'); names=robot.dof_names
    values=np.zeros(len(names),dtype=np.float32)
    start_q=[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0.0]
    for i,v in enumerate(start_q,1): values[names.index('joint'+str(i))]=v
    for n,v in mimic_commands(os.environ['SIMSCENE_ROBOT_URDF'],'finger_joint',-.5).items(): values[names.index(n)]=v
    robot.set_default_state(dof_positions=values.tolist())
    table=Cube('/World/table',positions=[0,-.5,.28],scales=[.25,.25,.04],sizes=1)
    GeomPrim('/World/table',apply_collision_apis=True)
    # Separate destination bin. All geometry is created before play.
    bin_parts=[('floor',[.28,-.5,.28],[.16,.16,.04]),
               ('wall_l',[.20,-.5,.37],[.02,.18,.14]),
               ('wall_r',[.36,-.5,.37],[.02,.18,.14]),
               ('wall_f',[.28,-.58,.37],[.14,.02,.14]),
               ('wall_b',[.28,-.42,.37],[.14,.02,.14])]
    for part,pos,scale in bin_parts:
        path='/World/bin_'+part
        Cube(path,positions=pos,scales=scale,sizes=1)
        GeomPrim(path,apply_collision_apis=True)
    block=Cube('/World/block',positions=[0,-.5,.32],scales=[.04,.04,.04],sizes=1)
    GeomPrim('/World/block',apply_collision_apis=True);RigidPrim('/World/block')
    stage=omni.usd.get_context().get_stage()
    PhysxSchema.PhysxContactReportAPI.Apply(stage.GetPrimAtPath('/World/block')).CreateThresholdAttr().Set(0)
    contact_counts={}
    contact_last_step={}
    current_step=[0]
    current_phase=['init']
    def contacts(headers,data):
        for header in headers:
            actors=[str(PhysicsSchemaTools.intToSdfPath(header.actor0)),str(PhysicsSchemaTools.intToSdfPath(header.actor1))]
            if '/World/block' not in actors: continue
            other=actors[1] if actors[0]=='/World/block' else actors[0]
            key=current_phase[0]+':'+other
            contact_counts[key]=contact_counts.get(key,0)+1
            contact_last_step[key]=current_step[0]
    contact_subscription=omni.physx.get_physx_simulation_interface().subscribe_contact_report_events(contacts)
    SimulationManager.setup_simulation(dt=1/60,device='cpu')
    app_utils.play();app.update();robot.reset_to_default_state();app.update()
    cube=GeomPrim('/World/block');tcp=GeomPrim('/World/robot/gripper_center')
    left_finger=GeomPrim('/World/robot/left_inner_finger');right_finger=GeomPrim('/World/robot/right_inner_finger')
    def set_grip(v):
        cmds=mimic_commands(os.environ['SIMSCENE_ROBOT_URDF'],'finger_joint',v)
        robot.set_dof_position_targets(np.array(list(cmds.values()),dtype=np.float32),dof_indices=[names.index(n) for n in cmds])
    grip_target = -.5 if os.getenv('SIMSCENE_DISABLE_GRIP') == '1' else .5
    samples=[]
    current_phase[0]='close'
    for step in range(240):
        current_step[0]=step
        set_grip(grip_target);app.update()
        if step%30==0: samples.append({'phase':'close','step':step,'cube':cube.get_world_poses()[0].numpy()[0].tolist()})
    model=load_cumotion_robot(directory=os.environ['SIMSCENE_XRDF_DIR'])
    binding=mg.WorldBinding(world_interface=CumotionWorldInterface(),obstacle_strategy=mg.ObstacleStrategy(),tracked_prims=[],tracked_collision_api=mg.TrackableApi.PHYSICS_COLLISION)
    binding.initialize();binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses());binding.synchronize_transforms()
    tool='gripper_center';controller=RmpFlowController(cumotion_robot=model,cumotion_world_interface=binding.get_world_interface(),robot_joint_space=names,robot_site_space=[tool],tool_frame=tool)
    controller.get_rmp_flow_config().set_param('cspace_target_rmp/metric_scalar',1.)
    pos,orientation=tcp.get_world_poses();target=pos.numpy()[0]+np.array([.0,.0,.15])
    def state(): return mg.RobotState(joints=mg.JointState.from_name(robot_joint_space=names,positions=(names,robot.get_dof_positions()),velocities=(names,robot.get_dof_velocities())))
    def setpoint(): return mg.RobotState(sites=mg.SpatialState.from_name(spatial_space=[tool],positions=([tool],wp.array([target.tolist()],dtype=wp.float32)),orientations=([tool],orientation)))
    if not controller.reset(state(),setpoint(),t=0):raise RuntimeError('controller reset failed')
    current_phase[0]='lift'
    for step in range(360):
        binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses());binding.synchronize_transforms()
        desired=controller.forward(state(),setpoint(),step/60)
        if desired is not None and desired.joints.positions is not None:
            robot.set_dof_position_targets(positions=desired.joints.positions,dof_indices=desired.joints.position_indices)
        current_step[0]=step
        set_grip(grip_target);app.update()
        if step%30==0: samples.append({'phase':'lift','step':step,'cube':cube.get_world_poses()[0].numpy()[0].tolist(),'tcp':tcp.get_world_poses()[0].numpy()[0].tolist()})
    for phase, new_target in [('transfer',target+np.array([.28,0,0])), ('lower',target+np.array([.28,0,-.15]))]:
        current_phase[0]=phase
        target=new_target
        if not controller.reset(state(),setpoint(),t=0):raise RuntimeError('controller reset failed: '+phase)
        for step in range(300):
            binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses());binding.synchronize_transforms()
            desired=controller.forward(state(),setpoint(),step/60)
            if desired is not None and desired.joints.positions is not None:
                robot.set_dof_position_targets(positions=desired.joints.positions,dof_indices=desired.joints.position_indices)
            current_step[0]=step
            set_grip(grip_target);app.update()
            if step%30==0: samples.append({'phase':phase,'step':step,'cube':cube.get_world_poses()[0].numpy()[0].tolist(),'tcp':tcp.get_world_poses()[0].numpy()[0].tolist()})
    current_phase[0]='release'
    for step in range(180):
        current_step[0]=step
        set_grip(-.5);app.update()
        if step%30==0: samples.append({'phase':'release','step':step,'cube':cube.get_world_poses()[0].numpy()[0].tolist(),'finger_joint_rad':float(robot.get_dof_positions().numpy().reshape(-1)[names.index('finger_joint')])})
    current_phase[0]='retract'
    target=target+np.array([0,0,.15])
    if not controller.reset(state(),setpoint(),t=0):raise RuntimeError('controller reset failed: retract')
    for step in range(240):
        current_step[0]=step
        binding.get_world_interface().update_world_to_robot_root_transforms(robot.get_world_poses());binding.synchronize_transforms()
        desired=controller.forward(state(),setpoint(),step/60)
        if desired is not None and desired.joints.positions is not None:
            robot.set_dof_position_targets(positions=desired.joints.positions,dof_indices=desired.joints.position_indices)
        set_grip(-.5);app.update()
        if step%30==0: samples.append({'phase':'retract','step':step,'cube':cube.get_world_poses()[0].numpy()[0].tolist(),'tcp':tcp.get_world_poses()[0].numpy()[0].tolist(),'left_finger':left_finger.get_world_poses()[0].numpy()[0].tolist(),'right_finger':right_finger.get_world_poses()[0].numpy()[0].tolist(),'finger_joint_rad':float(robot.get_dof_positions().numpy().reshape(-1)[names.index('finger_joint')])})
    print('SIMSCENE_RESULT='+json.dumps({'samples':samples,'contact_counts':contact_counts,'contact_last_step':contact_last_step,'target_tcp':target.tolist(),'grip_target':grip_target,'scope':'experimental static pick/place; no full robot collision validation'}),flush=True)
    app_utils.stop()
except Exception:
    import traceback;traceback.print_exc();sys.stderr.flush()
finally:app.close()
