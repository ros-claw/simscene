"""Frozen gravity handoffs through actual contacts and independently moving bodies.

Only the named chain is passive. A separately declared gallery mechanism may
have drives. Contact callbacks are evidence, never controller triggers here.
"""
import hashlib
import json
import math
import re
from pathlib import Path
from .settling import stable

SCHEMA = 'simscene.handoff_chain.v1'


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value, count):
    return isinstance(value, list) and len(value) == count and all(_number(v) for v in value)


def _bounds(value):
    return (isinstance(value, dict) and _vector(value.get('min'), 3) and _vector(value.get('max'), 3)
            and all(a < b for a, b in zip(value['min'], value['max'])))


def _inside(bounds, target):
    return _bounds(bounds) and all(target['min'][i] <= bounds['min'][i] <= bounds['max'][i] <= target['max'][i] for i in range(3))


def _id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value) is not None


def _path(value):
    return (isinstance(value, str) and value.startswith('/World/')
            and all(p not in ('', '.', '..') for p in value.split('/')[1:])
            and not any(c in value for c in ('\\', '%', '?', '#', ':')))


def validate_case(case):
    if (not isinstance(case, dict) or case.get('schema') != SCHEMA
            or type(case.get('schema_version')) is not int or case['schema_version'] != 1):
        raise ValueError('unsupported handoff chain case')
    if type(case.get('steps')) is not int or not 120 <= case['steps'] <= 60000:
        raise ValueError('handoff chain requires a frozen complete run duration')
    ids = [case.get(k) for k in ('source_object_id', 'ball_object_id', 'guide_object_id', 'receiver_object_id')]
    tiles = case.get('tiles'); tile_ids = case.get('tile_object_ids')
    if (not isinstance(tiles, list) or not 3 <= len(tiles) <= 64 or not isinstance(tile_ids, list)
            or len(tile_ids) != len(tiles) or not all(_id(n) for n in ids + tile_ids)
            or len(set(ids + tile_ids)) != len(ids + tile_ids)):
        raise ValueError('handoff chain requires distinct explicit object IDs and bounded tile mappings')
    if any(p != '/World/' + n.replace('-', '_') for p, n in zip(tiles, tile_ids)):
        raise ValueError('domino actors must match their explicitly declared ordinary object IDs')
    paths = [case.get(k) for k in ('source_body', 'ball_body', 'guide_actor', 'receiver_floor_actor')] + tiles
    if not all(_path(p) for p in paths) or len(set(paths)) != len(paths):
        raise ValueError('handoff chain requires distinct exact actor paths')
    if case['ball_body'] != '/World/' + case['ball_object_id'].replace('-', '_'):
        raise ValueError('handoff ball must have its explicit ordinary sphere actor')
    if case.get('negative_removed_tile') not in tiles[1:-1]:
        raise ValueError('handoff negative must remove exactly an interior domino')
    for name in ('source_min_travel_m', 'ball_min_travel_m', 'ball_radius_m'):
        if not _number(case.get(name)) or case[name] <= 0:
            raise ValueError('handoff motion/radius must be finite positive values')
    if case['ball_min_travel_m'] <= 2 * case['ball_radius_m']:
        raise ValueError('meaningful ball travel must exceed its diameter')
    initial = case.get('initial_vertical_cos_min'); active = case.get('activation_vertical_cos_max'); final = case.get('final_vertical_cos_max')
    if not all(_number(v) for v in (initial, active, final)) or not -1 <= final < active < initial <= 1 or initial < .9:
        raise ValueError('invalid frozen initial, activation and final tilt thresholds')
    if not _bounds(case.get('target_bounds')) or not _bounds(case.get('trajectory_bounds')) or not _inside(case['target_bounds'], case['trajectory_bounds']):
        raise ValueError('handoff requires a target inside its bounded trajectory region')
    if any(b-a <= 2*case['ball_radius_m'] for a, b in zip(case['target_bounds']['min'], case['target_bounds']['max'])):
        raise ValueError('ball must fit completely inside receiver target')
    if case.get('control_render_policy','identical') not in ('identical','allow_static_render_differences'):
        raise ValueError('unknown explicit control rendering policy')
    floor = case.get('container_floor_tolerance_m', .002)
    if not _number(floor) or not 0 <= floor <= .002:
        raise ValueError('container floor tolerance must stay within 2mm')
    roles = {case['source_object_id']: 'rigid_prop_v1', case['guide_object_id']: 'static_fixture_v1', case['receiver_object_id']: 'container_v1'}
    pins = case.get('prepared_manifest_sha256s'); sources = case.get('source_refs')
    if not isinstance(pins, dict) or set(pins) != set(roles) or case.get('prepared_profiles') != roles or not isinstance(sources, dict) or set(sources) != set(roles):
        raise ValueError('handoff requires all three prepared source/profile pins by actual object ID')
    for name in roles:
        if not isinstance(pins[name], str) or not re.fullmatch('[0-9a-f]{64}', pins[name]):
            raise ValueError('invalid handoff prepared manifest SHA256')
        source = sources[name]
        if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k] for k in ('source_id', 'asset_id', 'revision')):
            raise ValueError('handoff requires explicit immutable source references')
    return case


