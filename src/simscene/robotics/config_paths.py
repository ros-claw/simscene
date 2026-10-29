"""Locate cuMotion's bundled robot configurations across Isaac Sim releases."""
from pathlib import Path

def cumotion_robot_config(isaac_root, model):
    if model not in ('franka','ur10'):
        raise ValueError('unsupported bundled cuMotion robot configuration')
    extension=Path(isaac_root)/'exts'/'isaacsim.robot_motion.cumotion'
    candidates=(extension/'robot_configurations'/model,
                extension/'pip_prebundle'/'isaacsim'/'robot_motion'/'cumotion'/'robot_configurations'/model)
    required=('robot.urdf','robot.xrdf','rmp_flow.yaml')
    for path in candidates:
        if all((path/name).is_file() for name in required):return path
    raise FileNotFoundError('no complete cuMotion configuration for '+model+'; checked '+', '.join(map(str,candidates)))
