"""Conservative, source-pinned motion envelopes for two measured examples.

These are geometric preflights, not general joint inference or a physics pass.
"""
import hashlib
from importlib.resources import files
import itertools
import json
import math

from ..placement import bounds, intersects, rotate, vector
from ..scene import SceneError


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value):
    return (isinstance(value, dict) and set(value) == {'min', 'max'}
            and vector(value['min']) and vector(value['max'])
            and all(a < b for a, b in zip(value['min'], value['max'])))


def swept_local_bounds(kind, initial_bounds, axis, limits, pivot=None):
    """Enclose every pose of a known rigid child, in unscaled owner-local metres.

    A revolute joint uses a full-turn cylinder, so intermediate positions are
    enclosed even when endpoints alone would miss them. A prismatic joint uses
    the union along the full supplied translation interval. The input bounds
    must enclose the child's actual initial geometry at joint coordinate zero.
    """
    if not _box(initial_bounds):
        raise SceneError('motion geometry requires finite nonempty initial bounds')
    if not vector(axis) or abs(sum(v * v for v in axis) - 1.) > 1e-5:
        raise SceneError('motion axis must be a finite unit vector')
    if (not isinstance(limits, list) or len(limits) != 2 or
            not all(_number(v) for v in limits) or limits[0] > limits[1] or
            not limits[0] <= 0 <= limits[1]):
        raise SceneError('motion limits must be finite, ordered, and contain the measured zero state')
    length = math.sqrt(sum(v * v for v in axis))
    unit = [v / length for v in axis]
    if kind == 'prismatic':
        return {'min': [initial_bounds['min'][i] + min(unit[i] * q for q in limits) for i in range(3)],
                'max': [initial_bounds['max'][i] + max(unit[i] * q for q in limits) for i in range(3)]}
    if kind != 'revolute' or not vector(pivot):
        raise SceneError('unsupported motion geometry or missing revolute pivot')
    projections, radii = [], []
    for point in itertools.product(*[(initial_bounds['min'][i], initial_bounds['max'][i]) for i in range(3)]):
        delta = [point[i] - pivot[i] for i in range(3)]
        along = sum(delta[i] * unit[i] for i in range(3))
        projections.append(along)
        radii.append(math.sqrt(sum((delta[i] - along * unit[i]) ** 2 for i in range(3))))
    lo, hi, radius = min(projections), max(projections), max(radii)
    radial = [radius * math.sqrt(max(0., 1. - unit[i] ** 2)) for i in range(3)]
    return {'min': [pivot[i] + min(lo * unit[i], hi * unit[i]) - radial[i] for i in range(3)],
            'max': [pivot[i] + max(lo * unit[i], hi * unit[i]) + radial[i] for i in range(3)]}


def load_profile(profile_id):
    raw = files('simscene.recipes').joinpath('data/known-motion-geometry.json').read_bytes()
    data = json.loads(raw)
    if (not isinstance(profile_id, str) or data.get('schema') != 'simscene.known_motion_geometry.v1'
            or profile_id not in data.get('profiles', {})):
        raise SceneError('unknown or unsupported motion geometry profile')
    return data['profiles'][profile_id]


def _contains(actual, required):
    if isinstance(required, dict):
        return isinstance(actual, dict) and all(key in actual and _contains(actual[key], value)
                                                for key, value in required.items())
    if isinstance(required, list):
        return isinstance(actual, list) and len(actual) == len(required) and all(
            _contains(a, b) for a, b in zip(actual, required))
    if _number(required):
        return _number(actual) and abs(actual - required) <= 1e-7
    return type(actual) is type(required) and actual == required


def _world_bounds(local, position, orientation):
    points = []
    for point in itertools.product(*[(local['min'][i], local['max'][i]) for i in range(3)]):
        turned = rotate(orientation, point)
        points.append([turned[i] + position[i] for i in range(3)])
    return {'min': [min(p[i] for p in points) for i in range(3)],
            'max': [max(p[i] for p in points) for i in range(3)]}


def require_contained_bounds(actual, frozen):
    if not _box(actual) or not _box(frozen):
        raise SceneError('motion geometry requires finite child bounds')
    if any(actual['min'][i] < frozen['min'][i] - 1e-8 or
           actual['max'][i] > frozen['max'][i] + 1e-8 for i in range(3)):
        raise SceneError('actual child geometry exceeds the qualified initial bounds')


def _inspect_prepared_geometry(asset_path, profile):
    """Recheck the actual composed stage, not only the manifest's claims."""
    try:
        from pxr import Usd, UsdGeom
    except ImportError as error:
        raise SceneError('USD Python bindings are required to inspect motion geometry') from error
    from ..preparation.articulation import inspect_articulation
    from ..preparation.articulation_v2 import inspect_articulation_v2

    try:
        stage = Usd.Stage.Open(str(asset_path))
        if not stage or not stage.GetDefaultPrim() or str(stage.GetDefaultPrim().GetPath()) != '/Asset':
            raise SceneError('prepared motion geometry stage cannot be opened')
        expected = profile['qualification_manifest']
        inspect = inspect_articulation_v2 if expected['profile_id'] == 'articulated_prop_v2' else inspect_articulation
        observed = inspect(stage)
        if (not _contains(observed.get('joint_map'), expected['joint_map']) or
                not _contains(observed.get('body_map'), expected['body_map'])):
            raise SceneError('actual native joint or collider geometry differs from the known profile')
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render,
                                                           UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide])
        xforms = UsdGeom.XformCache()
        for motion in profile['motions']:
            joint = expected['joint_map'][motion['joint_id']]
            parent = expected['body_map'][joint['parent_body_id']]['relative_prim_path']
            child = expected['body_map'][joint['child_body_id']]['relative_prim_path']
            parent_prim = stage.GetPrimAtPath('/Asset/' + parent)
            child_prim = stage.GetPrimAtPath('/Asset/' + child)
            if not parent_prim or not child_prim:
                raise SceneError('known motion parent or child geometry is missing')
            transform = xforms.GetLocalToWorldTransform(parent_prim)
            matrix = [[float(transform[i][j]) for j in range(4)] for i in range(4)]
            if not _contains(matrix, motion['parent_transform_owner']):
                raise SceneError('native parent transform differs from qualified motion geometry')
            box = cache.ComputeWorldBound(child_prim).ComputeAlignedRange()
            if box.IsEmpty():
                raise SceneError('native child geometry has empty bounds')
            require_contained_bounds({'min': list(box.GetMin()), 'max': list(box.GetMax())},
                                     motion['initial_child_bounds_owner_m'])
    except SceneError:
        raise
    except Exception as error:
        raise SceneError('could not inspect actual prepared motion geometry: ' + str(error)) from error


