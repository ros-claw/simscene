"""Measure RG2 finger-joint response to drive commands in Isaac 6.0.1."""
import json,os,sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import numpy as np
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    from isaacsim.core.experimental.prims import Articulation, GeomPrim
    from isaacsim.core.simulation_manager import SimulationManager
    stage_utils.create_new_stage()
    stage_utils.add_reference_to_stage(usd_path=os.environ['SIMSCENE_ROBOT_USD'],path='/World/robot')
    robot=Articulation('/World/robot'); SimulationManager.setup_simulation(dt=1/60,device='cpu')
    app_utils.play();app.update()
    names=robot.dof_names; finger=names.index('finger_joint')
    from simscene.robotics.gripper import mimic_commands
    left=GeomPrim('/World/robot/left_inner_finger');right=GeomPrim('/World/robot/right_inner_finger')
    samples=[]
    for target in [-.5,0.0,.5,-.5]:
        commands=mimic_commands(os.environ['SIMSCENE_ROBOT_URDF'], 'finger_joint', target)
        values=np.array(list(commands.values()),dtype=np.float32)
        robot.set_dof_position_targets(values,dof_indices=[names.index(name) for name in commands])
        for _ in range(180): app.update()
        l=left.get_world_poses()[0].numpy()[0];r=right.get_world_poses()[0].numpy()[0]
        positions=robot.get_dof_positions().numpy().reshape(-1)
        samples.append({'target_rad':target,'actual_rad':float(positions[finger]),'left_world':l.tolist(),'right_world':r.tolist(),'finger_origin_separation_m':float(np.linalg.norm(l-r))})
    print('SIMSCENE_RESULT='+json.dumps({'commands':commands,'samples':samples,'scope':'finger origin motion only, not physical grip width or contact'}),flush=True)
    app_utils.stop()
except Exception:
    import traceback;traceback.print_exc();sys.stderr.flush()
finally: app.close()
