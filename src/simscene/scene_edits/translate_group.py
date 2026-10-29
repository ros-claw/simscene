"""Propose translating scene objects and explicitly selected move targets."""
import copy
import math
from ..scene import SceneError, _id, validate


def translate_group(scene, ids, delta, move_targets=None):
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 1000
            or not all(isinstance(name, str) for name in ids) or len(set(ids)) != len(ids)):
        raise SceneError('ids must contain 1–1000 distinct object IDs')
    if (not isinstance(delta, list) or len(delta) != 3
            or not all(type(x) in (int, float) and math.isfinite(x) for x in delta)):
        raise SceneError('delta must contain three finite world-space values')
    objects = scene.get('objects', {})
    operations = []
    for name in ids:
        _id(name)
        obj = objects.get(name)
        if not isinstance(obj, dict) or obj.get('kind') not in ('box', 'sphere', 'asset', 'light', 'camera', 'counter'):
            raise SceneError('every selected ID must name a supported scene object')
        if obj.get('kind') == 'camera' and 'camera_orbit' in obj:
            raise SceneError('an orbit camera needs an explicit orbit edit')
        pos = obj.get('position', [0, 0, 0])
        operations.append({'op': 'update', 'id': name,
                           'changes': {'position': [p+d for p, d in zip(pos, delta)]}})
    changed_phases = {}
    if move_targets is not None:
        if (not isinstance(move_targets, dict) or set(move_targets) != {'robot_id', 'center_xy', 'radius_m'}):
            raise SceneError('move_targets requires robot_id, center_xy and radius_m')
        robot = _id(move_targets['robot_id']); center = move_targets['center_xy']; radius = move_targets['radius_m']
        if robot in ids:
            raise SceneError('the robot cannot also be a selected object')
        if (not isinstance(center, list) or len(center) != 2
                or not all(type(x) in (int, float) and math.isfinite(x) for x in center)
                or type(radius) not in (int, float) or not math.isfinite(radius) or not 0 < radius <= 100):
            raise SceneError('move target center and radius must be finite')
        cfg = objects.get(robot, {}).get('pose_follower')
        if not isinstance(cfg, dict) or not isinstance(cfg.get('sequence'), list):
            raise SceneError('move_targets must identify a robot follower')
        updated = copy.deepcopy(cfg); indices = []
        for index, phase in enumerate(updated['sequence']):
            pos = phase.get('position') if phase.get('type') == 'move' else None
            if (isinstance(pos, list) and len(pos) == 3
                    and math.hypot(pos[0]-center[0], pos[1]-center[1]) <= radius):
                phase['position'] = [p+d for p, d in zip(pos, delta)]; indices.append(index)
        if not indices:
            raise SceneError('no absolute move targets matched the requested area')
        operations.append({'op': 'update', 'id': robot, 'changes': {'pose_follower': updated}})
        changed_phases[robot] = indices
    candidate = copy.deepcopy(scene)
    for operation in operations:
        candidate['objects'][operation['id']].update(operation['changes'])
    issues = validate(candidate)
    if issues:
        raise SceneError(f'translation produces an invalid scene: {issues}')
    return {'operations': operations, 'changed_move_phases': changed_phases,
            'scope': 'translation proposal only; inspect selected targets and recheck reachability, collision clearance and physical behavior'}
