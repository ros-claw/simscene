"""Check cuMotion can parse the generated experimental robot model."""
import json,os,sys
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    from isaacsim.robot_motion.cumotion import load_cumotion_robot
    robot=load_cumotion_robot(directory=os.environ['SIMSCENE_XRDF_DIR'])
    print('SIMSCENE_RESULT='+json.dumps({'controlled_joints':robot.controlled_joint_names,'tool_frames':list(robot.robot_description.tool_frame_names()), 'kinematics_methods':[x for x in dir(robot.kinematics) if not x.startswith('_')], 'pose_doc':robot.kinematics.pose.__doc__, 'position_doc':robot.kinematics.position.__doc__, 'status':'loaded_only'}),flush=True)
except Exception:
    import traceback
    traceback.print_exc(); sys.stderr.flush()
finally:
    app.close()
