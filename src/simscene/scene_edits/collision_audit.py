"""Propose a discrete collision audit for the three experimental models.

Asset names identify a candidate policy, not an assurance of asset identity or
safety. The caller must inspect the chosen model and pair exceptions.
"""
import copy
import json
from pathlib import Path
from ..scene import SceneError, _id, validate
from ..verification.acceptance import COLLISION_POLICY

SUFFIXES = {
    'kawasaki': '/Kawasaki/RS007L/rs007l_onrobot_rg2.usd',
    'franka': '/FrankaRobotics/FrankaPanda/franka.usd',
    'ur10': '/UniversalRobots/ur10/ur10.usd',
}
PROFILE_MODELS={'kawasaki_rs007l_rg2':'kawasaki','franka_panda':'franka','ur10_short_suction':'ur10'}

def propose(scene, robot_ids):
    if not isinstance(robot_ids, list) or not robot_ids or not all(isinstance(x, str) for x in robot_ids) or len(robot_ids) != len(set(robot_ids)):
        raise SceneError('robot_ids must be a nonempty list of distinct robot IDs')
    objects = scene.get('objects', {})
    mapping = {}
    operations = []
    for robot in robot_ids:
        _id(robot)
        obj = objects.get(robot, {})
        path = obj.get('asset_path')
        if obj.get('kind') != 'asset' or not isinstance(path, str):
            raise SceneError(f'{robot} must be a robot USD asset')
        matches = [kind for kind, suffix in SUFFIXES.items() if path.lower().endswith(suffix.lower())]
        # Downloaded packages often flatten the original asset root. A profile
        # generated for this exact local asset preserves the model identity.
        if not matches:
            follower = obj.get('pose_follower')
            directory = follower.get('model_directory') if isinstance(follower,dict) else None
            try:
                profile=json.loads((Path(directory)/'profile.json').read_text())
                kind=PROFILE_MODELS.get(profile.get('model'))
                if kind and Path(profile['asset_path']).expanduser().resolve()==Path(path).expanduser().resolve():
                    matches=[kind]
            except (OSError,ValueError,TypeError,KeyError):
                pass
        if len(matches) != 1:
            raise SceneError(f'{robot} is not a supported model path or matching generated profile; review collision policy manually')
        kind = matches[0]
        follower = obj.get('pose_follower')
        if not isinstance(follower, dict):
            raise SceneError(f'{robot} must have a pose follower')
        mapping[robot] = kind
        updated = copy.deepcopy(follower)
        updated['monitor_collisions'] = True
        updated['self_collision_enabled'] = True
        updated['diagnose_overlaps'] = True
        updated['self_collision_exclusions'] = copy.deepcopy(COLLISION_POLICY['mechanical_pairs'][kind])
        operations.append({'op':'update', 'id':robot, 'changes':{'pose_follower':updated}})
    candidate = copy.deepcopy(scene)
    for op in operations:
        candidate['objects'][op['id']].update(op['changes'])
    issues = validate(candidate)
    if issues:
        raise SceneError(f'collision audit proposal produces an invalid scene: {issues}')
    policy = {section: {name: copy.deepcopy(entries[kind]) for name, kind in mapping.items()}
              for section, entries in COLLISION_POLICY.items()}
    return {'operations':operations, 'collision_policy':policy,
            'scope':'Candidate for the named model paths or matching generated profiles only. Inspect the exact assets and mechanical pair exclusions. After applying the operations, regenerate the stream case and add collision_policy, run, and check the collision_audit. The audit samples discrete physics steps and approximates mesh collisions with convex hulls; it does not certify swept paths, excluded geometry, or physical-robot safety.'}
