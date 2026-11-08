"""Read-only evidence for narrowly typed, gravity-loaded support/friction pads.

No activation, category or activity credit. A free world-prismatic axis,
identified original contacts, compatible geometry and quiet loaded poses are
not calibrated force/impulse measurements. Nothing launches or edits physics.
"""
import collections
import copy
from fractions import Fraction
import hashlib
import json
import math

from . import mechanism as m
from .. import passive

SCHEMA = 'simscene.structural_loads.v1'
KIND = 'gravity_loaded_support_pad'
THRESHOLDS = {'seating_steps', 'contact_tolerance_m', 'maximum_penetration_m',
              'guide_limit_margin_m', 'guide_frame_tolerance_m', 'maximum_support_tilt_degrees'}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_declarations(declarations):
    _require(isinstance(declarations, dict) and 0 < len(declarations) <= 16, 'declare 1..16 typed gravity-loaded pads')
    for body, cfg in declarations.items():
        fields = {'kind', 'guide_joint_id', 'support_body_id', 'support_motion_event',
                  'pad_part_index', 'support_part_index', 'gravity_direction_world', 'thresholds'}
        _require(isinstance(body, str) and body and isinstance(cfg, dict) and set(cfg) == fields, 'invalid structural-load declaration fields')
        _require(cfg['kind'] == KIND, 'unsupported structural load kind')
        _require(all(isinstance(cfg[k], str) and cfg[k] for k in ('guide_joint_id', 'support_body_id', 'support_motion_event')) and cfg['support_body_id'] != body, 'declare actual distinct pad/support/guide/event identifiers')
        _require(m.vector(cfg['gravity_direction_world']) and cfg['gravity_direction_world'] == [0, 0, -1], 'this frozen backend profile requires world -Z gravity')
        _require(all(cfg[k] is None or type(cfg[k]) is int and cfg[k] >= 0 for k in ('pad_part_index', 'support_part_index')), 'select explicit real Box parts, or null for a primitive Box')
        limits = cfg['thresholds']
        _require(isinstance(limits, dict) and set(limits) == THRESHOLDS, 'freeze every structural-load threshold')
        _require(type(limits['seating_steps']) is int and 1 <= limits['seating_steps'] <= 600, 'initial seating budget must be 1..600 original steps')
        _require(all(m.finite(v) and v > 0 for k, v in limits.items() if k != 'seating_steps'), 'positive finite structural-load limits required')
        _require(limits['maximum_penetration_m'] <= limits['contact_tolerance_m'] and
                 limits['guide_frame_tolerance_m'] * 2 < limits['guide_limit_margin_m'] and
                 limits['maximum_support_tilt_degrees'] <= 5, 'invalid conservative pad/guide/tilt limits')
    return declarations


def _q(value):
    _require(m.quaternion(value), 'finite normalized quaternion required')
    norm = math.hypot(*value)
    return [v / norm for v in value]


def _multiply(a, b):
    w, x, y, z = a; t, u, v, s = b
    return [w*t-x*u-y*v-z*s, w*u+x*t+y*s-z*v,
            w*v-x*s+y*t+z*u, w*s+x*v-y*u+z*t]


def _pose(sample, body):
    position = sample.get('positions', {}).get(m.path(body))
    rotation = sample.get('orientations_wxyz', {}).get(m.path(body))
    _require(m.vector(position), 'original measured dynamic pose is missing')
    return position, _q(rotation)


def _authored(obj):
    position = obj.get('position', [0, 0, 0]); rotation = _q(obj.get('orientation_wxyz', [1, 0, 0, 0]))
    _require(m.vector(position), 'finite authored position required')
    return position, rotation


def _physical(obj):
    if obj.get('kind') == 'compound':
        return not passive.validate_parts(obj) and any(part.get('collision', True) is True for part in obj['parts'])
    return obj.get('kind') == 'box' and obj.get('collision') is True


