"""Compare cuMotion Franka fingertip FK with simulated finger + fixed offset."""
import json,os,sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import numpy as np
    import omni.usd
    from pxr import Gf,UsdGeom
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    from isaacsim.core.experimental.prims import Articulation
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot_motion.cumotion import load_cumotion_robot
    stage_utils.create_new_stage();stage_utils.add_reference_to_stage(usd_path=os.environ['SIMSCENE_ROBOT_USD'],path='/World/robot')
    robot=Articulation('/World/robot');SimulationManager.setup_simulation(dt=1/60,device='cpu')
    app_utils.play();app.update()
    names=robot.dof_names; arm=['panda_joint'+str(i) for i in range(1,8)]
    indices=[names.index(n) for n in arm+['panda_finger_joint1','panda_finger_joint2']]
    model=load_cumotion_robot(directory=os.environ['SIMSCENE_XRDF_DIR']);stage=omni.usd.get_context().get_stage()
    samples=[]
    for q in ([0,-.4,0,-1.8,0,1.4,.7],[.2,-.7,.3,-2,.2,1.8,.5]):
        q_full=np.array([q+[.025,.025]],dtype=np.float32)
        robot.set_dof_positions(q_full,dof_indices=indices);robot.set_dof_position_targets(q_full,dof_indices=indices)
        for _ in range(3):app.update()
        actual=robot.get_dof_positions().numpy().reshape(-1); coords={n:float(actual[names.index(n)]) for n in arm}
        cache=UsdGeom.XformCache();base=stage.GetPrimAtPath('/World/robot/panda_link0');finger=stage.GetPrimAtPath('/World/robot/panda_hand')
        offset=Gf.Matrix4d(1);offset.SetTranslate(Gf.Vec3d(0,0,.1034))
        world=offset*cache.GetLocalToWorldTransform(finger)
        sim=world*cache.GetLocalToWorldTransform(base).GetInverse()
        model_xyz=np.asarray(model.kinematics.position(np.array([coords[n] for n in model.controlled_joint_names],dtype=float),'simscene_tcp','panda_link0')).reshape(-1)
        sim_xyz=np.array([sim[3][i] for i in range(3)])
        samples.append({'actual':coords,'finger_actual_rad_m':[float(actual[names.index(n)]) for n in ['panda_finger_joint1','panda_finger_joint2']],'tcp_world':[float(world[3][i]) for i in range(3)],'tcp_position_error_m':float(np.linalg.norm(sim_xyz-model_xyz))})
    print('SIMSCENE_RESULT='+json.dumps({'samples':samples,'scope':'direct joint setting for calibration; centred TCP position only; no manipulation'},default=str),flush=True)
    app_utils.stop()
except Exception:
    import traceback;traceback.print_exc();sys.stderr.flush()
finally:app.close()
