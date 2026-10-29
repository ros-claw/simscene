"""Author explicit scene-local grip physics without changing the source USD."""
import math
import re


def validate(config):
    if not isinstance(config, dict) or set(config) != {'joint_path', 'body_paths', 'drive_type', 'max_force', 'friction'}:
        return ['gripper_physics requires joint_path, body_paths, drive_type, max_force and friction']
    def path(value):
        return (isinstance(value, str) and bool(value) and not value.startswith('/')
                and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', part) for part in value.split('/')))
    errors = []
    if not path(config['joint_path']):
        errors.append('gripper joint_path must be a relative USD prim path')
    bodies = config['body_paths']
    if (not isinstance(bodies, list) or not 1 <= len(bodies) <= 16
            or not all(path(item) for item in bodies) or len(set(bodies)) != len(bodies)):
        errors.append('gripper body_paths must contain 1–16 distinct relative USD prim paths')
    if config['drive_type'] not in ('linear', 'angular'):
        errors.append('gripper drive_type must be linear or angular')
    force = config['max_force']; friction = config['friction']
    if type(force) not in (int, float) or not math.isfinite(force) or not 0 < force <= 10000:
        errors.append('gripper max_force must be finite and in (0, 10000]')
    if type(friction) not in (int, float) or not math.isfinite(friction) or not 0 <= friction <= 2:
        errors.append('gripper friction must be finite and in [0, 2]')
    return errors


def apply(stage, robot_path, config):
    from pxr import UsdPhysics, UsdShade
    issues = validate(config)
    if issues:
        raise ValueError('; '.join(issues))
    asset_root = robot_path+'/Asset'
    joint = stage.GetPrimAtPath(asset_root+'/'+config['joint_path'])
    expected = UsdPhysics.PrismaticJoint if config['drive_type'] == 'linear' else UsdPhysics.RevoluteJoint
    if not joint or not joint.IsA(expected):
        raise ValueError('selected gripper joint is missing or has the wrong drive type')
    bodies = [stage.GetPrimAtPath(asset_root+'/'+path) for path in config['body_paths']]
    if any(not prim or not prim.HasAPI(UsdPhysics.RigidBodyAPI) for prim in bodies):
        raise ValueError('selected gripper body is missing or is not a rigid body')
    UsdPhysics.DriveAPI.Apply(joint, config['drive_type']).CreateMaxForceAttr().Set(float(config['max_force']))
    material = UsdShade.Material.Define(stage, robot_path+'/SimSceneGripMaterial')
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr().Set(float(config['friction']))
    physics.CreateDynamicFrictionAttr().Set(float(config['friction']))
    for prim in bodies:
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,
            bindingStrength=UsdShade.Tokens.strongerThanDescendants, materialPurpose='physics')