def _vertical(q):
    if not _vector(q, 4) or abs(sum(v*v for v in q)-1) > .001:
        raise ValueError('missing or invalid actual body quaternion')
    return 1 - 2 * (q[1]*q[1] + q[2]*q[2])


def _sphere_bounds(position, radius):
    if not _vector(position, 3):
        raise ValueError('missing actual sphere center')
    return {'min': [v-radius for v in position], 'max': [v+radius for v in position]}


def evaluate(run, case, mode='positive'):
    validate_case(case)
    if mode not in ('positive', 'missing_middle'):
        raise ValueError('unsupported handoff chain mode')
    try:
        return _evaluate(run, case, mode)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return {'schema_version': 1, 'mode': mode, 'passed': False,
                'checks': {'valid_measurements': False}, 'errors': [str(error)]}


def _evaluate(run, case, mode):
    frames = [run.get('initial_observation')] + run.get('samples', [])
    steps = run.get('actual_physics_steps'); tiles = case['tiles']; removed = case['negative_removed_tile']
    source = case['source_body']; ball = case['ball_body']
    chain_ids = {case['source_object_id'], case['ball_object_id'], *case['tile_object_ids']}
    checks = {'complete_steps': type(steps) is int and steps == run.get('requested_physics_steps') == case['steps'],
              'complete_frames': False, 'not_partial': run.get('partial') is False,
              'samples_not_truncated': run.get('samples_truncated') is False,
              'contacts_not_truncated': run.get('contacts_truncated') is False,
              'contact_geometry_complete': run.get('contact_geometry_incomplete') is False,
              'no_followers': not run.get('followers'), 'no_chain_drive_controllers': True}
    checks['complete_frames'] = (checks['complete_steps'] and run.get('observation_interval_steps') == 1
        and len(frames) == steps + 1 and all(isinstance(f, dict) and f.get('physics_steps') == i
            and _number(f.get('simulation_time_s')) and abs(f['simulation_time_s']-i/60) < 1e-6 for i, f in enumerate(frames))
        and _number(run.get('simulation_time_s')) and abs(run['simulation_time_s']-steps/60) < 1e-6)
    if not checks['complete_frames']:
        return {'schema_version': 1, 'mode': mode, 'passed': False, 'checks': checks, 'measurements': {}}
    mapping = run.get('body_bindings', {}).get(case['source_object_id'], {})
    checks['exact_prepared_source_motion_body'] = mapping.get('motion_body') == source and mapping.get('profile_id') == 'rigid_prop_v1'
    subjects = [(case['source_object_id'], source)] + list(zip(case['tile_object_ids'], tiles))
    if mode == 'missing_middle':
        subjects = [(name, path) for name, path in subjects if path != removed]
    actual_frames = True; bounded = True; sphere_bounds = []
    for frame in frames:
        checks['no_chain_drive_controllers'] &= not (set(frame.get('mechanisms', {})) & chain_ids)
        checks['no_followers'] &= not frame.get('followers')
        for name, path in subjects:
            if not _vector(frame.get('positions', {}).get(path), 3):
                raise ValueError('missing actual chain body position')
            _vertical(frame.get('orientations_wxyz', {}).get(path))
            bounds = frame.get('bounds', {}).get(name)
            actual_frames &= _bounds(bounds)
            bounded &= _inside(bounds, case['trajectory_bounds'])
        _vertical(frame.get('orientations_wxyz', {}).get(ball))
        bounds = _sphere_bounds(frame.get('positions', {}).get(ball), case['ball_radius_m'])
        sphere_bounds.append(bounds); bounded &= _inside(bounds, case['trajectory_bounds'])
    checks['full_body_pose_and_bounds_observations'] = actual_frames
    checks['full_bounded_trajectory'] = bounded
    pairs = {}; zero = run.get('run_zero_absolute_physics_step')
    if type(zero) is not int:
        raise ValueError('missing measured task-zero callback counter')
    for frame in frames:
        for pair in frame.get('contact_pairs', []):
            actors = pair.get('actor_paths'); first = pair.get('first_callback_absolute_physics_step'); last = pair.get('last_callback_absolute_physics_step')
            if (isinstance(actors, list) and len(actors) == 2 and all(_path(p) for p in actors)
                    and type(pair.get('count')) is int and pair['count'] > 0
                    and type(first) is int and type(last) is int and zero < first <= last <= zero+frame['physics_steps']):
                pairs.setdefault(frozenset(actors), []).append(first-zero)
    def contact(a, b):
        values = pairs.get(frozenset((a, b)), [])
        return min(values) if values else None
    activation = {}; final_cos = {}; initial_cos = {}
    for path in tiles:
        if mode == 'missing_middle' and path == removed:
            continue
        values = [_vertical(frame['orientations_wxyz'][path]) for frame in frames]
        initial_cos[path] = values[0]; final_cos[path] = values[-1]
        activation[path] = next((i for i, v in enumerate(values) if v <= case['activation_vertical_cos_max']), None)
    checks['tiles_initially_upright'] = all(v >= case['initial_vertical_cos_min'] for v in initial_cos.values())
    checks['source_actual_travel'] = max(f['positions'][source][0] for f in frames)-frames[0]['positions'][source][0] >= case['source_min_travel_m']
    first = contact(source, tiles[0]); checks['actual_source_first_tile_contact'] = first is not None
    checks['first_tile_activated_after_source_contact'] = first is not None and activation[tiles[0]] is not None and first <= activation[tiles[0]]
    initial_ball = frames[0]['positions'][ball]
    ball_activation = next((i for i, f in enumerate(frames) if f['positions'][ball][0]-initial_ball[0] >= case['ball_min_travel_m']), None)
    detail = {'activation_steps': activation, 'final_vertical_cos': final_cos, 'source_first_contact_step': first,
              'last_tile_ball_contact_step': contact(tiles[-1], ball), 'ball_activation_step': ball_activation,
              'ball_final_position': frames[-1]['positions'][ball], 'ball_final_bounds': sphere_bounds[-1],
              'sphere_bounds_method': 'actual_PhysX_center_plus_minus_frozen_uniform_sphere_radius; exact_rotation_invariant_geometry'}
    if mode == 'positive':
        checks['all_tiles_tipped'] = all(v <= case['final_vertical_cos_max'] for v in final_cos.values())
        detail['adjacent_contact_steps'] = {a+' -> '+b: contact(a, b) for a, b in zip(tiles, tiles[1:])}
        checks['all_adjacent_handoffs_contact_and_order'] = all(contact(a, b) is not None and activation[a] is not None
            and activation[b] is not None and activation[a] <= contact(a, b) <= activation[b] for a, b in zip(tiles, tiles[1:]))
        last = contact(tiles[-1], ball)
        checks['last_tile_actual_ball_handoff'] = (last is not None and activation[tiles[-1]] is not None
            and ball_activation is not None and activation[tiles[-1]] <= last <= ball_activation)
        guide_steps = pairs.get(frozenset((ball, case['guide_actor'])), [])
        checks['moving_ball_actual_generated_guide_contact'] = ball_activation is not None and any(s >= ball_activation for s in guide_steps)
        receiver = contact(ball, case['receiver_floor_actor'])
        checks['ball_actual_receiver_floor_contact'] = receiver is not None and ball_activation is not None and receiver >= ball_activation
        checks['ball_full_bounds_retained'] = _inside(sphere_bounds[-1], case['target_bounds'])
        checks['ball_settled_two_seconds'] = stable(frames, ball, run['simulation_time_s'], 2., .03, .3)
    else:
        index = tiles.index(removed); upstream = tiles[:index]; downstream = tiles[index+1:]
        checks['upstream_still_tips'] = all(final_cos[p] <= case['final_vertical_cos_max'] for p in upstream)
        checks['downstream_remains_upright'] = all(all(_vertical(f['orientations_wxyz'][p]) >= case['initial_vertical_cos_min'] for f in frames) for p in downstream)
        checks['no_source_bypass_contact'] = all(contact(source, p) is None for p in downstream)
        checks['ball_not_activated'] = ball_activation is None
        checks['no_downstream_ball_contact'] = contact(tiles[-1], ball) is None
        checks['no_receiver_completion'] = contact(ball, case['receiver_floor_actor']) is None
    return {'schema_version': 1, 'mode': mode, 'passed': all(checks.values()), 'checks': checks, 'measurements': detail,
            'scope': 'one frozen gravity/contact handoff chain; separately declared unrelated mechanisms may be driven'}


