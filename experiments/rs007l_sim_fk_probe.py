"""Diagnostic: compare measured Isaac link transforms with URDF FK.

Joint states are directly set only for calibration, not for a task run.
"""
import json
import os
import sys
from pathlib import Path
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':int(os.getenv('SIMSCENE_GPU','0'))})
try:
    import numpy as np
    import omni.usd
    from pxr import UsdGeom
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    from isaacsim.core.experimental.prims import Articulation
    from isaacsim.core.simulation_manager import SimulationManager
    from simscene.robotics.urdf import link_transform
    from isaacsim.robot_motion.cumotion import load_cumotion_robot
    cumotion_robot = load_cumotion_robot(directory=os.environ["SIMSCENE_XRDF_DIR"])
    usd=os.environ['SIMSCENE_ROBOT_USD']; urdf=os.environ['SIMSCENE_ROBOT_URDF']
    stage_utils.create_new_stage()
    stage_utils.add_reference_to_stage(usd_path=usd,path='/World/robot')
    robot=Articulation('/World/robot')
    SimulationManager.setup_simulation(dt=1/60, device='cpu')
    app_utils.play(); app.update()
    names=robot.dof_names
    indices=[names.index('joint'+str(i)) for i in range(1,7)]
    stage=omni.usd.get_context().get_stage()
    samples=[]
    for requested in ([0,0,0,0,0,0], [.2,-.3,.25,-.2,.15,-.1]):
        robot.set_dof_positions(np.array([requested],dtype=np.float32),dof_indices=indices)
        robot.set_dof_position_targets(np.array([requested],dtype=np.float32),dof_indices=indices)
        for _ in range(3): app.update()
        actual=robot.get_dof_positions().numpy().reshape(-1)
        joint_pos={name:float(actual[names.index(name)]) for name in ['joint'+str(i) for i in range(1,7)]}
        cache=UsdGeom.XformCache()
        base=stage.GetPrimAtPath('/World/robot/base_link')
        target=stage.GetPrimAtPath('/World/robot/link6')
        usd=cache.GetLocalToWorldTransform(target)*cache.GetLocalToWorldTransform(base).GetInverse()
        fk=link_transform(urdf,'base_link','link6',joint_pos)
        translation_error=float(np.linalg.norm(np.array([usd[3][i] for i in range(3)])-np.array([fk[i][3] for i in range(3)])))
        rotation_error=float(np.linalg.norm(np.array([[usd[j][i] for j in range(3)] for i in range(3)])-np.array([row[:3] for row in fk[:3]])))
        tcp_prim=stage.GetPrimAtPath('/World/robot/gripper_center')
        tcp=cache.GetLocalToWorldTransform(tcp_prim)*cache.GetLocalToWorldTransform(base).GetInverse()
        q=np.array([joint_pos[j] for j in cumotion_robot.controlled_joint_names], dtype=np.float64)
        model_tcp=np.asarray(cumotion_robot.kinematics.position(q, 'gripper_center', 'base_link')).reshape(-1)
        tcp_error=float(np.linalg.norm(np.array([tcp[3][i] for i in range(3)])-model_tcp))
        samples.append({'requested':requested,'actual':joint_pos,'translation_error_m':translation_error,'rotation_matrix_frobenius_error':rotation_error,'cumotion_tcp_translation_error_m':tcp_error})
    print('SIMSCENE_RESULT='+json.dumps({'joint_names':names,'samples':samples, 'scope':'diagnostic joint teleport, not manipulation'},default=str),flush=True)
    app_utils.stop()
except Exception:
    import traceback
    traceback.print_exc(); sys.stderr.flush()
finally:
    app.close()
