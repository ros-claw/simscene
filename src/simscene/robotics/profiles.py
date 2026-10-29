"""Generate experimental robot motion profiles for individually acquired assets."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from ..settings import get

MODELS = {
    'kawasaki_rs007l_rg2': 'prepare_rs007l_profile.py',
    'franka_panda': 'prepare_franka_profile.py',
    'ur10_short_suction': 'prepare_ur10_profile.py',
}


def prepare(model, asset_path):
    if model not in MODELS:
        raise ValueError('unsupported profile model; choose one of: ' + ', '.join(MODELS))
    asset = Path(asset_path).expanduser().resolve()
    if not asset.is_file() or asset.suffix.lower() not in ('.usd', '.usda', '.usdc'):
        raise ValueError('asset_path must be an acquired local USD file')
    runtime = get('isaac_python')
    if not runtime or not Path(runtime).expanduser().is_file():
        raise ValueError('configure isaac_python on the simulation host before preparing a profile')
    root = Path(runtime).expanduser().resolve().parent
    home = Path(get('data_directory', '~/.local/share/simscene')).expanduser().resolve()
    profiles = home / 'profiles'
    profiles.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.profile-', dir=profiles))
    destination = profiles / uuid.uuid4().hex
    try:
        script = Path(__file__).parent / 'profile_scripts' / MODELS[model]
        command = [sys.executable, str(script), '--isaac-root', str(root), '--asset-usd', str(asset), '--output', str(temporary)]
        env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[2])
        env['PYTHONPATH'] = os.pathsep.join(filter(None, (package_root, env.get('PYTHONPATH'))))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120, env=env)
        if completed.returncode:
            detail = completed.stderr.strip()[-4000:] or completed.stdout.strip()[-4000:]
            raise ValueError('profile generation failed; verify model, asset dependencies and Python USD/IK packages: ' + detail)
        metadata = json.loads((temporary / 'profile.json').read_text())
        metadata['model'] = model
        (temporary / 'profile.json').write_text(json.dumps(metadata, indent=2) + '\n')
        for filename in ('robot.urdf', 'robot.xrdf', 'rmp_flow.yaml'):
            if not (temporary / filename).is_file():
                raise ValueError('profile generator did not produce ' + filename)
        os.replace(temporary, destination)
        return {'model': model, 'model_directory': str(destination), **metadata}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def suggest(model_directory, base_position, orientation_wxyz):
    """Suggest a starting pose and control configuration, not a certified plan."""
    import math
    directory = Path(model_directory).expanduser().resolve()
    metadata = json.loads((directory / 'profile.json').read_text())
    model = metadata.get('model')
    if model not in MODELS:
        raise ValueError('profile does not identify a supported generated model')
    if (not isinstance(base_position, list) or len(base_position) != 3 or
            not isinstance(orientation_wxyz, list) or len(orientation_wxyz) != 4 or
            any(type(x) not in (float, int) or not math.isfinite(x) for x in base_position + orientation_wxyz)):
        raise ValueError('base position and orientation must be finite vectors of length 3 and 4')
    norm = math.sqrt(sum(x*x for x in orientation_wxyz))
    if abs(norm - 1) > 1e-4:
        raise ValueError('orientation must be a normalized wxyz quaternion')
    w,x,y,z = orientation_wxyz
    local = [-.05,-.5,.31] if model == 'kawasaki_rs007l_rg2' else [.45,0,.34 if model == 'franka_panda' else .345]
    # Rotate a base-frame target into the world frame.
    tx=2*(y*local[2]-z*local[1]);ty=2*(z*local[0]-x*local[2]);tz=2*(x*local[1]-y*local[0])
    rotated=[local[0]+w*tx+y*tz-z*ty,local[1]+w*ty+z*tx-x*tz,local[2]+w*tz+x*ty-y*tx]
    target=[base_position[i]+rotated[i] for i in range(3)]
    config={'experimental':True,'model_directory':str(directory),'tool_frame':metadata['tool_frame'],
            'tcp_prim':metadata['tcp_prim'],'target_position':target,'monitor_collisions':True}
    if model == 'kawasaki_rs007l_rg2':
        from .gripper import mimic_commands
        joints=dict(zip(['joint1','joint2','joint3','joint4','joint5','joint6'],[1.5707829843,.1642120063,-1.8665936187,-.0000123875,-1.1107880308,0]))
        joints.update(mimic_commands(str(directory/'robot.urdf'),'finger_joint',-.5))
        config.update(initial_joints=joints,gripper_urdf=str(directory/'robot.urdf'),gripper_joint='finger_joint')
    elif model == 'franka_panda':
        joints=dict(zip(['panda_joint'+str(i) for i in range(1,8)],[-.0114430609,-.1461084292,.0110332323,-2.2183429949,.0018318037,2.0722426326,.7839902483]))
        joints.update({'panda_finger_joint1':.04,'panda_finger_joint2':.04})
        config.update(initial_joints=joints,tcp_offset=metadata['tcp_offset'],gripper_urdf=str(directory/'robot.urdf'),gripper_joint='panda_finger_joint1',gripper_mapping={'panda_finger_joint2':1.},max_joint_speed=.5,
                      gripper_physics={'joint_path':'panda_hand/panda_finger_joint1','body_paths':['panda_leftfinger','panda_rightfinger'],'drive_type':'linear','max_force':20.,'friction':1.})
    else:
        joints=dict(zip(['shoulder_pan_joint','shoulder_lift_joint','elbow_joint','wrist_1_joint','wrist_2_joint','wrist_3_joint'],[-.3340939157,-1.9129483852,2.1030217123,-1.7608695245,-1.5707965136,1.2367162245]))
        config.update(initial_joints=joints,tcp_offset=metadata['tcp_offset'],tcp_orientation_wxyz=metadata['tcp_orientation_wxyz'],suction={'prim':metadata['surface_gripper_prim'],'max_grip_distance':.02,'force_limit':100},max_joint_speed=.5)
    limitations=['starting configuration only; asset compatibility, reachable targets, trajectory and collision safety must be validated in the actual simulator']
    if model=='franka_panda':
        limitations.append('scene-local 20 N finger drive and friction 1.0 are experimental and must be validated for the selected asset and objects')
    return {'model':model,'pose_follower':config,'variants':metadata.get('variants',{}),'limitations':limitations}


def pick_cycle(model_directory, drop_position, item='$item', return_position=None, workspace_min=None, workspace_max=None):
    """Propose a calibrated-size pick cycle for expansion by the stream planner."""
    import math
    directory=Path(model_directory).expanduser().resolve()
    metadata=json.loads((directory/'profile.json').read_text());model=metadata.get('model')
    if model not in MODELS:raise ValueError('profile does not identify a supported generated model')
    def vector(value):
        return isinstance(value,list) and len(value)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in value)
    if drop_position!='$slot' and not vector(drop_position):raise ValueError('drop_position must be a world position or $slot')
    if return_position is not None and not vector(return_position):raise ValueError('return_position must be a world position')
    if workspace_min is not None or workspace_max is not None:
        if not vector(workspace_min) or not vector(workspace_max) or any(a>=b for a,b in zip(workspace_min,workspace_max)):
            raise ValueError('workspace bounds require ordered finite world positions')
    if not isinstance(item,str) or not item:raise ValueError('item must be a workpiece ID or $item')
    offset={'kawasaki_rs007l_rg2':-.01,'franka_panda':.02,'ur10_short_suction':.025}[model]
    close={'kawasaki_rs007l_rg2':.5,'franka_panda':0.,'ur10_short_suction':.5}[model]
    opening={'kawasaki_rs007l_rg2':-.5,'franka_panda':.04,'ur10_short_suction':-.5}[model]
    settle=120 if model=='ur10_short_suction' else 180
    track={'type':'track','object':item,'offset':[0,0,offset],'steps':90}
    grip={'type':'track','object':item,'offset':[0,0,offset],'steps':settle,'gripper_value':close}
    if workspace_min is not None:
        for phase in (track,grip):phase.update(workspace_min=list(workspace_min),workspace_max=list(workspace_max))
    if model=='ur10_short_suction':grip['required_object']=item
    lift={'type':'move','object':item,'offset':[0,0,.2 if model=='franka_panda' else .23],
          'min_steps':120 if model=='kawasaki_rs007l_rg2' else 30,'max_steps':600,'tolerance_m':.01}
    height={'kawasaki_rs007l_rg2':.23,'franka_panda':.13,'ur10_short_suction':.205}[model]
    def move(z):
        phase={'type':'move','min_steps':30,'max_steps':600,'tolerance_m':.01,'max_joint_speed':1.3,'settle_steps':15}
        if drop_position=='$slot':phase.update(position='$slot',slot_offset=[0,0,z])
        else:phase['position']=[drop_position[0],drop_position[1],drop_position[2]+z]
        return phase
    transfer=move(height)
    if model=='franka_panda':transfer['rmp_max_joint_speed']=.4
    phases=[track,grip,lift,transfer,move(0),{'type':'gripper','value':opening,'steps':settle},move(height)]
    if return_position is not None:
        phase=move(0);phase['position']=return_position;phase.pop('slot_offset',None);phases.append(phase)
    return {'model':model,'cycle':phases,'assumptions':['experimental template calibrated only for approximately 4 cm cube workpieces and the matching NVIDIA robot/gripper asset',
             'drop_position is the intended TCP position, not an automatically solved bin center',
             'reachability, collisions, grasp force and timing require independent validation in the simulator']}