def _selection(spec, case):
    """Pin source/profile identities and known sphere/container geometry to inputs."""
    from ..physics_binding import validate_asset_binding
    from ..placement import rotate
    manifests = {}
    for name, profile in case['prepared_profiles'].items():
        obj = spec['objects'][name]; binding = obj['asset_binding']
        if binding['manifest_sha256'] != case['prepared_manifest_sha256s'][name]:
            raise ValueError('chain prepared manifest differs from frozen case')
        manifest = validate_asset_binding(binding, require_dynamic=profile == 'rigid_prop_v1', asset_path=obj['asset_path'])
        if manifest['profile_id'] != profile or manifest.get('source_ref') != case['source_refs'][name]:
            raise ValueError('chain source/profile differs from frozen case')
        if obj.get('dynamic', False) is not (profile == 'rigid_prop_v1'):
            raise ValueError('chain source/guide/receiver dynamic role differs')
        manifests[name] = manifest
    ball = spec['objects'][case['ball_object_id']]; diameter = 2*case['ball_radius_m']
    if (ball.get('kind') != 'sphere' or ball.get('dynamic') is not True or ball.get('collision', True) is not True
            or not _vector(ball.get('size'), 3) or any(abs(v-diameter) > 1e-9 for v in ball['size'])):
        raise ValueError('chain ball differs from frozen uniform sphere geometry')
    for name in [case['source_object_id'], case['ball_object_id'], *case['tile_object_ids']]:
        obj = spec['objects'].get(name)
        if obj is not None and (obj.get('pose_follower') or obj.get('mechanism') or obj.get('spawn_step', 0)):
            raise ValueError('chain subjects cannot have controllers or scheduled spawning')
    missing=[name for name in case['tile_object_ids'] if name not in spec['objects']]
    removed_id=case['tile_object_ids'][case['tiles'].index(case['negative_removed_tile'])]
    if missing and missing != [removed_id]:
        raise ValueError('only the frozen interior control tile may be absent')
    for name in case['tile_object_ids']:
        obj = spec['objects'].get(name)
        if obj is not None and (obj.get('kind') != 'box' or obj.get('dynamic') is not True or obj.get('collision', True) is not True):
            raise ValueError('chain tiles must be ordinary colliding dynamic boxes')
    source = manifests[case['source_object_id']]['body_map']['main']['relative_prim_path']
    expected = '/World/'+case['source_object_id'].replace('-', '_')+'/Asset/'+source
    if expected != case['source_body']:
        raise ValueError('chain source body differs from exact prepared mapping')
    for name_key, actor_key in [('guide_object_id', 'guide_actor'), ('receiver_object_id', 'receiver_floor_actor')]:
        name = case[name_key]; paths = [p for entry in manifests[name]['body_map'].values() for p in entry['collider_relative_prim_paths']]
        if case[actor_key] not in ['/World/'+name.replace('-', '_')+'/Asset/'+p for p in paths]:
            raise ValueError('chain support actor differs from prepared collider mapping')
    receiver_name = case['receiver_object_id']; obj = spec['objects'][receiver_name]
    interior = manifests[receiver_name]['parameters']['container_proxy']['interior_bounds']
    q = obj.get('orientation_wxyz', [1, 0, 0, 0]); position = obj.get('position', [0, 0, 0])
    # This role is an axis-aligned upward receiver; do not use a rotated AABB as
    # proof that a sphere fits an arbitrarily rotated cavity.
    axes = [rotate(q, [float(i == j) for i in range(3)]) for j in range(3)]
    if abs(axes[2][2]-1) > 1e-6 or any(sum(abs(v) > 1e-6 for v in axis) != 1 for axis in axes):
        raise ValueError('handoff receiver must have an axis-aligned upward cavity')
    corners = []
    for x in (interior['min'][0], interior['max'][0]):
        for y in (interior['min'][1], interior['max'][1]):
            for z in (interior['min'][2], interior['max'][2]):
                point = rotate(q, [x, y, z]); corners.append([a+b for a, b in zip(point, position)])
    target = {'min': [min(p[i] for p in corners) for i in range(3)], 'max': [max(p[i] for p in corners) for i in range(3)]}
    target['min'][2] -= case.get('container_floor_tolerance_m', .002)
    if any(abs(target[k][i]-case['target_bounds'][k][i]) > 1e-6 for k in ('min', 'max') for i in range(3)):
        raise ValueError('handoff target differs from actual prepared cavity and frozen floor tolerance')
    return True


