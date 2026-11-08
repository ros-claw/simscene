"""Compile measured role bindings into ordinary atomic scene operations.

No downloads, SDK startup, scene writes, physics runs or runtime setters occur.
Prepared-package pins are verified before their metric bounds are used.
"""
from copy import deepcopy
import itertools
import math

from ..catalog.models import stable_hash
from ..physics_binding import validate_asset_binding
from ..placement import rotate, validate_surfaces
from ..scene import SceneError, _id, validate
from .registry import get_recipe


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in [{low}, {high}]')
    return float(value)


def _vector(value, name, n=3):
    if not isinstance(value, list) or len(value) != n:
        raise ValueError(name + ' must be a finite vector')
    return [_number(v, name, -1e5, 1e5) for v in value]


def _box(value):
    if not isinstance(value, dict) or set(value) != {'min', 'max'}:
        raise ValueError('bounds require min/max')
    low, high = _vector(value['min'], 'minimum'), _vector(value['max'], 'maximum')
    if any(a >= b for a, b in zip(low, high)):
        raise ValueError('empty or inverted bounds')
    return {'min': low, 'max': high}


def _role(bindings, role, profile):
    if role not in bindings:
        raise ValueError(f'missing asset://{role}: select and prepare a {profile} asset before compilation')
    value = bindings[role]
    if not isinstance(value, dict) or set(value) != {'asset_path', 'asset_binding'}:
        raise ValueError(f'asset://{role} requires exactly asset_path and pinned asset_binding')
    manifest = validate_asset_binding(value['asset_binding'], require_dynamic=profile == 'rigid_prop_v1', asset_path=value['asset_path'])
    if manifest.get('profile_id') != profile:
        raise ValueError(f'asset://{role} requires {profile}; prepare a compatible alternative')
    bounds = _box({k: manifest['bounds'][k] for k in ('min', 'max')})
    return deepcopy(value), manifest, bounds


def _overlap(a, b):
    return all(min(a['max'][i], b['max'][i]) - max(a['min'][i], b['min'][i]) > 1e-8 for i in range(3))