def _part(obj, index, single=False):
    if obj.get('kind') == 'box':
        _require(index is None and obj.get('collision') is True, 'primitive Box uses null part index and a real collider')
        part = {'kind': 'box', 'size': obj.get('size'), 'position': [0, 0, 0], 'orientation_wxyz': [1, 0, 0, 0]}
    else:
        _require(obj.get('kind') == 'compound' and not passive.validate_parts(obj) and type(index) is int and index < len(obj['parts']), 'select an existing valid compound part')
        part = obj['parts'][index]
        _require(part.get('kind') == 'box' and part.get('collision', True) is True, 'load contact patches must be actual colliding Box parts')
        if single:
            _require(sum(p.get('collision', True) is True for p in obj['parts']) == 1, 'pad admits exactly one Box collider; extra hidden supports are unsupported')
    _require(m.vector(part.get('size')) and min(part['size']) > 0, 'positive finite contact-patch dimensions required')
    _authored(part)
    return copy.deepcopy(part)


def _part_pose(pose, part):
    position, rotation = pose
    center = [a+b for a, b in zip(position, m.rotate(rotation, part.get('position', [0, 0, 0])))]
    return center, _q(_multiply(rotation, _q(part.get('orientation_wxyz', [1, 0, 0, 0]))))


def _clip(poly, axis, sign, bound):
    if not poly:
        return []
    output = []
    for a, b in zip(poly[-1:]+poly[:-1], poly):
        va, vb = sign*a[axis]-bound, sign*b[axis]-bound
        if (va <= 0) != (vb <= 0):
            t = va/(va-vb)
            output.append(tuple(x+t*(y-x) for x, y in zip(a, b)))
        if vb <= 0:
            output.append(b)
    return output


def _geometry(pad_pose, support_pose, pad_part, support_part, guide_origin, gravity):
    pc, pq = _part_pose(pad_pose, pad_part); sc, sq = _part_pose(support_pose, support_part)
    inverse = [sq[0], *[-v for v in sq[1:]]]
    half = [v/2 for v in pad_part['size']]
    points = []
    for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        world = [a+b for a, b in zip(pc, m.rotate(pq, [x*half[0], y*half[1], -half[2]]))]
        points.append(m.rotate(inverse, m.sub(world, sc)))
    sx, sy, sz = [v/2 for v in support_part['size']]
    polygon = [tuple(Fraction(v) for v in point[:2]) for point in points]
    for axis, sign, bound in ((0, 1, sx), (0, -1, sx), (1, 1, sy), (1, -1, sy)):
        polygon = _clip(polygon, axis, sign, Fraction(bound))
    normal = m.rotate(sq, [0, 0, 1]); pad_normal = m.rotate(pq, [0, 0, 1])
    up = [-v for v in gravity]
    top = [a+b for a, b in zip(sc, m.rotate(sq, [0, 0, sz]))]
    denominator = m.dot(normal, gravity)
    _require(abs(denominator) > .9, 'support surface is outside the near-horizontal load profile')
    height = m.dot(normal, m.sub(top, guide_origin))/denominator
    def tilt(axis):
        return math.degrees(math.acos(max(-1., min(1., m.dot(axis, up)))))
    return {'overlap': bool(polygon), 'minimum_initial_edge_margin_m': min(min(sx-abs(p[0]), sy-abs(p[1])) for p in points),
            'minimum_face_gap_m': min(p[2]-sz for p in points), 'maximum_face_gap_m': max(p[2]-sz for p in points),
            'support_tilt_degrees': tilt(normal), 'pad_tilt_degrees': tilt(pad_normal),
            'support_plane_gravity_coordinate_m': height}


def _guide_geometry(pose, guide, axis):
    anchor0 = guide.get('local_pos0', [0, 0, 0])
    anchor1 = [a+b for a, b in zip(pose[0], m.rotate(pose[1], guide.get('local_pos1', [0, 0, 0])))]
    delta = m.sub(anchor1, anchor0); coordinate = m.dot(delta, axis)
    off_axis = math.sqrt(sum((v-coordinate*d)**2 for v, d in zip(delta, axis)))
    return coordinate, off_axis, anchor0, anchor1