def verify_selection(spec, case):
    """Public pure-CPU file/recipe admission for an embedded gallery component."""
    validate_case(case)
    return _selection(spec, case)


def _render_schema_proof(directories, names):
    if not names:
        return True
    try:
        from pxr import Usd, UsdPhysics
        for directory in directories:
            stage = Usd.Stage.Open(str(directory/'scene.usda'))
            if not stage:
                return False
            for name in names:
                root = stage.GetPrimAtPath('/World/'+name.replace('-', '_'))
                if not root:
                    continue
                for prim in Usd.PrimRange(root):
                    if (prim.HasAPI(UsdPhysics.RigidBodyAPI) or prim.HasAPI(UsdPhysics.CollisionAPI)
                            or prim.HasAPI(UsdPhysics.ArticulationRootAPI) or prim.IsA(UsdPhysics.Joint)
                            or any('DriveAPI' in schema for schema in prim.GetAppliedSchemas())):
                        return False
        return True
    except (ImportError, RuntimeError, OSError):
        return False


def _render_comparison(positive, negative, case, directories):
    """Exclude explicitly permitted rendering deltas, never physical assets."""
    proof = {'policy':case.get('control_render_policy','identical'), 'objects':{}, 'presentation':None,
             'checked_no_physics_schemas':True,
             'scope':'Rendering differences are excluded only from physical-spec equivalence, not input/evidence hashes.'}
    if proof['policy'] == 'identical':
        return proof
    chain = {case['source_object_id'],case['ball_object_id'],*case['tile_object_ids']}
    allowed = {'camera':{'kind','position','orientation_wxyz','camera','camera_orbit','camera_path','record_fps','preview_fps'},
               'light':{'kind','position','orientation_wxyz','light','intensity','color'}}
    def safe(obj):
        return obj is None or isinstance(obj,dict) and obj.get('kind') in allowed and not set(obj)-allowed[obj['kind']]
    for name in set(positive['objects']) | set(negative['objects']):
        before=positive['objects'].get(name);after=negative['objects'].get(name)
        if name in chain or before==after or not safe(before) or not safe(after):
            continue
        proof['objects'][name]={'before':before,'after':after}
        positive['objects'].pop(name,None);negative['objects'].pop(name,None)
    before=positive.get('presentation');after=negative.get('presentation')
    if before != after:
        from ..capture import validate_presentation
        try:
            for value in (before,after):
                if value is not None:validate_presentation(value)
            proof['presentation']={'before':before,'after':after}
            positive.pop('presentation',None);negative.pop('presentation',None)
        except (TypeError,ValueError) as error:
            proof['checked_no_physics_schemas']=False;proof['error']=str(error)
    proof['checked_no_physics_schemas'] = bool(proof['checked_no_physics_schemas'] and _render_schema_proof(directories,list(proof['objects'])))
    return proof