def compile_recipe(recipe_id, parameters, bindings, scene):
    recipe = get_recipe(recipe_id)
    if not isinstance(parameters, dict) or not isinstance(bindings, dict) or not isinstance(scene, dict) or not isinstance(scene.get('objects'), dict):
        raise ValueError('parameters, bindings and a scene with objects are required')
    revision = scene.get('revision')
    if type(revision) is not int or revision < 0:
        raise ValueError('scene requires a nonnegative base revision')
    p = deepcopy(parameters)
    prefix = _id(p.pop('prefix', 'cell'))
    warnings, requirements, ports, envelopes = [], [], {}, {}
    if recipe_id == 'passive_door_bridge_v1':
        if bindings:
            raise ValueError('primitive bridge recipe accepts no imported role bindings')
        from ..mechanism_modules import compile_plan
        plan = compile_plan('door_bridge', prefix, p)
        operations, ports = plan['operations'], plan['ports']
        warnings.extend(plan['warnings'])
        requirements.append({'type': 'local_physics_trial', 'negative_control': 'lock panel or remove payload contact'})
    else:
        allowed = {'origin_m', 'support_surface', 'count', 'spacing_m', 'drop_height_m', 'payload_orientation_wxyz', 'keepout_bounds'}
        if set(p) - allowed or set(bindings) - {'support', 'payload'}:
            raise ValueError('unknown gravity-drop parameters or roles')
        origin = _vector(p.get('origin_m', [0, 0, 0]), 'origin_m')
        count = p.get('count', 1)
        if type(count) is not int or not 1 <= count <= 8:
            raise ValueError('count must be 1..8')
        gap = _number(p.get('spacing_m', .025), 'spacing_m', .001, 2)
        drop = _number(p.get('drop_height_m', .25), 'drop_height_m', .01, 2)
        q = _vector(p.get('payload_orientation_wxyz', [1, 0, 0, 0]), 'orientation', 4)
        if abs(sum(v*v for v in q) - 1) > 1e-6:
            raise ValueError('payload quaternion must be normalized')
        payload, payload_manifest, payload_bounds = _role(bindings, 'payload', 'rigid_prop_v1')
        support, support_manifest, support_bounds = _role(bindings, 'support', 'static_fixture_v1')
        surfaces = support_manifest.get('support_surfaces')
        validate_surfaces(surfaces)
        surface_name = p.get('support_surface')
        if not isinstance(surface_name, str) or surface_name not in surfaces:
            raise ValueError('choose support_surface from the prepared support manifest: ' + ', '.join(surfaces))
        region = surfaces[surface_name]
        rotated = [rotate(q, list(point)) for point in itertools.product(*zip(payload_bounds['min'], payload_bounds['max']))]
        low = [min(point[i] for point in rotated) for i in range(3)]
        high = [max(point[i] for point in rotated) for i in range(3)]
        width = high[0] - low[0]
        total = count*width + (count-1)*gap
        if total + 2*gap > region['max_xy'][0]-region['min_xy'][0] or high[1]-low[1] + 2*gap > region['max_xy'][1]-region['min_xy'][1]:
            raise ValueError('payload footprints exceed usable support region; choose a larger support, smaller prepared payload or fewer instances')
        cx = (region['min_xy'][0]+region['max_xy'][0])/2
        cy = (region['min_xy'][1]+region['max_xy'][1])/2
        operations = [{'op': 'add', 'id': prefix+'_support', 'object': dict(support, kind='asset', position=origin, dynamic=False, collision=True)}]
        keepouts = [_box(b) for b in p.get('keepout_bounds', [])] if isinstance(p.get('keepout_bounds', []), list) else None
        if keepouts is None or len(keepouts) > 128:
            raise ValueError('keepout_bounds requires at most 128 world-metre boxes')
        for index in range(count):
            x = cx-total/2+width/2+index*(width+gap)
            position = [origin[0]+x-(low[0]+high[0])/2, origin[1]+cy-(low[1]+high[1])/2, origin[2]+region['z_m']+drop-low[2]]
            footprint = {'min_xy': [x-width/2, cy-(high[1]-low[1])/2], 'max_xy': [x+width/2, cy+(high[1]-low[1])/2]}
            if any(all(min(footprint['max_xy'][i], ex['max_xy'][i]) > max(footprint['min_xy'][i], ex['min_xy'][i]) for i in range(2)) for ex in region.get('exclude', [])):
                raise ValueError('a payload footprint crosses an excluded support region')
            name = prefix+'_payload_'+str(index+1).zfill(2)
            # The entire drop sweep, including eventual resting volume, must avoid the caller's keepouts.
            envelope = {'min': [position[0]+low[0], position[1]+low[1], origin[2]+region['z_m']],
                        'max': [position[i]+high[i] for i in range(3)]}
            if any(_overlap(envelope, box) for box in keepouts):
                raise ValueError('planned drop envelope intersects a keepout: '+name)
            envelopes[name] = envelope
            operations.append({'op': 'add', 'id': name, 'object': dict(payload, kind='asset', position=position, orientation_wxyz=q, dynamic=True, collision=True)})
        ports = {'receiving_surface': {'body': prefix+'_support', 'surface': surface_name, 'world_z_m': origin[2]+region['z_m']},
                 'input_bodies': [op['id'] for op in operations[1:]]}
        requirements = [{'role': role, 'profile_id': manifest['profile_id'], 'prepared_id': manifest['prepared_id'],
                         'manifest_sha256': bindings[role]['asset_binding']['manifest_sha256']} for role, manifest in [('payload', payload_manifest), ('support', support_manifest)]]
        requirements.append({'type': 'local_physics_trial', 'negative_control': 'remove support collision in a separately frozen scene', 'checks': ['actual body path', 'gravity motion', 'support actor contact', 'complete bounds', 'settling']})
        warnings.append('Measured geometric fit is not a stability certificate. Validate the new scene and its missing-support control before recording.')
    merged = deepcopy(scene)
    for op in operations:
        if op['id'] in merged['objects']:
            raise SceneError('recipe object already exists: '+op['id'])
        merged['objects'][op['id']] = deepcopy(op['object'])
    issues = validate(merged)
    if issues:
        raise SceneError('compiled scene is invalid: '+str(issues[:5]))
    identity = {'recipe_id': recipe_id, 'version': recipe['version'], 'parameters': parameters, 'bindings': bindings}
    return {'schema_version': 1, 'recipe_id': recipe_id, 'recipe_hash': stable_hash(identity), 'base_revision': revision,
            'operations': operations, 'requirements': requirements, 'warnings': warnings, 'ports': ports,
            'drop_envelopes_m': envelopes, 'physics_tested': False,
            'recommended_camera': {'purpose': 'show payload, support and contact before the drop', 'resolution': [960, 540], 'fps': 30}}
