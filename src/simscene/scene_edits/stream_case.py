"""Propose an opt-in physical evidence case from explicit scene constraints.

This is a user-facing convenience for checking and counting observed items;
the resulting case is derived from the proposed scene and is not an independent
acceptance benchmark. It currently supports the standard per-item cycles of
the three experimental robot profiles and a +X belt.
"""
import hashlib
import json
import math
from pathlib import Path
from ..scene import SceneError, _id
from ..verification.archive_candidate import validate_case


def plan_case(scene, belt_id, bins, forbidden_objects):
    objects = scene.get('objects', {})
    _id(belt_id)
    belt = objects.get(belt_id, {}).get('conveyor', {})
    direction = belt.get('direction')
    speed = belt.get('speed_m_s')
    if (not isinstance(direction, list) or len(direction) != 3
            or abs(direction[0]-1) > 1e-6 or abs(direction[1]) > 1e-6 or abs(direction[2]) > 1e-6
            or type(speed) not in (int, float) or not math.isfinite(speed) or speed <= 0):
        raise SceneError('case proposal currently requires a nonzero +X conveyor')
    if not isinstance(bins, dict) or not bins:
        raise SceneError('bins must map every class to explicit inner bounds')
    if (not isinstance(forbidden_objects, list) or not forbidden_objects
            or not all(isinstance(name, str) and name in objects for name in forbidden_objects)
            or belt_id not in forbidden_objects):
        raise SceneError('forbidden_objects must explicitly name the belt and other monitored scene objects')
    def vector(value):
        return isinstance(value, list) and len(value) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in value)
    for label, value in bins.items():
        if (not isinstance(label, str) or not isinstance(value, dict) or set(value)-{'min', 'max', 'pass_x'}
                or not vector(value.get('min')) or not vector(value.get('max'))
                or any(a >= b for a, b in zip(value['min'], value['max']))
                or not isinstance(value.get('pass_x', []), list)
                or not all(type(x) in (int, float) and math.isfinite(x) for x in value.get('pass_x', []))):
            raise SceneError('each bin needs ordered finite min/max bounds and optional pass_x coordinates')
    items = [(obj['spawn_step'], name, obj) for name, obj in objects.items()
             if isinstance(obj, dict) and obj.get('dynamic') and type(obj.get('spawn_step')) is int and obj['spawn_step'] > 0]
    items.sort()
    if not items or len(items) > 100 or len({step for step, _, _ in items}) != len(items):
        raise SceneError('the scene needs 1–100 uniquely scheduled workpieces')
    origin = items[0][2].get('position')
    if not vector(origin) or any(obj.get('position') != origin for _, _, obj in items):
        raise SceneError('all scheduled workpieces must share one explicit upstream position')
    common = {'tolerance_m': .002, 'minimum_lift_m': .08, 'minimum_belt_displacement_m': .02,
              'retract_distance_m': .1, 'stable_duration_s': 1., 'stable_displacement_m': .003,
              'max_linear_velocity_m_s': .05, 'max_angular_velocity_rad_s': .5,
              'belt_path': '/World/'+belt_id.replace('-', '_'),
              'forbidden_environment_paths': ['/World/'+name.replace('-', '_') for name in forbidden_objects]}
    models = {'franka_panda': {'type': 'parallel', 'left_finger': 'panda_leftfinger', 'right_finger': 'panda_rightfinger',
                               'open_direction': 'greater', 'open_threshold': .035, 'contact_fraction': .8},
              'kawasaki_rs007l_rg2': {'type': 'parallel', 'left_finger': 'left_inner_finger', 'right_finger': 'right_inner_finger',
                                      'open_direction': 'less', 'open_threshold': -.4, 'contact_fraction': .8},
              'ur10_short_suction': {'type': 'suction'}}
    result = []
    for _, item, obj in items:
        label = obj.get('class_label'); bin_spec = bins.get(label)
        if not bin_spec:
            raise SceneError(f'missing explicit bin for workpiece class {label!r}')
        matches = []
        for robot, body in objects.items():
            cfg = body.get('pose_follower') if isinstance(body, dict) else None
            if not isinstance(cfg, dict):
                continue
            sequence = cfg.get('sequence', [])
            matches.extend((robot, cfg, sequence, index) for index, phase in enumerate(sequence)
                           if phase.get('type') == 'wait_object' and phase.get('object') == item)
        if len(matches) != 1:
            raise SceneError(f'{item} needs exactly one scheduled robot route')
        robot, cfg, sequence, wait = matches[0]
        if cfg.get('monitor_collisions') is not True:
            raise SceneError(f'{robot} must monitor collisions for physical evidence')
        try:
            profile = json.loads((Path(cfg['model_directory'])/'profile.json').read_text())
            model = models[profile['model']]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SceneError(f'{robot} needs a recognized experimental profile') from error
        if wait+7 >= len(sequence):
            raise SceneError(f'{item} has an incomplete standard pick cycle')
        phases = sequence[wait:wait+8]
        if ([phase.get('type') for phase in phases] != ['wait_object', 'track', 'track', 'move', 'move', 'move', 'gripper', 'move']
                or any(phases[i].get('object') != item for i in (0, 1, 2, 3))
                or 'gripper_value' not in phases[2] or 'object' in phases[4] or 'object' in phases[5]):
            raise SceneError(f'{item} is not using the supported standard pick cycle')
        entry = dict(model, robot_id=robot, part_id=item, part_path='/World/'+item.replace('-', '_'),
                     class_label=label, tracking_phase=wait+1, release_phase=wait+6,
                     pass_x=bin_spec.get('pass_x', []), bin_min=bin_spec['min'], bin_max=bin_spec['max'],
                     evidence_per_item=True)
        if model['type'] == 'parallel':
            entry.update(grip_phase=wait+2, lift_phase=wait+3, transfer_phase=wait+4)
        else:
            entry['held_phases'] = [wait+3, wait+4, wait+5]
        result.append(entry)
    scene_hash = hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    case = {'source_scene_sha256': scene_hash, 'expected_spawn_order': [name for _, name, _ in items], 'upstream_position': origin,
            'belt_id': belt_id, 'minimum_belt_speed': speed*.99, 'objects': result, 'common': common}
    try:
        validate_case(scene, case)
    except (ValueError, TypeError, KeyError) as error:
        raise SceneError(f'case proposal is inconsistent with scene: {error}') from error
    return {'case': case, 'scope': 'case derived from the supplied scene and bin bounds; it is not independent acceptance or collision-path certification'}