def _interior(coordinate, guide, margin):
    return ('lower_limit' not in guide or coordinate > guide['lower_limit']+margin) and ('upper_limit' not in guide or coordinate < guide['upper_limit']-margin)


def bind(spec, declarations, path_bodies, quiet_limits):
    validate_declarations(declarations)
    _require(isinstance(path_bodies, (set, frozenset, list, tuple)) and not (set(declarations) & set(path_bodies)), 'a load pad can never be a task path/activity/category body')
    _require(not spec.get('drivers') and not spec.get('followers'), 'active scene drivers/followers invalidate gravity-only support proof')
    _require(spec.get('world', {}).get('up_axis', 'Z') == 'Z' and spec.get('world', {}).get('units', 'm') == 'm', 'this load profile uses metric world -Z backend coordinates')
    objects = spec['objects']; loads = {}
    _require(len({m.path(n) for n in objects}) == len(objects), 'distinct object IDs cannot alias an exported prim path')
    for body, cfg in declarations.items():
        support = cfg['support_body_id']; pad = objects.get(body, {}); target = objects.get(support, {})
        _require(support in path_bodies and support not in declarations, 'load target must be an existing real task-path body')
        for name, obj in ((body, pad), (support, target)):
            _require(obj.get('dynamic') is True and _physical(obj) and not obj.get('spawn_step', 0), 'pad/support must be initially present real dynamic collision geometry')
            _require(not any(obj.get(k) for k in ('pose_follower', 'conveyor', 'rigid_attachment', 'kinematic', 'kinematic_enabled', 'driver', 'drive', 'motor', 'force', 'external_force', 'external_forces', 'surface_velocity', 'disable_gravity')), 'active/kinematic pad or support is forbidden')
            _require(name in quiet_limits and set(quiet_limits[name]) == {'maximum_motion_m', 'maximum_rotation_degrees'} and all(m.finite(v) and v > 0 for v in quiet_limits[name].values()), 'both pad/support need real frozen quiet budgets')
            _require('mass_kg' in obj and m.finite(obj['mass_kg']) and obj['mass_kg'] > 0, 'pad/support mass must be explicit and positive')
            _require(not obj.get('physics') or not passive.validate_physics(obj), 'pad/support physics must use supported passive settings')
        pp = _part(pad, cfg['pad_part_index'], single=True); sp = _part(target, cfg['support_part_index'])
        limits = cfg['thresholds']; tolerance = limits['guide_frame_tolerance_m']
        _require(limits['contact_tolerance_m'] <= min(pp['size'][2], sp['size'][2])/4, 'contact tolerance cannot replace real contact-patch geometry')
        connected = [(n, o) for n, o in objects.items() if o.get('kind') == 'joint' and body in (o.get('joint', {}).get('body0'), o.get('joint', {}).get('body1'))]
        _require(len(connected) == 1 and connected[0][0] == cfg['guide_joint_id'], 'pad admits exactly one joint, with no hidden load bypass')
        guide_obj = connected[0][1]; guide = guide_obj.get('joint', {})
        _require(not passive.validate_joint(spec, guide_obj) and guide.get('type') == 'prismatic' and guide.get('enabled', True) is True and guide.get('body0') is None and guide.get('body1') == body, 'pad guide must be one enabled passive world prismatic')
        local_axis = {'X': [1, 0, 0], 'Y': [0, 1, 0], 'Z': [0, 0, 1]}[guide.get('axis', 'X')]
        axis = m.rotate(_q(guide.get('local_rot0_wxyz', [1, 0, 0, 0])), local_axis)
        _require(abs(m.dot(axis, cfg['gravity_direction_world'])) >= 1-1e-8, 'guide must remain free along gravity, not clamp that direction')
        pad_pose, support_pose = _authored(pad), _authored(target)
        q0 = _q(guide.get('local_rot0_wxyz', [1, 0, 0, 0])); q1 = _multiply(pad_pose[1], _q(guide.get('local_rot1_wxyz', [1, 0, 0, 0])))
        _require(m.angle_degrees(q0, q1) <= .001, 'prismatic initial rotation frames must align without preload')
        coordinate, off_axis, anchor0, _ = _guide_geometry(pad_pose, guide, axis)
        _require(off_axis <= tolerance and _interior(coordinate, guide, limits['guide_limit_margin_m']), 'pad initial guide must be aligned and away from either gravity-carrying limit')
        geometry = _geometry(pad_pose, support_pose, pp, sp, anchor0, cfg['gravity_direction_world'])
        required_margin = quiet_limits[body]['maximum_motion_m']+quiet_limits[support]['maximum_motion_m']+2*tolerance
        _require(geometry['minimum_initial_edge_margin_m'] >= required_margin, 'full initial pad footprint must fit the real support with BOTH quiet budgets plus two frame tolerances on every edge')
        _require(max(geometry['support_tilt_degrees'], geometry['pad_tilt_degrees']) <= limits['maximum_support_tilt_degrees'], 'initial contact faces must oppose gravity within declared tilt')
        _require(geometry['minimum_face_gap_m'] >= -limits['maximum_penetration_m'] and geometry['maximum_face_gap_m'] <= quiet_limits[body]['maximum_motion_m'], 'initial seating gap/penetration is not compatible with the frozen quiet budget')
        loads[body] = {'support_body_id': support, 'support_motion_event': cfg['support_motion_event'], 'guide_joint_id': cfg['guide_joint_id'],
            'pad_part': pp, 'support_part': sp, 'guide': copy.deepcopy(guide), 'guide_axis_world': axis,
            'initial_pad_pose': pad_pose, 'initial_support_pose': support_pose, 'initial_geometry': geometry,
            'required_full_overlap_margin_m': required_margin, 'actual_full_overlap_margin_m': geometry['minimum_initial_edge_margin_m']}
    return {'body_ids': sorted(declarations), 'loads': loads, 'path_bodies': sorted(path_bodies),
            'quiet_limits': copy.deepcopy(quiet_limits), 'declarations_sha256': _sha(declarations),
            'scope': 'Only explicitly bound pad IDs are admitted; no graph traversal, category/activity or force-sensor credit.'}


