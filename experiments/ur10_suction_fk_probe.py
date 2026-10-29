"""Compare experimental short-suction TCP model to Isaac articulation frames."""
import json,os,sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import numpy as np
    import omni.usd
    from pxr import Gf,UsdGeom,UsdPhysics
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    from isaacsim.core.experimental.prims import Articulation
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot_motion.cumotion import load_cumotion_robot
    stage_utils.create_new_stage();stage_utils.add_reference_to_stage(usd_path=os.environ['SIMSCENE_ROBOT_USD'],path='/World/robot',variants=[('Gripper','Short_Suction')])
    robot=Articulation('/World/robot');SimulationManager.setup_simulation(dt=1/60,device='cpu');app_utils.play();app.update()
    names=robot.dof_names;model=load_cumotion_robot(directory=os.environ['SIMSCENE_XRDF_DIR']);indices=[names.index(n) for n in model.controlled_joint_names]
    stage=omni.usd.get_context().get_stage();joint=UsdPhysics.Joint(stage.GetPrimAtPath('/World/robot/ee_link/suction_cup/Suction_Joint'))
    local_pos=joint.GetLocalPos0Attr().Get();local_rot=joint.GetLocalRot0Attr().Get()
    offset=Gf.Matrix4d(1);offset.SetRotate(Gf.Rotation(Gf.Quatd(local_rot)));offset.SetTranslateOnly(Gf.Vec3d(local_pos))
    samples=[]
    for q in ([0,-1.0,1.0,-1.0,-1.0,0],[.3,-1.2,1.3,-.8,-1.2,.2]):
        values=np.array([q],dtype=np.float32);robot.set_dof_positions(values,dof_indices=indices);robot.set_dof_position_targets(values,dof_indices=indices)
        for _ in range(3):app.update()
        actual=robot.get_dof_positions().numpy().reshape(-1);coords=np.array([float(actual[names.index(n)]) for n in model.controlled_joint_names])
        cache=UsdGeom.XformCache();base=stage.GetPrimAtPath('/World/robot/base_link');ee=stage.GetPrimAtPath('/World/robot/ee_link')
        world=offset*cache.GetLocalToWorldTransform(ee);relative=world*cache.GetLocalToWorldTransform(base).GetInverse()
        expected=np.asarray(model.kinematics.position(coords,'simscene_suction_tcp','base_link')).reshape(-1)
        orientation_obj=model.kinematics.orientation(coords,'simscene_suction_tcp','base_link')
        model_orientation=np.asarray(orientation_obj.matrix())
        observed=np.array([[relative[j][i] for j in range(3)] for i in range(3)])
        rotation_error=float(np.linalg.norm(observed-model_orientation)) if model_orientation.shape==(3,3) else None
        samples.append({'actual':coords.tolist(),'tcp_world':list(world.ExtractTranslation()),'tcp_position_error_m':float(np.linalg.norm(np.asarray(relative.ExtractTranslation())-expected)),'orientation_shape':list(model_orientation.shape),'orientation_type':str(type(orientation_obj)),'orientation_methods':[x for x in dir(orientation_obj) if not x.startswith('_')],'rotation_matrix_error':rotation_error})
    print('SIMSCENE_RESULT='+json.dumps({'samples':samples,'scope':'two diagnostic joint settings; suction not tested'},default=str),flush=True);app_utils.stop()
except Exception:
    import traceback;traceback.print_exc();sys.stderr.flush()
finally:app.close()
