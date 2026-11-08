"""Deterministic, editable passive geometry in a caller-supplied local frame.

These compilers author ordinary scene operations, never controllers or releases.
Their output is a construction proposal, not a physical success certificate.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from .passive import finite, quaternion, vector
from .scene import SceneError, _id, validate

SCHEMA = 'simscene.mechanism_plan.v1'


def _require(value, message):
    if not value:
        raise SceneError(message)


def _mul(a, b):
    w, x, y, z = a
    W, X, Y, Z = b
    return [w*W-x*X-y*Y-z*Z, w*X+x*W+y*Z-z*Y,
            w*Y-x*Z+y*W+z*X, w*Z+x*Y-y*X+z*W]


def _rotate(q, p):
    return _mul(_mul(q, [0, *p]), [q[0], -q[1], -q[2], -q[3]])[1:]


def _axis(axis, degrees):
    angle = math.radians(degrees)/2
    return [math.cos(angle), *[math.sin(angle)*v for v in axis]]


def _number(value, low, high, label):
    _require(finite(value) and low <= value <= high, 'invalid '+label)
    return value


def compile_plan(kind, prefix, parameters):
    """origin is a support/pivot location in metres; orientation is wxyz."""
    _id(prefix)
    _require(kind in ('domino_line', 'domino_arc', 'door_bridge'), 'unknown mechanism module')
    _require(isinstance(parameters, dict), 'module parameters must be an object')
    p = copy.deepcopy(parameters)
    common = {'origin', 'orientation_wxyz', 'color', 'physics', 'mass_kg'}
    allowed = common | ({'count', 'size_m', 'spacing_m', 'radius_m', 'sweep_degrees', 'support_thickness_m'}
                        if kind.startswith('domino_') else
                        {'length_m', 'width_m', 'thickness_m', 'raised_angle_degrees', 'landing_width_m'})
    _require(not set(p)-allowed, 'unsupported module parameters: '+str(sorted(set(p)-allowed)))
    origin, frame = p.get('origin', [0, 0, 0]), p.get('orientation_wxyz', [1, 0, 0, 0])
    _require(vector(origin) and quaternion(frame), 'finite origin and normalized wxyz frame required')
    norm = math.sqrt(sum(v*v for v in frame))
    frame = [v/norm for v in frame]
    color = p.get('color', [.08, .35, .50])
    _require(vector(color) and all(0 <= v <= 1 for v in color), 'invalid color')
    up = _rotate(frame, [0, 0, 1])
    _require(up[2] > .999, 'v1 modules require a horizontal support frame; yaw is free')
    physics = {'static_friction': .8, 'dynamic_friction': .65, 'restitution': 0,
               'linear_damping': .05, 'angular_damping': .05, 'sleep_threshold': 0,
               'solver_position_iterations': 64, 'solver_velocity_iterations': 4,
               'enable_ccd': True, 'contact_offset_m': .001, 'rest_offset_m': 0}
    _require(isinstance(p.get('physics', {}), dict), 'physics must be an object')
    physics.update(p.get('physics', {}))
    operations, ports, warnings = [], {}, []

    def point(v):
        r = _rotate(frame, v)
        return [origin[i]+r[i] for i in range(3)]

    def add(name, obj, position, rotation=None):
        obj = copy.deepcopy(obj)
        obj['position'] = point(position)
        obj['orientation_wxyz'] = _mul(frame, rotation or [1, 0, 0, 0])
        operations.append({'op': 'add', 'id': prefix+'_'+name, 'object': obj})

    if kind.startswith('domino_'):
        count, size = p.get('count', 20), p.get('size_m', [.018, .08, .14])
        _require(type(count) is int and 2 <= count <= 512, 'count must be 2..512')
        _require(vector(size) and all(.001 <= x <= 2 for x in size), 'invalid metric domino dimensions')
        thickness, width, height = size
        mass = _number(p.get('mass_kg', .012), .0001, 100, 'mass_kg')
        poses = []
        if kind == 'domino_line':
            _require(not {'radius_m', 'sweep_degrees'} & set(p), 'line does not accept arc parameters')
            spacing = _number(p.get('spacing_m', .065), thickness+.001, height*.95, 'spacing_m')
            poses = [([i*spacing, 0, height/2], 0.) for i in range(count)]
        else:
            _require('spacing_m' not in p, 'arc uses radius and sweep, not spacing_m')
            radius = _number(p.get('radius_m', .7), width/2+.001, 100, 'radius_m')
            sweep = _number(p.get('sweep_degrees', 120), -350, 350, 'sweep_degrees')
            _require(abs(sweep) > .01, 'arc sweep cannot be zero')
            sign = 1 if sweep > 0 else -1
            step = math.radians(sweep)/(count-1)
            for i in range(count):
                a = step*i
                poses.append(([radius*math.sin(a)*sign, radius*(1-math.cos(a))*sign, height/2], math.degrees(a)))
            chord = 2*radius*math.sin(abs(step)/2)
            _require(chord <= height*.95, 'arc gap exceeds the v1 reach bound; add tiles or reduce radius')
        # Oriented rectangle SAT, including nonadjacent tiles on tight curves.
        def overlap(a, b):
            pa, aa = a; pb, ab = b
            axes = [[math.cos(math.radians(v)), math.sin(math.radians(v))] for v in (aa, aa+90, ab, ab+90)]
            def corners(pose):
                pos, deg = pose; q = _axis([0, 0, 1], deg)
                return [[pos[j]+_rotate(q, [x*thickness/2, y*width/2, 0])[j] for j in range(2)] for x in (-1, 1) for y in (-1, 1)]
            ca, cb = corners(a), corners(b)
            for axis in axes:
                va = [sum(x*y for x, y in zip(c, axis)) for c in ca]
                vb = [sum(x*y for x, y in zip(c, axis)) for c in cb]
                if max(va)+.0001 < min(vb) or max(vb)+.0001 < min(va):
                    return False
            return True
        for i, a in enumerate(poses):
            for b in poses[i+1:]:
                _require(not overlap(a, b), 'initial tile overlap/insufficient clearance')
        for i, (pos, angle) in enumerate(poses):
            add('tile_'+str(i+1).zfill(3), {'kind': 'box', 'size': size, 'dynamic': True,
                'collision': True, 'mass_kg': mass, 'physics': physics, 'color': color}, pos, _axis([0, 0, 1], angle))
        support = p.get('support_thickness_m', .025)
        _number(support, 0, 1, 'support_thickness_m')
        if support:
            for i, (pos, angle) in enumerate(poses):
                add('support_'+str(i+1).zfill(3), {'kind': 'box', 'size': [max(thickness*2, height), width+.04, support],
                    'collision': True, 'color': [.63, .51, .35]}, [pos[0], pos[1], -support/2], _axis([0, 0, 1], angle))
        ports = {'input': {'body': prefix+'_tile_001', 'position_m': point(poses[0][0]),
                           'direction_world': _rotate(frame, [1, 0, 0])},
                 'output': {'body': prefix+'_tile_'+str(count).zfill(3), 'position_m': point(poses[-1][0]),
                            'direction_world': _rotate(_mul(frame, _axis([0, 0, 1], poses[-1][1])), [1, 0, 0])}}
        warnings.append('No trigger is authored. Strike the first tile physically; test a removed middle tile control.')
    else:
        length = _number(p.get('length_m', .6), .05, 5, 'length_m')
        width = _number(p.get('width_m', .3), .02, 3, 'width_m')
        thickness = _number(p.get('thickness_m', .025), .002, .2, 'thickness_m')
        angle = _number(p.get('raised_angle_degrees', 80), 5, 89, 'raised_angle_degrees')
        landing = _number(p.get('landing_width_m', .06), thickness, length/2, 'landing_width_m')
        mass = _number(p.get('mass_kg', .3), .001, 100, 'mass_kg')
        rotation = _axis([0, 1, 0], -angle)
        add('panel', {'kind': 'compound', 'parts': [{'kind': 'box', 'size': [length, width, thickness]}], 'dynamic': True,
                     'collision': True, 'mass_kg': mass, 'physics': physics, 'color': color},
            _rotate(rotation, [length/2, 0, 0]), rotation)
        operations.append({'op': 'add', 'id': prefix+'_hinge', 'object': {'kind': 'joint', 'joint': {
            'type': 'revolute', 'body1': prefix+'_panel', 'axis': 'Y',
            'local_pos0': origin, 'local_pos1': [-length/2, 0, 0],
            'local_rot0_wxyz': frame, 'lower_limit': -angle, 'upper_limit': 0}}})
        add('landing', {'kind': 'box', 'size': [landing, width+.04, .04],
                       'collision': True, 'color': [.48, .38, .28]}, [length-landing/2, 0, -thickness/2-.02])
        ports = {'pivot': {'position_m': list(origin), 'axis_world': _rotate(frame, [0, 1, 0])},
                 'input': {'body': prefix+'_panel', 'position_m': point([0, 0, thickness/2])},
                 'output': {'body': prefix+'_panel', 'position_m': point([length, 0, thickness/2])},
                 'retainer': {'body': prefix+'_panel', 'position_m': point(_rotate(rotation, [length*.8, 0, -thickness/2]))}}
        warnings.append('Panel is unlatched and falls under gravity. For a triggered bridge add a real retainer at the retainer port; no timed release is synthesized.')
        warnings.append('Landing support is included; adjoining tables, payload and physical release of that payload are caller-owned.')
    scene = {'objects': {op['id']: op['object'] for op in operations}}
    issues = validate(scene)
    _require(not issues, 'compiled operations are invalid: '+str(issues[:3]))
    return {'schema': SCHEMA, 'version': 1, 'kind': kind, 'prefix': prefix,
            'parameters': p, 'operations': operations, 'ports': ports, 'warnings': warnings,
            'validation': {'schema_valid': True, 'physics_tested': False,
                           'scope': 'Metric construction only. Changing support, load, scale or collision neighbourhood needs a local paired trial.'}}


def save_plan(plan, path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    return {'plan_ref': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'object_count': len(plan['operations']), 'ports': plan['ports'],
            'warnings': plan['warnings'], 'physics_tested': False}


def apply_plan(scene_id, plan_path, expected_sha256, base_revision, request_id):
    from .scene import SceneStore
    path = Path(plan_path)
    data = path.read_bytes()
    _require(hashlib.sha256(data).hexdigest() == expected_sha256, 'plan bytes changed')
    plan = json.loads(data)
    _require(plan['schema'] == SCHEMA and plan == compile_plan(plan['kind'], plan['prefix'], plan['parameters']),
             'plan must be the unchanged deterministic expansion')
    result = SceneStore().apply(scene_id, base_revision, request_id, plan['operations'])
    return {'scene_id': scene_id, 'revision': result['revision'], 'plan_object_count': len(plan['operations']),
            'ports': plan['ports'], 'physics_tested': False}