def _mass_valid(value, authored_mass, count):
    matrix = value.get('inertia_at_com_in_prim_axes_kg_m2')
    valid = isinstance(matrix, list) and len(matrix) == 3 and all(m.vector(row) for row in matrix)
    if valid:
        symmetric = all(math.isclose(matrix[i][j], matrix[j][i], rel_tol=1e-5, abs_tol=1e-8) for i in range(3) for j in range(3))
        a, b, c = [[(Fraction(matrix[i][j])+Fraction(matrix[j][i]))/2 for j in range(3)] for i in range(3)]
        determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
        valid = symmetric and a[0] > 0 and a[0]*b[1]-a[1]*b[0] > 0 and determinant > 0
    observed = value.get('observed_at_physics_step')
    return bool(valid and m.finite(value.get('mass_kg')) and value['mass_kg'] > 0 and math.isclose(value['mass_kg'], authored_mass, rel_tol=1e-5, abs_tol=1e-9) and m.vector(value.get('center_of_mass_local_m')) and m.quaternion(value.get('principal_axes_local_wxyz')) and type(observed) is int and 0 <= observed <= count and isinstance(value.get('source'), str) and value['source'].startswith('PhysX tensor readback'))


def _patch_collider(body, obj, index):
    return m.path(body) if obj['kind'] == 'box' else m.path(body)+'/part_'+str(index)+'/Shape'


def _at_patch(value, expected):
    return isinstance(value, str) and (value == expected or value.startswith(expected+'/'))