def check_motion_clearance(scene, owner_id, profile_id, object_ids=None, clearance_m=.05):
    """Return named known-joint keepouts and check selected external objects.

    The prepared closure, source hash, collision paths and joint metadata must
    match a shipped measurement profile. Only render bounds of explicitly
    listed objects are compared; unlisted objects remain unassessed.
    """
    profile = load_profile(profile_id)
    objects = scene.get('objects') if isinstance(scene, dict) else None
    if not isinstance(objects, dict) or owner_id not in objects:
        raise SceneError('motion preflight requires an existing owner')
    owner = objects[owner_id]
    if (not isinstance(owner, dict) or owner.get('kind') != 'asset' or owner.get('dynamic') is not True
            or not owner.get('asset_binding') or not owner.get('asset_path')):
        raise SceneError('motion preflight requires a dynamic prepared articulated owner')
    forbidden = {'size', 'scale', 'variants', 'pose_follower', 'rigid_attachment', 'asset_metrics',
                 'physics', 'mass_kg', 'collision_exclusions'} & set(owner)
    if forbidden or owner.get('collision', True) is not True:
        raise SceneError('motion geometry cannot be reused with owner geometry or physics overrides')
    position = owner.get('position', [0, 0, 0])
    orientation = owner.get('orientation_wxyz', [1, 0, 0, 0])
    if not vector(position) or not vector(orientation, 4) or abs(sum(v*v for v in orientation) - 1.) > 1e-6:
        raise SceneError('motion owner requires finite position and a normalized orientation')
    if not _number(clearance_m) or not 0 <= clearance_m <= .5:
        raise SceneError('motion clearance must be finite and between zero and 0.5 m')
    selected = [] if object_ids is None else object_ids
    if (not isinstance(selected, list) or len(selected) > 8
            or any(not isinstance(name, str) or name not in objects for name in selected)
            or len(set(selected)) != len(selected)):
        raise SceneError('motion preflight accepts at most eight distinct existing object IDs')
    from ..physics_binding import validate_asset_binding
    try:
        manifest = validate_asset_binding(owner['asset_binding'], require_dynamic=True, asset_path=owner['asset_path'])
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        raise SceneError('motion geometry requires a verified prepared owner: ' + str(error)) from error
    if not _contains(manifest, profile['qualification_manifest']):
        raise SceneError('prepared source, joint or collider geometry differs from the known motion profile')
    _inspect_prepared_geometry(owner['asset_path'], profile)
    named = []
    for motion in profile['motions']:
        local = swept_local_bounds(motion['kind'], motion['initial_child_bounds_owner_m'],
                                   motion['axis_owner'], motion['limits'], motion['pivot_owner_m'])
        named.append({'joint_id': motion['joint_id'], 'bounds': _world_bounds(local, position, orientation),
                      'kind': motion['kind'], 'limits': motion['limits']})
    checked, conflicts = [], []
    for name in selected:
        if name == owner_id:
            continue
        box = bounds(objects[name], scene, name)
        if not _box(box):
            raise SceneError('object has unknown or invalid measured geometry: ' + name)
        checked.append({'object_id': name, 'world_bounds_m': box})
        for region in named:
            if intersects(box, region['bounds'], clearance_m):
                conflicts.append({'object_id': name, 'owner_id': owner_id, 'joint_id': region['joint_id'],
                                  'clearance_m': clearance_m})
    identity = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    try:
        scene_identity = hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(',', ':'),
                                                   allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError) as error:
        raise SceneError('motion preflight requires a finite JSON scene') from error
    return {'schema': 'simscene.motion_clearance.v1', 'scene_revision': scene.get('revision'),
            'scene_sha256': scene_identity, 'owner_id': owner_id, 'profile_id': profile_id, 'profile_sha256': identity,
            'owner_manifest_sha256': owner['asset_binding'].get('manifest_sha256'),
            'keepout_bounds': [entry['bounds'] for entry in named], 'motions': named,
            'clearance_m': clearance_m, 'checked_objects': checked, 'conflicts': conflicts,
            'skipped_owner': owner_id in selected,
            'status': 'conflict' if conflicts else 'clear' if checked else 'not_checked',
            'physics_tested': False,
            'scope': ('Known source and prepared geometry only; full-turn revolute or native-limit slider '
                      'envelopes and selected rendered bounds. Unlisted objects, future joint integrity, '
                      'actual contacts, parent drift and dynamic stability require separate checks.')}