def _component(document, component_id):
    if document.get('schema') == SCHEMA:
        if component_id is not None:
            raise ValueError('standalone handoff case has no embedded component ID')
        return document, None
    if document.get('schema') != 'simscene.asset_gallery.v1':
        raise ValueError('handoff verification requires a standalone or embedded gallery case')
    from .asset_gallery import validate_case as validate_gallery
    validate_gallery(document)
    matches = [item for item in document['components'] if item['case'].get('schema') == SCHEMA
               and (component_id is None or item['id'] == component_id)]
    if len(matches) != 1:
        raise ValueError('select one unambiguous handoff gallery component')
    return matches[0]['case'], matches[0]['id']


def verify_run(directory, case_path=None, mode='positive', reference_directory=None, component_id=None):
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    root = Path(directory).resolve(); lock = json.loads((root/'run-lock.json').read_text())
    if lock.get('acceptance_case_file') != 'acceptance-case.json':
        raise ValueError('handoff chain requires its frozen JSON acceptance case')
    frozen = root/'acceptance-case.json'; expected = lock.get('acceptance_case_sha256')
    def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if sha(frozen) != expected or case_path is not None and sha(case_path) != expected:
        raise ValueError('handoff acceptance case changed')
    document = json.loads(frozen.read_text()); case, selected_component = _component(document, component_id)
    run = json.loads((root/'result.json').read_text()); spec = json.loads((root/'spec.json').read_text())
    result = evaluate(run, case, mode)
    try:
        _selection(spec, case); selection = True
    except (ValueError, KeyError, TypeError, OSError, AttributeError):
        selection = False
    result['checks']['prepared_selection_and_geometry_pinned'] = selection
    result['checks']['bindings_pinned_to_run'] = run.get('body_bindings') == lock.get('body_bindings') and isinstance(lock.get('body_bindings'), dict)
    if mode == 'missing_middle':
        if reference_directory is None:
            raise ValueError('missing-middle control requires its positive reference run')
        reference = Path(reference_directory).resolve()
        positive = verify_run(reference, mode='positive', component_id=selected_component)
        result['checks']['positive_reference_passed'] = positive['passed']
        p = json.loads((reference/'spec.json').read_text()); n = spec
        def normalize_spec(record, directory):
            result = json.loads(json.dumps(record))
            for key in ('scene_id', 'revision', 'requests'):
                result.pop(key, None)
            def location(value):
                path = Path(value)
                try:
                    return path.relative_to(directory).as_posix()
                except ValueError:
                    return value
            for obj in result['objects'].values():
                if obj.get('kind') == 'asset':
                    obj['asset_path'] = location(obj['asset_path'])
                    if 'asset_binding' in obj:
                        obj['asset_binding']['manifest_path'] = location(obj['asset_binding']['manifest_path'])
            return result
        pobj = normalize_spec(p, reference); nobj = normalize_spec(n, root)
        render_delta = _render_comparison(pobj,nobj,case,[reference,root])
        result['render_only_delta'] = render_delta
        result['checks']['render_delta_has_no_physical_actors'] = render_delta['checked_no_physics_schemas']
        removed_id = case['tile_object_ids'][case['tiles'].index(case['negative_removed_tile'])]
        existed = removed_id in pobj['objects']; pobj['objects'].pop(removed_id, None)
        result['checks']['only_frozen_middle_tile_removed'] = existed and pobj == nobj
        result['checks']['same_frozen_case'] = sha(reference/'acceptance-case.json') == expected
        def runtime_files(directory):
            return {path.relative_to(directory/'runtime').as_posix(): sha(path) for path in (directory/'runtime').rglob('*.py')}
        before = runtime_files(reference); after = runtime_files(root)
        result['checks']['same_runtime_python_files'] = bool(before) and before == after
        reference_lock = json.loads((reference/'run-lock.json').read_text())
        result['checks']['same_runtime_configuration'] = all(lock.get(k) == reference_lock.get(k)
            for k in ('physics_device', 'physics_dt_s', 'runtime_version', 'requested_physics_steps', 'seed'))
    inputs = verify_inputs(root); evidence = verify_evidence(root)
    result.update(input_integrity=inputs, evidence_integrity=evidence, case_pinned_to_run=True,
                  case_container_schema=document['schema'], embedded_component_id=selected_component)
    result['passed'] = bool(all(result['checks'].values()) and inputs['passed'] and evidence['passed'] and evidence['partial'] is False)
    return result