def _coherent_guide(pose, state, guide, axis, tolerance):
    coordinate, off_axis, anchor0, anchor1 = _guide_geometry(pose, guide, axis)
    q0 = _q(guide.get('local_rot0_wxyz', [1, 0, 0, 0]))
    q1 = _multiply(pose[1], _q(guide.get('local_rot1_wxyz', [1, 0, 0, 0])))
    valid = state.get('type') == 'prismatic' and state.get('enabled') is True and state.get('drive_present') is False
    valid = valid and m.finite(state.get('position_m')) and abs(state['position_m']-coordinate) <= tolerance
    valid = valid and m.finite(state.get('anchor_error_m')) and state['anchor_error_m'] >= 0 and abs(state['anchor_error_m']-off_axis) <= tolerance
    valid = valid and m.vector(state.get('anchor0_world_m')) and m.vector(state.get('anchor1_world_m'))
    valid = valid and math.dist(state['anchor0_world_m'], anchor0) <= tolerance and math.dist(state['anchor1_world_m'], anchor1) <= tolerance
    valid = valid and off_axis <= tolerance and m.angle_degrees(q0, q1) <= .001
    return valid


def _contact_index(run, declarations, journal):
    _require(journal.get('passed') is True and isinstance(journal.get('records'), list), 'complete original callback journal required')
    bodies = set(declarations); source = collections.Counter(); supplied = collections.Counter(); index = collections.defaultdict(list)
    for sample in run['samples']:
        _require(isinstance(sample.get('contact_pairs'), list), 'every original step must carry actual callback observations')
        for record in sample['contact_pairs']:
            _require(isinstance(record, dict) and isinstance(record.get('body_ids'), list), 'invalid original contact record')
            if not bodies.intersection(record['body_ids']):
                continue
            source[_sha([sample['physics_steps'], record])] += 1
            index[sample['physics_steps']].append(record)
    for record in journal['records']:
        if not bodies.intersection(record.get('body_ids', [])):
            continue
        step = record.get('observation_step'); _require(type(step) is int and 1 <= step <= len(run['samples']), 'callback journal has nonoriginal step')
        _require(record.get('observation_absolute_step') == run['samples'][step-1]['absolute_physics_step'], 'callback journal boundary differs from original step')
        raw = {k: v for k, v in record.items() if k not in ('observation_step', 'observation_absolute_step')}
        supplied[_sha([step, raw])] += 1
    _require(source == supplied, 'pad callback journal must equal original per-step records, not fabricated/persistent aggregate contacts')
    return index


def evaluate(run, spec, declarations, binding_context, events, journal, dt):
    result = {'schema': SCHEMA, 'passed': False, 'loads': {}, 'errors': [],
              'normal_force_measured': False, 'gravity_compatible_evidence_only': True,
              'activity_or_category_credit': False, 'formal_stage_accepted': False,
              'guide_axis_limits_source': 'Frozen authored model; loaded type/endpoints/enabled/drives and measured pose/frame coherence are checked. Full original stage/configuration review and locks remain required.'}
    try:
        binding = bind(spec, declarations, binding_context['path_bodies'], binding_context['quiet_limits'])
        _require(binding['body_ids'] == binding_context['body_ids'] and binding['declarations_sha256'] == binding_context['declarations_sha256'], 'structural binding/declarations changed')
        timeline = m.timeline(run, spec, dt); strict = m.strict_initial_state(run, spec, {'require_strict_initial_state': True}, dt)
        result['timeline'] = timeline; result['strict_initial_state'] = strict
        _require(timeline['passed'] and strict['passed'], 'complete unchanged original strict timeline/tensor data required')
        _require(run.get('contacts_truncated') is False and spec.get('observation', {}).get('record_contact_pairs') is True, 'nontruncated per-step contact capture required')
        contacts = _contact_index(run, declarations, journal)
        loaded = run.get('mechanism_configuration', {}); actual_joints = loaded.get('joints', [])
        for body, cfg in declarations.items():
            context = binding['loads'][body]; support = context['support_body_id']; guide = context['guide']; axis = context['guide_axis_world']
            limits = cfg['thresholds']; tolerance = limits['guide_frame_tolerance_m']; quiet = binding['quiet_limits']
            mass = loaded.get('mass_properties_by_prim_path', {}).get(m.path(body), {})
            checks = {'cooked_mass_com_inertia_positive': _mass_valid(mass, spec['objects'][body]['mass_kg'], run['actual_physics_steps'])}
            checks['cooked_support_mass_com_inertia_positive'] = _mass_valid(loaded.get('mass_properties_by_prim_path', {}).get(m.path(support), {}), spec['objects'][support]['mass_kg'], run['actual_physics_steps'])
            if checks['cooked_mass_com_inertia_positive']:
                part = context['pad_part']; center, rotation = _authored(part)
                local_com = m.rotate([rotation[0], *[-v for v in rotation[1:]]], m.sub(mass['center_of_mass_local_m'], center))
                checks['cooked_com_inside_only_pad_collider'] = all(abs(v) < size/2 for v, size in zip(local_com, part['size']))
            else:
                checks['cooked_com_inside_only_pad_collider'] = False
            attached = [j for j in actual_joints if m.path(body) in j.get('body0', [])+j.get('body1', [])]
            checks['one_loaded_passive_world_gravity_guide'] = len(attached) == 1 and attached[0].get('path') == m.path(cfg['guide_joint_id']) and attached[0].get('type') == 'PhysicsPrismaticJoint' and attached[0].get('enabled') is True and attached[0].get('body0') == [] and attached[0].get('body1') == [m.path(body)] and attached[0].get('drives') == [] and attached[0].get('drive_attributes') == []
            settings = loaded.get('body_settings', {}).get(body, {})
            checks['no_reported_kinematic_or_disabled_gravity'] = not any(settings.get(k) for k in ('kinematic', 'kinematic_enabled', 'disable_gravity'))
            failures = []; missing_contacts = []; unrelated = []; rows = []; retired = False; loss_step = None; certified = 0
            initial_pad = _pose(run['initial_observation'], body)
            initial_support = _pose(run['initial_observation'], support)
            checks['same_t0_guide_frame_identity'] = _coherent_guide(initial_pad, run['initial_observation'].get('joints', {}).get(cfg['guide_joint_id'], {}), guide, axis, tolerance)
            baseline_height = context['initial_geometry']['support_plane_gravity_coordinate_m']
            motion_event = events.get(cfg['support_motion_event'])
            _require(isinstance(motion_event, dict) and (motion_event.get('onset_step') is None or type(motion_event['onset_step']) is int and 1 <= motion_event['onset_step'] <= run['actual_physics_steps']), 'declared real support motion event is missing or outside the original task clock')
            for sample in run['samples']:
                step = sample['physics_steps']; pad_pose = _pose(sample, body); support_pose = _pose(sample, support)
                coordinate, off_axis, anchor0, anchor1 = _guide_geometry(pad_pose, guide, axis)
                state = sample.get('joints', {}).get(cfg['guide_joint_id'], {})
                coherent = _coherent_guide(pad_pose, state, guide, axis, tolerance)
                if not coherent:
                    failures.append({'step': step, 'reason': 'guide state/frame/pose mismatch or active guide'})
                geometry = _geometry(pad_pose, support_pose, context['pad_part'], context['support_part'], anchor0, cfg['gravity_direction_world'])
                records = [r for r in contacts.get(step, []) if body in r.get('body_ids', [])]
                same = []
                for record in records:
                    ids = record.get('body_ids', []); others = [n for n in ids if n != body]
                    if len(ids) != 2 or len(others) != 1 or others[0] != support:
                        unrelated.append({'step': step, 'body_ids': ids}); continue
                    first, last = record.get('first_callback_absolute_physics_step'), record.get('last_callback_absolute_physics_step')
                    valid = type(record.get('count')) is int and record['count'] > 0 and type(first) is int and type(last) is int and sample['absolute_physics_step']-1 <= first <= last <= sample['absolute_physics_step']
                    valid = valid and isinstance(record.get('actor_paths'), list) and len(record['actor_paths']) == 2 and isinstance(record.get('collider_paths'), list) and len(record['collider_paths']) == 2
                    if valid:
                        valid = all(isinstance(actor, str) and (actor == m.path(n) or actor.startswith(m.path(n)+'/')) and (collider is None or isinstance(collider, str) and (collider == m.path(n) or collider.startswith(m.path(n)+'/'))) for n, actor, collider in zip(ids, record['actor_paths'], record['collider_paths']))
                        valid = valid and all(_at_patch(collider, _patch_collider(n, spec['objects'][n], cfg['pad_part_index'] if n == body else cfg['support_part_index'])) for n, collider in zip(ids, record['collider_paths']))
                        valid = valid and ('minimum_separation_m' not in record or m.finite(record['minimum_separation_m']) and record['minimum_separation_m'] >= -limits['maximum_penetration_m'])
                    if valid:
                        same.append(record)
                    else:
                        failures.append({'step': step, 'reason': 'invalid original identified support callback'})
                if not geometry['overlap'] and not retired:
                    onset = motion_event.get('onset_step')
                    progress = math.dist(support_pose[0], initial_support[0]) > quiet[support]['maximum_motion_m'] or m.angle_degrees(support_pose[1], initial_support[1]) > quiet[support]['maximum_rotation_degrees']
                    if not (type(onset) is int and onset <= step and progress):
                        failures.append({'step': step, 'reason': 'premature support loss without real task-support motion'})
                    retired = True; loss_step = step
                if retired:
                    phase = 'geometrically_clear_retired'
                    if geometry['overlap']:
                        failures.append({'step': step, 'reason': 'unsupported reentry after one-way support loss'})
                else:
                    phase = 'initial_seating' if step <= limits['seating_steps'] else 'supported'
                    compatible = _interior(coordinate, guide, limits['guide_limit_margin_m']) and math.dist(pad_pose[0], initial_pad[0]) <= quiet[body]['maximum_motion_m'] and m.angle_degrees(pad_pose[1], initial_pad[1]) <= quiet[body]['maximum_rotation_degrees']
                    compatible = compatible and max(geometry['support_tilt_degrees'], geometry['pad_tilt_degrees']) <= limits['maximum_support_tilt_degrees'] and abs(geometry['support_plane_gravity_coordinate_m']-baseline_height) <= quiet[support]['maximum_motion_m']
                    compatible = compatible and geometry['minimum_face_gap_m'] >= -limits['maximum_penetration_m']
                    if phase == 'supported':
                        compatible = compatible and geometry['maximum_face_gap_m'] <= limits['contact_tolerance_m']
                        if not same:
                            missing_contacts.append(step)
                        if compatible and same:
                            certified += 1
                    if not compatible:
                        failures.append({'step': step, 'reason': 'load pose/quiet/face-gap/tilt/interior-guide evidence incompatible'})
                rows.append({'physics_step': step, 'absolute_physics_step': sample['absolute_physics_step'], 'phase': phase,
                             'guide_position_m_from_measured_pose': coordinate, 'support_callback_records': len(same), **geometry})
            checks['all_original_steps_examined'] = len(rows) == run['actual_physics_steps']
            checks['gravity_compatible_quiet_and_interior_guide'] = not failures
            checks['actual_support_callback_every_certified_step'] = not missing_contacts
            checks['no_unrelated_contacts_or_hidden_load_path'] = not unrelated
            checks['real_nonempty_loaded_phase'] = certified >= 2
            result['loads'][body] = {'passed': all(checks.values()), 'checks': checks, 'certified_support_steps': certified,
                'geometric_support_loss_step': loss_step, 'required_initial_full_overlap_margin_m': context['required_full_overlap_margin_m'],
                'actual_initial_full_overlap_margin_m': context['actual_full_overlap_margin_m'],
                'missing_supported_contact_steps': missing_contacts, 'unrelated_contacts': unrelated,
                'failures': failures, 'per_step_geometry': rows, 'force_scope': 'Gravity-compatible geometry/quiet/free-guide/contact evidence only; no normal-force, friction-force or impulse sensor is claimed.'}
        result['passed'] = bool(result['loads']) and all(value['passed'] for value in result['loads'].values())
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
        result['errors'].append({'type': type(error).__name__, 'reason': str(error)})
    return result
