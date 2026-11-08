"""Read-only acceptance of frozen passive-mechanism runs.

P1 geometry is evidence of a straightened segmented rope, not a force sensor.
The isolated detached-end control supplies the additional causal evidence.
Contact count/first/last summaries never supply a connected body's activation
time here. Event mechanisms accept a contact-summary endpoint only when that
actual endpoint falls inside the independently measured handoff window.

The optional activity case freezes events, task phases, bodies, speed floors
and world ROIs before a run. All durations use original simulation time and
the union of measured per-step flags. Camera transforms are never inspected.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


SCHEMA = 'simscene.mechanism.v1'
PAIRED_MANIFEST_FIELDS = (
    'worker_code_sha256', 'seed', 'requested_physics_steps', 'physics_dt_s',
    'physics_device', 'runtime_python', 'runtime_python_sha256',
    'queue_launcher_python', 'queue_launcher_python_sha256', 'runtime_version',
    'gpu_selection', 'continue_on_controller_error', 'archive_verified_objects',
)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, length=3):
    return isinstance(value, list) and len(value) == length and all(finite(v) for v in value)


def quaternion(value):
    return vector(value, 4) and abs(sum(v*v for v in value)-1) <= .001


def positive_mass(obj):
    # Omitted mass uses the simulator's computed mass; mass_kg is the API key.
    value = obj.get('mass_kg', 1)
    return finite(value) and value > 0


def path(name):
    return '/World/' + name.replace('-', '_')


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def sub(a, b):
    return [x-y for x, y in zip(a, b)]


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def rotate(q, point):
    # Unit quaternion rotation without an Isaac/USD dependency.
    t = [2*v for v in cross(q[1:], point)]
    return [p+q[0]*a+b for p, a, b in zip(point, t, cross(q[1:], t))]


def unit(value):
    return vector(value) and abs(dot(value, value)-1) <= .001


def angle_degrees(a, b):
    norm_product = math.sqrt(dot(a, a)*dot(b, b))
    if not finite(norm_product) or norm_product <= 0:
        raise ValueError('angle measurement requires finite nonzero quaternions')
    return math.degrees(2*math.acos(min(1., max(0., abs(dot(a, b))/norm_product))))


def pose(sample, spec, name):
    obj = spec['objects'][name]
    if obj.get('dynamic'):
        return sample['positions'][path(name)], sample['orientations_wxyz'][path(name)]
    return obj.get('position', [0, 0, 0]), obj.get('orientation_wxyz', [1, 0, 0, 0])


def validate_case(case):
    if not isinstance(case, dict) or case.get('schema') != SCHEMA:
        raise ValueError('expected ' + SCHEMA)
    if case.get('mechanism') in ('spoon_sugar', 'wheel_door_bridge'):
        return validate_event_case(case)
    if case.get('mechanism') != 'rope_drawer':
        raise ValueError('unsupported passive mechanism')
    if case.get('rope_model') not in ('segmented_over_free_pulley', 'segmented_direct'):
        raise ValueError('rope_model must explicitly identify segmented wrapped/direct rope')
    if not isinstance(case.get('trigger_id'), str) or type(case.get('release_step')) is not int or case['release_step'] < 0:
        raise ValueError('trigger_id and nonnegative release_step required')
    roles = case.get('roles', {})
    joints = case.get('joints', {})
    wrapped = case['rope_model'] == 'segmented_over_free_pulley'
    for key in ('weight', 'drawer') + (('pulley',) if wrapped else ()):
        if not isinstance(roles.get(key), str) or not roles[key]:
            raise ValueError('missing body role ' + key)
    for key in ('drawer', 'drawer_end') + (('pulley',) if wrapped else ()):
        if not isinstance(joints.get(key), str) or not joints[key]:
            raise ValueError('missing joint role ' + key)
    rope = case.get('rope', {})
    segments = rope.get('segment_ids', [])
    chain = rope.get('joint_ids', [])
    if not isinstance(segments, list) or len(segments) < 3 or len(set(segments)) != len(segments):
        raise ValueError('rope requires at least three distinct physical segments')
    if not isinstance(chain, list) or len(chain) != len(segments)+1 or len(set(chain)) != len(chain) or chain[0] != joints['drawer_end']:
        raise ValueError('ordered joint_ids must connect drawer, all segments, weight')
    partition_mode = rope.get('partition_mode', 'frozen_indices')
    if partition_mode not in ('frozen_indices', 'rim_geometry') or partition_mode == 'rim_geometry' and not wrapped:
        raise ValueError('rim_geometry requires the segmented free-pulley claim')
    spans = rope.get('free_spans', [])
    if not isinstance(spans, list) or partition_mode == 'frozen_indices' and not spans:
        raise ValueError('freeze one or more free-span node ranges')
    for span in spans:
        if not isinstance(span, list) or len(span) != 2 or any(type(i) is not int for i in span) or not 0 <= span[0] < span[1] < len(chain):
            raise ValueError('invalid free-span node range')
    if case['rope_model'] == 'segmented_over_free_pulley':
        span = rope.get('wrap_span')
        if not isinstance(span, list) or len(span) != 2 or any(type(i) is not int for i in span) or not 0 <= span[0] < span[1]-1 < len(chain)-1:
            raise ValueError('wrap_span needs at least three measured rope nodes')
        if rope.get('axle_local_axis') not in ('X', 'Y', 'Z'):
            raise ValueError('freeze the pulley axle local axis')
        for key in ('pulley_radius_m', 'minimum_wrap_degrees', 'radial_tolerance_m', 'axial_tolerance_m'):
            if not finite(rope.get(key)) or rope[key] <= 0:
                raise ValueError('invalid wrap geometry ' + key)
        if not 45 <= rope['minimum_wrap_degrees'] <= 270:
            raise ValueError('wrap coverage must be 45..270 degrees')
    partitions = spans + ([rope['wrap_span']] if case['rope_model'] == 'segmented_over_free_pulley' else [])
    edges = [i for a, b in partitions for i in range(a, b)]
    if partition_mode == 'frozen_indices' and sorted(edges) != list(range(len(chain)-1)):
        raise ValueError('free spans and wrap span must partition the entire measured chain')
    limits = case.get('thresholds', {})
    for key in ('slack_min_excess_m', 'taut_max_excess_m', 'slack_drawer_max_m', 'drawer_min_travel_m', 'weight_min_drop_m', 'weight_slack_min_drop_m', 'pulley_min_rotation_degrees', 'max_anchor_error_m', 'max_off_axis_m'):
        if not finite(limits.get(key)) or limits[key] <= 0:
            raise ValueError('freeze a positive threshold ' + key)
    if limits['slack_min_excess_m'] <= limits['taut_max_excess_m'] or limits['drawer_min_travel_m'] <= limits['slack_drawer_max_m']:
        raise ValueError('slack/taut and motion/no-motion thresholds must be separated')
    for key in ('slack_min_steps', 'taut_hold_steps'):
        if type(limits.get(key)) is not int or limits[key] < 2:
            raise ValueError('freeze at least two steps for ' + key)
    if not unit(case.get('drawer_axis_world')):
        raise ValueError('drawer_axis_world must be a normalized signed XYZ vector')
    return case


def timeline(run, spec, dt=1/60):
    samples = run.get('samples', [])
    count = run.get('actual_physics_steps')
    checks = {
        'complete_run': type(count) is int and count > 0 and count == run.get('requested_physics_steps') and not run.get('partial') and not run.get('evidence_incomplete') and run.get('task_status') != 'failed',
        'per_step_observation_requested': spec.get('observation', {}).get('sample_interval_steps') == 1 and run.get('observation_interval_steps') == 1,
        'every_physics_step_present': isinstance(samples, list) and type(count) is int and len(samples) == count and all(isinstance(s, dict) and type(s.get('physics_steps')) is int and s['physics_steps'] == i for i, s in enumerate(samples, 1)),
        'original_simulation_clock': bool(samples) and all(finite(s.get('simulation_time_s')) and abs(s['simulation_time_s']-s.get('physics_steps', -1)*dt) <= max(1e-6, dt*1e-4) for s in samples) and finite(run.get('simulation_time_s')) and type(count) is int and abs(run['simulation_time_s']-count*dt) <= max(1e-6, dt*1e-4),
    }
    missing = []
    for name, obj in spec.get('objects', {}).items():
        if not obj.get('dynamic'):
            continue
        # Worker spawns at the step boundary; the next completed step is mandatory.
        start = obj.get('spawn_step', 0)
        for sample in samples:
            if sample.get('physics_steps', 0) <= start:
                continue
            if not vector(sample.get('positions', {}).get(path(name))) or not quaternion(sample.get('orientations_wxyz', {}).get(path(name))):
                missing.append({'body': name, 'step': sample.get('physics_steps')})
                break
    checks['all_dynamic_body_poses_complete'] = not missing
    return {'passed': all(checks.values()), 'checks': checks, 'missing_body_poses': missing, 'physics_dt_s': dt}


def strict_initial_state(run, spec, case, dt=1/60):
    """Check one measured, restored t0; legacy runs retain their old scope."""
    requested = case.get('require_strict_initial_state', False)
    configured = spec.get('observation', {}).get('strict_start', False)
    flags_valid = type(requested) is bool and type(configured) is bool
    required = bool(requested or configured) or not flags_valid
    report = {'required': required, 'passed': True, 'checks': {}, 'scope': 'Legacy task samples 1..N; no same-boundary restored sample0 was requested.'}
    if not required:
        return report
    report['scope'] = 'Measured tensor sample0 after one initialization restore and before task motion; absolute counters and times must agree through every task step. Warmup counter/time deltas are reported without inventing task observations.'
    checks = report['checks']
    checks['strict_initial_flags_are_boolean'] = flags_valid
    checks['strict_initial_mode_enabled'] = configured is True
    initial, reset = run.get('initial_observation'), run.get('initialization_reset')
    checks['strict_initial_snapshot_and_reset_present'] = isinstance(initial, dict) and isinstance(reset, dict)
    if not checks['strict_initial_snapshot_and_reset_present']:
        report['passed'] = False
        return report
    bodies = {n: o for n, o in spec.get('objects', {}).items() if o.get('dynamic') and not o.get('spawn_step', 0)}
    expected = {path(n): o for n, o in bodies.items()}
    checks['strict_initial_body_paths_are_unique'] = len(expected) == len(bodies)
    identifiers, paths = reset.get('body_ids'), reset.get('body_paths')
    checks['strict_initial_reset_covers_all_initial_bodies'] = isinstance(identifiers, list) and all(isinstance(n, str) for n in identifiers) and len(identifiers) == len(bodies) and set(identifiers) == set(bodies) and isinstance(paths, list) and all(isinstance(n, str) for n in paths) and len(paths) == len(expected) and set(paths) == set(expected)
    maps = ('positions', 'orientations_wxyz', 'linear_velocities_m_s', 'angular_velocities_rad_s')
    checks['strict_initial_tensor_maps_complete'] = all(isinstance(initial.get(k), dict) and set(initial[k]) == set(expected) for k in maps)
    if checks['strict_initial_tensor_maps_complete']:
        checks['strict_initial_tensor_values_finite'] = all(vector(initial['positions'][p]) and quaternion(initial['orientations_wxyz'][p]) and vector(initial['linear_velocities_m_s'][p]) and vector(initial['angular_velocities_rad_s'][p]) for p in expected)
    else:
        checks['strict_initial_tensor_values_finite'] = False
    checks['strict_initial_single_restore_before_task'] = reset.get('applied') is True and reset.get('phase') == 'before_task_start' and type(reset.get('reset_count')) is int and reset['reset_count'] == 1 and reset.get('setters_during_task') is False
    checks['strict_initial_no_followers'] = initial.get('followers') == {} and not run.get('followers')
    checks['strict_initial_relative_zero'] = type(initial.get('physics_steps')) is int and initial['physics_steps'] == 0 and finite(initial.get('simulation_time_s')) and initial['simulation_time_s'] == 0
    zero_step, zero_time = run.get('run_zero_absolute_physics_step'), run.get('run_zero_absolute_simulation_time_s')
    checks['strict_initial_absolute_zero_declared'] = type(zero_step) is int and zero_step >= 0 and finite(zero_time) and zero_time >= 0
    def same_counter_time(record, step_key, time_key):
        return checks['strict_initial_absolute_zero_declared'] and type(record.get(step_key)) is int and record[step_key] == zero_step and finite(record.get(time_key)) and abs(record[time_key]-zero_time) <= 1e-9
    checks['strict_initial_snapshot_matches_task_zero'] = same_counter_time(initial, 'absolute_physics_step', 'absolute_simulation_time_s')
    checks['strict_initial_restore_matches_task_zero'] = same_counter_time(reset, 'absolute_physics_step', 'absolute_simulation_time_s')
    checks['strict_initial_paused_warmup_did_not_advance_after_restore'] = same_counter_time(reset, 'after_warmup_absolute_physics_step', 'after_warmup_absolute_simulation_time_s')
    before_step, before_time = reset.get('before_warmup_absolute_physics_step'), reset.get('before_warmup_absolute_simulation_time_s')
    checks['strict_initial_warmup_boundary_recorded'] = checks['strict_initial_absolute_zero_declared'] and type(before_step) is int and 0 <= before_step <= zero_step and finite(before_time) and 0 <= before_time <= zero_time+1e-9
    joint_cfgs = {n: o.get('joint', {}) for n, o in spec['objects'].items() if o.get('kind') == 'joint'}
    def complete_joints(values):
        return isinstance(values, dict) and set(values) == set(joint_cfgs) and all(
            isinstance(values[n], dict) and values[n].get('type') == cfg.get('type') and values[n].get('enabled') is cfg.get('enabled', True) and values[n].get('drive_present') is False and finite(values[n].get('anchor_error_m')) and values[n]['anchor_error_m'] >= 0 and vector(values[n].get('anchor0_world_m')) and vector(values[n].get('anchor1_world_m')) and (cfg.get('type') not in ('prismatic', 'revolute') or finite(values[n].get('position_m' if cfg['type'] == 'prismatic' else 'angle_degrees')))
            for n, cfg in joint_cfgs.items())
    checks['strict_initial_joint_frames_complete'] = complete_joints(initial.get('joints'))
    checks['strict_initial_joints_match_same_zero'] = isinstance(initial.get('joints'), dict) and initial['joints'] == run.get('initial_joint_states')
    limits = {'authored_pose_readback_max_error_m': 1e-6, 'max_quaternion_error': 1e-6, 'max_linear_speed_m_s': 1e-7, 'max_angular_speed_rad_s': 1e-7,
              'authored_orientation_readback_max_error_degrees': math.degrees(4*math.asin(1e-6/2))+1e-6}
    checks['strict_initial_reset_readback_errors_bounded'] = all(finite(reset.get(k)) and 0 <= reset[k] <= limit for k, limit in limits.items())
    if checks['strict_initial_tensor_values_finite']:
        metrics = {'authored_pose_readback_max_error_m': 0., 'max_quaternion_error': 0., 'authored_orientation_readback_max_error_degrees': 0., 'max_linear_speed_m_s': 0., 'max_angular_speed_rad_s': 0.}
        for p, obj in expected.items():
            desired_position = obj.get('position', [0, 0, 0])
            desired_q = obj.get('orientation_wxyz', [1, 0, 0, 0])
            if not vector(desired_position) or not quaternion(desired_q):
                raise ValueError('strict initial authored poses must be finite and normalized')
            q = initial['orientations_wxyz'][p]
            values = {'authored_pose_readback_max_error_m': math.dist(initial['positions'][p], desired_position), 'max_quaternion_error': min(math.dist(q, desired_q), math.dist(q, [-v for v in desired_q])), 'authored_orientation_readback_max_error_degrees': angle_degrees(q, desired_q), 'max_linear_speed_m_s': math.sqrt(dot(initial['linear_velocities_m_s'][p], initial['linear_velocities_m_s'][p])), 'max_angular_speed_rad_s': math.sqrt(dot(initial['angular_velocities_rad_s'][p], initial['angular_velocities_rad_s'][p]))}
            for k, value in values.items():
                metrics[k] = max(metrics[k], value)
        report['independent_readback_errors'] = metrics
        checks['strict_initial_measured_state_matches_authored_zero_velocity'] = all(value <= limits[k] for k, value in metrics.items())
    else:
        checks['strict_initial_measured_state_matches_authored_zero_velocity'] = False
    clock_complete, bodies_complete, joints_complete = True, True, True
    for sample in run.get('samples', []):
        step, time_s = sample.get('physics_steps'), sample.get('simulation_time_s')
        clock_complete = clock_complete and checks['strict_initial_absolute_zero_declared'] and type(step) is int and type(sample.get('absolute_physics_step')) is int and sample['absolute_physics_step'] == zero_step+step and finite(time_s) and finite(sample.get('absolute_simulation_time_s')) and abs(sample['absolute_simulation_time_s']-zero_time-time_s) <= max(1e-6, dt*1e-4)
        active = {path(n) for n, obj in spec['objects'].items() if obj.get('dynamic') and obj.get('spawn_step', 0) < (step if type(step) is int else -1)}
        bodies_complete = bodies_complete and all(isinstance(sample.get(k), dict) and set(sample[k]) == active for k in maps)
        if bodies_complete:
            bodies_complete = all(vector(sample['positions'][p]) and quaternion(sample['orientations_wxyz'][p]) and vector(sample['linear_velocities_m_s'][p]) and vector(sample['angular_velocities_rad_s'][p]) for p in active)
        joints_complete = joints_complete and complete_joints(sample.get('joints', {}))
    checks['strict_initial_every_task_absolute_boundary_consistent'] = bool(run.get('samples')) and clock_complete
    checks['strict_initial_every_task_tensor_state_complete'] = bool(run.get('samples')) and bodies_complete
    checks['strict_initial_every_task_joint_frame_complete'] = bool(run.get('samples')) and joints_complete
    report['passed'] = all(checks.values())
    return report


def baseline_observation(run, spec):
    return run['initial_observation'] if spec.get('observation', {}).get('strict_start') is True else run['samples'][0]


def passive_checks(run, spec, case):
    objects = spec.get('objects', {})
    release = case['release_step']
    scheduled = {n for n, o in objects.items() if o.get('spawn_step', 0) > 0}
    allowed = {case['trigger_id']} if release else set()
    active_keys = ('pose_follower', 'conveyor', 'driver', 'drive', 'motor', 'kinematic')
    checks = {
        'no_active_body_motion': not run.get('followers') and not spec.get('drivers') and not spec.get('followers') and all(not any(o.get(key) for key in active_keys) for o in objects.values()) and all(not s.get('followers') for s in run.get('samples', [])),
        'only_frozen_initial_release': scheduled == allowed and case['trigger_id'] in objects and objects[case['trigger_id']].get('spawn_step', 0) == release,
        'spawn_events_match': ({e.get('id') for e in run.get('spawn_events', [])} == allowed and len(run.get('spawn_events', [])) == len(allowed) and all(e.get('physics_step') == release for e in run.get('spawn_events', []))),
        'no_pending_or_archived_bodies': not run.get('pending_spawn_ids') and not run.get('archived_objects'),
        'contacts_complete': run.get('contacts_truncated') is False,
        'all_dynamic_mass_kg_valid': all(positive_mass(obj) for obj in objects.values() if obj.get('dynamic')),
    }
    joints = {n: o['joint'] for n, o in objects.items() if o.get('kind') == 'joint' and isinstance(o.get('joint'), dict)}
    checks['all_joint_observations_passive'] = bool(joints) and all(
        all(isinstance(s.get('joints', {}).get(n), dict) and s['joints'][n].get('drive_present') is False and s['joints'][n].get('type') == j.get('type') and s['joints'][n].get('enabled') is j.get('enabled', True) and finite(s['joints'][n].get('anchor_error_m')) and vector(s['joints'][n].get('anchor0_world_m')) and vector(s['joints'][n].get('anchor1_world_m')) for n, j in joints.items())
        for s in run.get('samples', []))
    checks['no_authored_joint_drives'] = all(not any('drive' in k.lower() or 'motor' in k.lower() or 'target' in k.lower() for k in cfg) for cfg in joints.values())
    actual = run.get('mechanism_configuration', {}).get('joints', [])
    loaded = {j.get('path'): j for j in actual if isinstance(j, dict)}
    usd_types = {t: 'Physics'+t.title()+'Joint' for t in ('fixed', 'revolute', 'prismatic', 'spherical')}
    checks['loaded_joint_inventory_matches_spec'] = (len(loaded) == len(actual) and set(loaded) == {path(n) for n in joints} and all(
        loaded[path(n)].get('type') == usd_types.get(cfg.get('type')) and loaded[path(n)].get('enabled') is cfg.get('enabled', True) and loaded[path(n)].get('drives') == [] and loaded[path(n)].get('drive_attributes') == [] and all(loaded[path(n)].get('body'+str(i)) == ([path(cfg['body'+str(i)])] if cfg.get('body'+str(i)) else []) for i in (0, 1))
        for n, cfg in joints.items()))
    initial = run.get('initial_joint_states', {})
    checks['initial_joint_observations_complete'] = set(initial) == set(joints) and all(
        isinstance(initial.get(n), dict) and initial[n].get('drive_present') is False and initial[n].get('type') == cfg.get('type') and initial[n].get('enabled') is cfg.get('enabled', True) and finite(initial[n].get('anchor_error_m')) and vector(initial[n].get('anchor0_world_m')) and vector(initial[n].get('anchor1_world_m')) and (cfg['type'] not in ('prismatic', 'revolute') or finite(initial[n].get('position_m' if cfg['type'] == 'prismatic' else 'angle_degrees')))
        for n, cfg in joints.items())
    actual_settings = run.get('mechanism_configuration', {}).get('body_settings', {})
    physical_keys = ('linear_damping', 'angular_damping', 'sleep_threshold', 'solver_position_iterations', 'solver_velocity_iterations', 'enable_ccd')
    checks['loaded_passive_body_settings_match_spec'] = all(
        isinstance(actual_settings.get(n), dict) and all(k in actual_settings[n] and finite(actual_settings[n][k]) and abs(float(actual_settings[n][k])-float(value)) <= 1e-5 if k != 'enable_ccd' else actual_settings[n].get(k) is value for k, value in obj.get('physics', {}).items() if k in physical_keys)
        for n, obj in objects.items() if obj.get('physics'))
    needs_ccd = any(obj.get('physics', {}).get('enable_ccd') is True for obj in objects.values())
    checks['loaded_scene_ccd_enabled_when_required'] = not needs_ccd or run.get('mechanism_configuration', {}).get('scene_enable_ccd') is True
    return checks


def contact_exists(run, a, b):
    for key, record in run.get('contact_counts', {}).items():
        parts = key.split('|')
        if len(parts) < 2 or not finite(record.get('count')) or record['count'] <= 0:
            continue
        if (parts[0] == a and (parts[1] == path(b) or parts[1].startswith(path(b)+'/'))) or (parts[0] == b and (parts[1] == path(a) or parts[1].startswith(path(a)+'/'))):
            return True
    return False


def radial_geometry(sample, spec, case, nodes):
    rope = case['rope']
    center, rotation = pose(sample, spec, case['roles']['pulley'])
    axis = rotate(rotation, [float(i == 'XYZ'.index(rope['axle_local_axis'])) for i in range(3)])
    radial, axial = [], []
    for point in nodes:
        relative = sub(point, center)
        along = dot(relative, axis)
        radial.append([r-along*a for r, a in zip(relative, axis)])
        axial.append(abs(along))
    return axis, radial, axial


def chain_geometry(sample, case, spec):
    nodes = []
    for name in case['rope']['joint_ids']:
        value = sample['joints'][name]
        nodes.append([(a+b)/2 for a, b in zip(value['anchor0_world_m'], value['anchor1_world_m'])])
    rope = case['rope']
    spans = rope.get('free_spans', [])
    wrap_span = rope.get('wrap_span')
    if rope.get('partition_mode') == 'rim_geometry':
        _, radial, axial = radial_geometry(sample, spec, case, nodes)
        lower, upper = wrap_span
        blocks, start = [], None
        for i in range(lower, upper+2):
            near = i <= upper and abs(math.sqrt(dot(radial[i], radial[i]))-rope['pulley_radius_m']) <= rope['radial_tolerance_m'] and axial[i] <= rope['axial_tolerance_m']
            if near and start is None:
                start = i
            if not near and start is not None:
                if i-start >= 3:
                    blocks.append([start, i-1])
                start = None
        # A frozen geometric rule, with deterministic lower-index tie breaking.
        wrap_span = max(blocks, key=lambda block: (block[1]-block[0], -block[0])) if blocks else None
        spans = ([[0, wrap_span[0]]] if wrap_span and wrap_span[0] > 0 else []) + ([[wrap_span[1], len(nodes)-1]] if wrap_span and wrap_span[1] < len(nodes)-1 else [])
    excess = []
    for first, last in spans:
        points = nodes[first:last+1]
        excess.append(sum(math.dist(a, b) for a, b in zip(points, points[1:]))-math.dist(points[0], points[-1]))
    return nodes, excess, wrap_span


def wrapped_geometry(sample, spec, case, nodes, span):
    rope = case['rope']
    if span is None:
        return {'valid': False, 'coverage_degrees': 0, 'radial_distances_m': [], 'max_axial_offset_m': None}
    axis, radial, axial = radial_geometry(sample, spec, case, nodes[span[0]:span[1]+1])
    lengths = [math.sqrt(dot(p, p)) for p in radial]
    increments = [math.degrees(math.atan2(dot(axis, cross(a, b)), dot(a, b))) for a, b in zip(radial, radial[1:])]
    coverage = abs(sum(increments))
    one_direction = bool(increments) and (all(a >= -1e-5 for a in increments) or all(a <= 1e-5 for a in increments))
    valid = (all(abs(r-rope['pulley_radius_m']) <= rope['radial_tolerance_m'] for r in lengths) and max(axial) <= rope['axial_tolerance_m'] and one_direction and coverage >= rope['minimum_wrap_degrees'])
    return {'valid': valid, 'coverage_degrees': coverage, 'radial_distances_m': lengths, 'max_axial_offset_m': max(axial)}


def first_run(flags, length):
    count = 0
    for i, flag in enumerate(flags):
        count = count+1 if flag else 0
        if count >= length:
            return i-length+1
    return None


def isolated_detachment(spec, reference_spec, joint_id):
    if reference_spec is None:
        return False
    current, expected = copy.deepcopy(spec), copy.deepcopy(reference_spec)
    for document in (current, expected):
        for key in ('scene_id', 'revision', 'requests'):
            document.pop(key, None)
    try:
        if expected['objects'][joint_id]['joint'].get('enabled', True) is not True or current['objects'][joint_id]['joint'].get('enabled', True) is not False:
            return False
        expected['objects'][joint_id]['joint']['enabled'] = False
    except (KeyError, TypeError):
        return False
    return current == expected


def evaluate(run, spec, case, mode='positive', reference_spec=None, dt=1/60):
    validate_case(case)
    if case['mechanism'] != 'rope_drawer':
        if mode != 'positive':
            raise ValueError('additional controls are not mandatory for this P1 mechanism')
        return evaluate_event_mechanism(run, spec, case, dt)
    if mode not in ('positive', 'detached_drawer'):
        raise ValueError('unknown control mode')
    clock = timeline(run, spec, dt)
    checks = {**clock['checks'], **passive_checks(run, spec, case)}
    strict = strict_initial_state(run, spec, case, dt)
    checks.update(strict['checks'])
    if not strict['passed']:
        return {'passed': False, 'mode': mode, 'checks': checks, 'timeline': clock, 'strict_initial_state': strict, 'scope': strict['scope']}
    objects, roles, joint_roles = spec.get('objects', {}), case['roles'], case['joints']
    rope, thresholds = case['rope'], case['thresholds']
    body_ids = list(roles.values()) + rope['segment_ids']
    checks['all_roles_are_physical_bodies'] = all(n in objects and objects[n].get('kind') in ('box', 'sphere', 'cylinder', 'capsule', 'compound') and objects[n].get('dynamic') is True and (objects[n].get('collision') is True or objects[n].get('kind') == 'compound') and positive_mass(objects[n]) for n in body_ids)
    joint_ids = rope['joint_ids'] + [joint_roles['drawer']] + ([joint_roles['pulley']] if 'pulley' in joint_roles else [])
    checks['all_role_joints_exist'] = all(objects.get(n, {}).get('kind') == 'joint' for n in joint_ids)
    if not checks['all_role_joints_exist']:
        return {'passed': False, 'mode': mode, 'checks': checks, 'timeline': clock, 'scope': 'missing required physical joint definitions'}
    configs = {n: objects[n]['joint'] for n in joint_ids}
    ordered_bodies = [roles['drawer']] + rope['segment_ids'] + [roles['weight']]
    checks['continuous_physical_rope_topology'] = all(set((configs[j].get('body0'), configs[j].get('body1'))) == {ordered_bodies[i], ordered_bodies[i+1]} and configs[j].get('type') in (('spherical', 'fixed') if i in (0, len(rope['joint_ids'])-1) else ('spherical',)) for i, j in enumerate(rope['joint_ids']))
    checks['passive_prismatic_drawer'] = configs[joint_roles['drawer']].get('type') == 'prismatic' and configs[joint_roles['drawer']].get('body1') == roles['drawer'] and configs[joint_roles['drawer']].get('body0') is None
    if case['rope_model'] == 'segmented_over_free_pulley':
        pulley_cfg = configs[joint_roles['pulley']]
        checks['unlimited_free_revolute_pulley'] = pulley_cfg.get('type') == 'revolute' and pulley_cfg.get('body1') == roles['pulley'] and pulley_cfg.get('body0') is None and 'lower_limit' not in pulley_cfg and 'upper_limit' not in pulley_cfg
    disabled = {n for n, cfg in configs.items() if cfg.get('enabled', True) is False}
    checks['expected_joint_enable_state'] = disabled == ({joint_roles['drawer_end']} if mode == 'detached_drawer' else set())
    if mode == 'detached_drawer':
        checks['only_drawer_end_joint_changed'] = isolated_detachment(spec, reference_spec, joint_roles['drawer_end'])
    samples = [s for s in run.get('samples', []) if s.get('physics_steps', 0) > case['release_step']]
    if not all(checks[k] for k in ('every_physics_step_present', 'all_dynamic_body_poses_complete', 'all_joint_observations_passive', 'initial_joint_observations_complete')) or not samples:
        return {'passed': False, 'mode': mode, 'checks': checks, 'timeline': clock, 'scope': 'incomplete observations cannot establish mechanism acceptance'}
    if any(not finite(s['joints'][joint_roles['drawer']].get('position_m')) or ('pulley' in joint_roles and not finite(s['joints'][joint_roles['pulley']].get('angle_degrees'))) for s in samples):
        checks['joint_coordinates_finite'] = False
        return {'passed': False, 'mode': mode, 'checks': checks, 'timeline': clock}
    checks['joint_coordinates_finite'] = True
    checks['enabled_joint_anchors_remain_bounded'] = all(s['joints'][n]['anchor_error_m'] <= thresholds['max_anchor_error_m'] for s in samples for n in joint_ids if n not in disabled)
    initial = baseline_observation(run, spec) if spec.get('observation', {}).get('strict_start') is True else samples[0]
    drawer_initial = pose(initial, spec, roles['drawer'])[0]
    weight_initial = pose(initial, spec, roles['weight'])[0]
    q0 = run['initial_joint_states'][joint_roles['drawer']]['position_m']
    angle0 = run['initial_joint_states'][joint_roles['pulley']]['angle_degrees'] if 'pulley' in joint_roles else 0
    motion = []
    for sample in samples:
        displacement = sub(pose(sample, spec, roles['drawer'])[0], drawer_initial)
        signed = dot(displacement, case['drawer_axis_world'])
        off_axis = math.sqrt(max(0., dot(displacement, displacement)-signed*signed))
        coordinate = sample['joints'][joint_roles['drawer']]['position_m']-q0
        # USD joint coordinate sign can be reversed by the frozen joint frame.
        pulley_rotation = abs(sample['joints'][joint_roles['pulley']]['angle_degrees']-angle0) if 'pulley' in joint_roles else 0
        motion.append({'step': sample['physics_steps'], 'time_s': sample['simulation_time_s'], 'drawer_signed_m': signed, 'drawer_total_m': math.sqrt(dot(displacement, displacement)), 'drawer_off_axis_m': off_axis, 'drawer_joint_travel_m': abs(coordinate), 'weight_drop_m': weight_initial[2]-pose(sample, spec, roles['weight'])[0][2], 'pulley_rotation_degrees': pulley_rotation})
    checks['drawer_motion_follows_frozen_xyz_axis'] = max(m['drawer_off_axis_m'] for m in motion) <= thresholds['max_off_axis_m'] and min(m['drawer_signed_m'] for m in motion) >= -thresholds['slack_drawer_max_m']
    checks['weight_really_falls'] = max(m['weight_drop_m'] for m in motion) >= thresholds['weight_min_drop_m']
    details = {'motion_per_step': motion}
    if mode == 'detached_drawer':
        checks['detached_drawer_does_not_open'] = max(m['drawer_total_m'] for m in motion) <= thresholds['slack_drawer_max_m'] and max(m['drawer_joint_travel_m'] for m in motion) <= thresholds['slack_drawer_max_m']
    else:
        geometry = []
        for sample in samples:
            nodes, excess, measured_wrap_span = chain_geometry(sample, case, spec)
            wrap = wrapped_geometry(sample, spec, case, nodes, measured_wrap_span) if case['rope_model'] == 'segmented_over_free_pulley' else None
            geometry.append({'step': sample['physics_steps'], 'free_span_excess_m': excess, 'slack': bool(excess) and max(excess) >= thresholds['slack_min_excess_m'], 'taut': bool(excess) and max(excess) <= thresholds['taut_max_excess_m'], 'measured_wrap_span': measured_wrap_span, 'wrap': wrap})
        taut = first_run([g['taut'] for g in geometry], thresholds['taut_hold_steps'])
        slack = first_run([g['slack'] for g in geometry], thresholds['slack_min_steps'])
        slack_before_taut = geometry[:taut] if taut is not None else geometry
        slack_indices = [i for i, g in enumerate(slack_before_taut) if g['slack']]
        checks['measured_slack_precedes_measured_taut'] = slack is not None and taut is not None and slack+thresholds['slack_min_steps'] <= taut
        checks['drawer_stays_still_through_slack'] = bool(slack_indices) and all(motion[i]['drawer_total_m'] <= thresholds['slack_drawer_max_m'] and motion[i]['drawer_joint_travel_m'] <= thresholds['slack_drawer_max_m'] for i in range(taut if taut is not None else len(motion)))
        checks['weight_falls_while_slack'] = bool(slack_indices) and max(motion[i]['weight_drop_m'] for i in slack_indices) >= thresholds['weight_slack_min_drop_m']
        opened = next((i for i, m in enumerate(motion) if m['drawer_signed_m'] >= thresholds['drawer_min_travel_m'] and m['drawer_joint_travel_m'] >= thresholds['drawer_min_travel_m']), None)
        checks['taut_rope_then_drawer_opens'] = taut is not None and opened is not None and opened >= taut+thresholds['taut_hold_steps']-1
        if case['rope_model'] == 'segmented_over_free_pulley':
            checks['free_pulley_rotates_during_pull'] = taut is not None and opened is not None and abs(samples[opened]['joints'][joint_roles['pulley']]['angle_degrees']-samples[taut]['joints'][joint_roles['pulley']]['angle_degrees']) >= thresholds['pulley_min_rotation_degrees']
            checks['rope_contacts_physical_pulley'] = any(contact_exists(run, n, roles['pulley']) for n in rope['segment_ids'])
            checks['measured_wrap_persists_through_pull'] = taut is not None and opened is not None and all(g['wrap']['valid'] for g in geometry[taut:opened+1])
        details.update({'geometry_per_step': geometry, 'slack_onset_step': samples[slack]['physics_steps'] if slack is not None else None, 'taut_onset_step': samples[taut]['physics_steps'] if taut is not None else None, 'drawer_open_step': samples[opened]['physics_steps'] if opened is not None else None})
    report = {'passed': all(checks.values()), 'mode': mode, 'rope_model': case['rope_model'], 'wrapped_pulley_geometry_passed': mode == 'positive' and case['rope_model'] == 'segmented_over_free_pulley' and all(checks.values()), 'wrapped_pulley_success': False, 'checks': checks, 'timeline': clock, 'strict_initial_state': strict, **details, 'scope': 'Recorded passive geometry and motion only; wrapped success requires the paired isolated detached-drawer control. Slack/taut are geometric classifications, not measured rope force.'}
    if case.get('activity'):
        report['activity'] = measure_activity(run, spec, case['activity'], dt)
        report['passed'] = report['passed'] and report['activity']['passed']
    return report


def valid_bounds(bounds):
    return isinstance(bounds, dict) and vector(bounds.get('min')) and vector(bounds.get('max')) and all(a < b for a, b in zip(bounds['min'], bounds['max']))


def validate_event_case(case):
    kind = case['mechanism']
    roles, joints, axes = case.get('roles', {}), case.get('joints', {}), case.get('axes', {})
    spoon = kind == 'spoon_sugar'
    role_keys = ('lasttile', 'stopper', 'spoon', 'sugar', 'cup') if spoon else ('wheel', 'latch', 'door', 'seat', 'rollingpin', 'retainer')
    joint_keys = ('stopper', 'spoon') if spoon else ('wheel', 'latch', 'door')
    if not isinstance(case.get('trigger_id'), str) or not case['trigger_id'] or type(case.get('release_step')) is not int or case['release_step'] < (1 if spoon else 0):
        raise ValueError('freeze the unique trigger and its release_step')
    if any(not isinstance(roles.get(k), str) or not roles[k] for k in role_keys) or any(not isinstance(joints.get(k), str) or not joints[k] for k in joint_keys):
        raise ValueError('missing mechanism body/joint roles')
    world_axes = ('stopper_world',) if spoon else ('latch_world', 'rollingpin_world')
    signs = ('spoon_joint_sign',) if spoon else ('wheel_joint_sign', 'door_joint_sign')
    if any(not unit(axes.get(k)) for k in world_axes) or any(type(axes.get(k)) not in (int, float) or axes[k] not in (-1, 1) for k in signs):
        raise ValueError('freeze normalized XYZ axes and signed joint directions')
    thresholds = case.get('thresholds', {})
    positive = ['initial_max_motion_m', 'initial_max_rotation_degrees', 'max_anchor_error_m', 'max_off_axis_m']
    positive += (['lasttile_activation_degrees', 'stopper_min_travel_m', 'stopper_initial_max_m', 'spoon_activation_degrees', 'spoon_initial_max_degrees', 'sugar_leave_min_distance_m', 'sugar_leave_clearance_m', 'terminal_max_motion_m', 'terminal_max_rotation_degrees'] if spoon else ['wheel_activation_degrees', 'latch_min_travel_m', 'latch_initial_max_m', 'door_activation_degrees', 'door_bridge_angle_degrees', 'door_bridge_angle_tolerance_degrees', 'rollingpin_release_travel_m', 'part_contact_tolerance_m', 'retainer_release_clearance_m'])
    if any(not finite(thresholds.get(k)) or thresholds[k] <= 0 for k in positive):
        raise ValueError('freeze positive mechanism thresholds: '+', '.join(positive))
    for key in ('initial_hold_steps', 'terminal_hold_steps' if spoon else 'bridge_hold_steps'):
        if type(thresholds.get(key)) is not int or thresholds[key] < 2:
            raise ValueError('freeze at least two measured steps for '+key)
    tolerance = thresholds.get('contact_window_tolerance_steps')
    if type(tolerance) is not int or tolerance < 0:
        raise ValueError('freeze nonnegative contact_window_tolerance_steps')
    if spoon:
        if not valid_bounds(case.get('support_region_local')) or not valid_bounds(case.get('receiver', {}).get('interior_world')) or not vector(case.get('receiver', {}).get('sugar_size_m')) or min(case['receiver']['sugar_size_m']) <= 0:
            raise ValueError('freeze the spoon support region, cup interior and sugar dimensions')
        if thresholds['stopper_min_travel_m'] <= thresholds['stopper_initial_max_m'] or thresholds['spoon_activation_degrees'] <= thresholds['spoon_initial_max_degrees']:
            raise ValueError('activation thresholds must exceed initial quiet tolerances')
    else:
        regions = case.get('bridge_regions_world')
        geometry = case.get('geometry', {})
        if not isinstance(regions, list) or len(regions) < 2 or not all(valid_bounds(b) for b in regions):
            raise ValueError('freeze at least bridge entry and bridge exit regions')
        if any(type(geometry.get(k)) is not int or geometry[k] < 0 for k in ('wheel_paddle_part_index', 'retainer_part_index')):
            raise ValueError('freeze actual compound paddle/retainer collision part indices')
        if thresholds['door_bridge_angle_degrees'] <= thresholds['door_activation_degrees'] or thresholds['latch_min_travel_m'] <= thresholds['latch_initial_max_m']:
            raise ValueError('bridge/clearance thresholds must exceed activation/quiet values')
    return case


def contact_records(run, first, second):
    matches = []
    for key, value in run.get('contact_counts', {}).items():
        fields = key.split('|')
        if len(fields) < 2 or not finite(value.get('count')) or value['count'] <= 0:
            continue
        start, end = value.get('first_physics_step'), value.get('last_physics_step')
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= run.get('actual_physics_steps', -1):
            continue
        if ((fields[0] == first and (fields[1] == path(second) or fields[1].startswith(path(second)+'/'))) or
                (fields[0] == second and (fields[1] == path(first) or fields[1].startswith(path(first)+'/')))):
            matches.append(value)
    return matches


def contact_window(run, first, second, lower, upper, tolerance=0):
    """A real summary endpoint in the window; no interpolation of contacts."""
    stamps = sorted({value[k] for value in contact_records(run, first, second) for k in ('first_physics_step', 'last_physics_step') if type(value.get(k)) is int and value[k] >= 0})
    witnesses = [s for s in stamps if lower is not None and upper is not None and lower <= s <= upper+tolerance]
    return {'body_ids': [first, second], 'window_start_step': lower, 'window_end_step': upper, 'summary_endpoint_steps': stamps, 'witness_steps': witnesses, 'passed': bool(witnesses), 'scope': 'Actual first/last contact endpoint only; intermediate persistence is not inferred.'}


def first_flag(samples, flags):
    return next((s['physics_steps'] for s, flag in zip(samples, flags) if flag), None)


def box_corners(sample, spec, name):
    obj = spec['objects'][name]
    if obj.get('kind') != 'box' or not vector(obj.get('size')) or min(obj['size']) <= 0:
        raise ValueError('whole-box measurement requires a physical box and actual dimensions')
    p, q = pose(sample, spec, name)
    return [[v+r for v, r in zip(p, rotate(q, [x*obj['size'][0], y*obj['size'][1], z*obj['size'][2]]))] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]


def local_points(points, center, rotation):
    inverse = [rotation[0], *[-v for v in rotation[1:]]]
    return [rotate(inverse, sub(point, center)) for point in points]


def points_contained(points, bounds, epsilon=0):
    return all(all(a-epsilon <= v <= b+epsilon for a, v, b in zip(bounds['min'], point, bounds['max'])) for point in points)


def points_disjoint(points, bounds, clearance):
    return any(max(p[i] for p in points) < bounds['min'][i]-clearance or min(p[i] for p in points) > bounds['max'][i]+clearance for i in range(3))


def stable_poses(samples, spec, name, motion, rotation):
    poses = [pose(s, spec, name) for s in samples]
    return bool(poses) and all(math.dist(a[0], b[0]) <= motion and angle_degrees(a[1], b[1]) <= rotation for i, a in enumerate(poses) for b in poses[i+1:])


def first_stable_window(samples, spec, name, flags, hold, motion, rotation):
    for i in range(len(samples)-hold+1):
        if all(flags[i:i+hold]) and stable_poses(samples[i:i+hold], spec, name, motion, rotation):
            return samples[i]['physics_steps'], samples[i+hold-1]['physics_steps']
    return None, None


def event_stamp(step, dt, confirmation=None):
    return {'onset_step': step, 'onset_time_s': step*dt if step is not None else None,
            'confirmation_step': confirmation if confirmation is not None else step,
            'confirmation_time_s': (confirmation if confirmation is not None else step)*dt if step is not None else None}


def event_mechanism_base(run, spec, case, dt):
    clock = timeline(run, spec, dt)
    checks = {**clock['checks'], **passive_checks(run, spec, case)}
    strict = strict_initial_state(run, spec, case, dt)
    checks.update(strict['checks'])
    objects, roles, joint_roles = spec['objects'], case['roles'], case['joints']
    spoon = case['mechanism'] == 'spoon_sugar'
    dynamic = ('lasttile', 'stopper', 'spoon', 'sugar') if spoon else ('wheel', 'latch', 'door', 'rollingpin', 'retainer')
    static = ('cup',) if spoon else ('seat',)
    def physical(name):
        obj = objects.get(name, {})
        if obj.get('kind') == 'compound':
            return any(p.get('collision', True) for p in obj.get('parts', []))
        return obj.get('kind') in ('box', 'sphere', 'cylinder', 'capsule') and obj.get('collision') is True
    checks['all_roles_are_physical_bodies'] = all(physical(n) for n in roles.values()) and all(objects.get(roles[k], {}).get('dynamic') is True and positive_mass(objects[roles[k]]) for k in dynamic) and all(not objects.get(roles[k], {}).get('dynamic') for k in static)
    types = {'stopper': 'prismatic', 'spoon': 'revolute'} if spoon else {'wheel': 'revolute', 'latch': 'prismatic', 'door': 'revolute'}
    checks['role_joints_match_physical_bodies'] = all(objects.get(n, {}).get('kind') == 'joint' and objects[n].get('joint', {}).get('type') == types[k] and objects[n]['joint'].get('body1') == roles[k] and objects[n]['joint'].get('body0') is None and objects[n]['joint'].get('enabled', True) is True for k, n in joint_roles.items())
    samples = run.get('samples', [])
    checks['all_mechanism_joint_coordinates_finite'] = all(finite(s.get('joints', {}).get(n, {}).get('position_m' if types[k] == 'prismatic' else 'angle_degrees')) for s in samples for k, n in joint_roles.items())
    checks['enabled_joint_anchors_remain_bounded'] = all(j.get('anchor_error_m', math.inf) <= case['thresholds']['max_anchor_error_m'] for s in samples for j in s.get('joints', {}).values() if j.get('enabled') is True)
    report = {'passed': False, 'mode': 'positive', 'mechanism': case['mechanism'], 'checks': checks, 'timeline': clock, 'strict_initial_state': strict, 'paired_control_required_for_causal_acceptance': False, 'formal_whole_room_acceptance': False, 'scope': 'P1 passive event mechanism only. Contacts are actual summary endpoints inside measured event windows; they are not a general proof of causality. No P2/P3 acceptance is established.'}
    safe = ('every_physics_step_present', 'all_dynamic_body_poses_complete', 'all_joint_observations_passive', 'initial_joint_observations_complete', 'all_roles_are_physical_bodies', 'role_joints_match_physical_bodies', 'all_mechanism_joint_coordinates_finite')
    return report, strict['passed'] and all(checks[k] for k in safe)


def evaluate_event_mechanism(run, spec, case, dt):
    report, safe = event_mechanism_base(run, spec, case, dt)
    if not safe:
        return report
    if case['mechanism'] == 'spoon_sugar':
        evaluate_spoon(run, spec, case, report, dt)
    else:
        evaluate_wheel_door(run, spec, case, report, dt)
    report['passed'] = all(report['checks'].values())
    if case.get('activity'):
        report['activity'] = measure_activity(run, spec, case['activity'], dt)
        report['passed'] = report['passed'] and report['activity']['passed']
    return report


def evaluate_spoon(run, spec, case, report, dt):
    samples, roles, joints, t = run['samples'], case['roles'], case['joints'], case['thresholds']
    checks = report['checks']
    initial = baseline_observation(run, spec)
    before = [s for s in samples if s['physics_steps'] <= case['release_step']]
    quiet_observations = ([initial] if spec.get('observation', {}).get('strict_start') is True else []) + before
    initial_joints = run['initial_joint_states']
    stopper0 = initial_joints[joints['stopper']]['position_m']
    spoon0 = initial_joints[joints['spoon']]['angle_degrees']
    sugar_size = spec['objects'][roles['sugar']].get('size')
    checks['actual_sugar_dimensions_match_frozen_case'] = vector(sugar_size) and all(abs(a-b) <= 1e-9 for a, b in zip(sugar_size, case['receiver']['sugar_size_m']))
    if spec['objects'][roles['sugar']].get('kind') != 'box':
        checks['sugar_is_physical_box'] = False
        return
    rows, support_flags, leave_flags, inside_flags = [], [], [], []
    local0 = local_points([pose(initial, spec, roles['sugar'])[0]], *pose(initial, spec, roles['spoon']))[0]
    for s in samples:
        displacement = sub(pose(s, spec, roles['stopper'])[0], pose(initial, spec, roles['stopper'])[0])
        signed = dot(displacement, case['axes']['stopper_world'])
        local = local_points(box_corners(s, spec, roles['sugar']), *pose(s, spec, roles['spoon']))
        local_center = local_points([pose(s, spec, roles['sugar'])[0]], *pose(s, spec, roles['spoon']))[0]
        row = {'step': s['physics_steps'], 'lasttile_degrees': angle_degrees(pose(initial, spec, roles['lasttile'])[1], pose(s, spec, roles['lasttile'])[1]), 'stopper_signed_m': signed, 'stopper_joint_m': abs(s['joints'][joints['stopper']]['position_m']-stopper0), 'stopper_off_axis_m': math.sqrt(max(0., dot(displacement, displacement)-signed*signed)), 'spoon_signed_degrees': case['axes']['spoon_joint_sign']*(s['joints'][joints['spoon']]['angle_degrees']-spoon0), 'sugar_relative_travel_m': math.dist(local_center, local0)}
        rows.append(row)
        support_flags.append(points_contained(local, case['support_region_local'], 1e-6))
        leave_flags.append(points_disjoint(local, case['support_region_local'], t['sugar_leave_clearance_m']) and row['sugar_relative_travel_m'] >= t['sugar_leave_min_distance_m'])
        inside_flags.append(points_contained(box_corners(s, spec, roles['sugar']), case['receiver']['interior_world']))
    tile = first_flag(samples, [r['lasttile_degrees'] >= t['lasttile_activation_degrees'] for r in rows])
    stopper = first_flag(samples, [r['stopper_signed_m'] >= t['stopper_min_travel_m'] and r['stopper_joint_m'] >= t['stopper_min_travel_m'] for r in rows])
    spoon = first_flag(samples, [r['spoon_signed_degrees'] >= t['spoon_activation_degrees'] for r in rows])
    leave, full = first_flag(samples, leave_flags), first_flag(samples, inside_flags)
    stable, confirmation = first_stable_window(samples, spec, roles['sugar'], inside_flags, t['terminal_hold_steps'], t['terminal_max_motion_m'], t['terminal_max_rotation_degrees'])
    contact_first = [v['first_physics_step'] for v in contact_records(run, roles['sugar'], roles['cup']) if type(v.get('first_physics_step')) is int and v['first_physics_step'] >= 0]
    cup_touch = min(contact_first) if contact_first else None
    checks['sufficient_initial_observation_window'] = len(before) >= t['initial_hold_steps']
    checks['initial_mechanism_is_quiet'] = bool(before) and all(stable_poses(quiet_observations, spec, roles[k], t['initial_max_motion_m'], t['initial_max_rotation_degrees']) for k in ('lasttile', 'stopper', 'spoon', 'sugar'))
    checks['initial_joint_coordinates_quiet'] = bool(before) and all(abs(s['joints'][joints['stopper']]['position_m']-stopper0) <= t['stopper_initial_max_m'] and abs(s['joints'][joints['spoon']]['angle_degrees']-spoon0) <= t['spoon_initial_max_degrees'] for s in before)
    initial_support = points_contained(local_points(box_corners(initial, spec, roles['sugar']), *pose(initial, spec, roles['spoon'])), case['support_region_local'], 1e-6)
    checks['sugar_initially_supported_and_inside_spoon_region'] = bool(before) and initial_support and all(support_flags[s['physics_steps']-1] for s in before) and contact_window(run, roles['sugar'], roles['spoon'], 0, case['release_step'])['passed']
    checks['stopper_follows_frozen_xyz_axis'] = max(r['stopper_off_axis_m'] for r in rows) <= t['max_off_axis_m'] and min(r['stopper_signed_m'] for r in rows) >= -t['stopper_initial_max_m']
    checks['physical_events_in_required_order'] = all(v is not None for v in (tile, stopper, spoon, leave, full)) and case['release_step'] < tile <= stopper < spoon <= leave < full
    checks['first_cup_contact_is_new_and_observed'] = cup_touch is not None and spoon is not None and case['release_step'] < cup_touch and spoon <= cup_touch <= run['actual_physics_steps']
    checks['whole_sugar_received_and_stable'] = stable is not None and confirmation is not None and full is not None and leave is not None and leave < full <= stable
    tail = [s for s in samples if stable is not None and s['physics_steps'] >= stable]
    checks['sugar_remains_contained_after_stability'] = bool(tail) and all(inside_flags[s['physics_steps']-1] for s in tail) and stable_poses(tail, spec, roles['sugar'], t['terminal_max_motion_m'], t['terminal_max_rotation_degrees'])
    tolerance = t['contact_window_tolerance_steps']
    contacts = {
        'trigger_to_lasttile': contact_window(run, case['trigger_id'], roles['lasttile'], case['release_step'], tile, tolerance),
        'lasttile_to_stopper': contact_window(run, roles['lasttile'], roles['stopper'], tile, stopper, tolerance),
        'stopper_withdraws_spoon_support': contact_window(run, roles['stopper'], roles['spoon'], tile, stopper, tolerance),
        'spoon_to_sugar': contact_window(run, roles['spoon'], roles['sugar'], stopper, leave, tolerance),
    }
    checks['all_physical_handoff_contacts_witnessed'] = all(c['passed'] for c in contacts.values())
    report.update({'events': {'release': event_stamp(case['release_step'], dt), 'lasttile_activation': event_stamp(tile, dt), 'stopper_clear': event_stamp(stopper, dt), 'spoon_activation': event_stamp(spoon, dt), 'sugar_left_spoon': event_stamp(leave, dt), 'first_cup_contact': event_stamp(cup_touch, dt), 'first_whole_sugar_entry': event_stamp(full, dt), 'sugar_stable': event_stamp(stable, dt, confirmation)}, 'contacts': contacts, 'motion_per_step': rows, 'sugar_contained_per_step': [{'physics_step': s['physics_steps'], 'whole_sugar_inside': flag} for s, flag in zip(samples, inside_flags)], 'receiver': {'interior_world': case['receiver']['interior_world'], 'final_sugar_center_world_m': pose(samples[-1], spec, roles['sugar'])[0], 'final_sugar_corners_world_m': box_corners(samples[-1], spec, roles['sugar']), 'final_whole_sugar_inside': inside_flags[-1], 'required_hold_steps': t['terminal_hold_steps']}})


def multiply_quaternions(a, b):
    imaginary = [a[0]*v+b[0]*u+c for u, v, c in zip(a[1:], b[1:], cross(a[1:], b[1:]))]
    return [a[0]*b[0]-dot(a[1:], b[1:]), *imaginary]


def primitive_extent_corners(sample, spec, name):
    obj = spec['objects'][name]
    if obj.get('kind') == 'compound':
        root_p, root_q = pose(sample, spec, name)
        points = []
        for part in obj.get('parts', []):
            if not part.get('collision', True):
                continue
            if not vector(part.get('size')) or min(part['size']) <= 0:
                raise ValueError('compound clearance requires actual collision-part dimensions')
            for x in (-.5, .5):
                for y in (-.5, .5):
                    for z in (-.5, .5):
                        offset = rotate(part.get('orientation_wxyz', [1, 0, 0, 0]), [x*part['size'][0], y*part['size'][1], z*part['size'][2]])
                        local = [a+b for a, b in zip(part.get('position', [0, 0, 0]), offset)]
                        points.append([a+b for a, b in zip(root_p, rotate(root_q, local))])
        if not points:
            raise ValueError('compound clearance requires real collision geometry')
        return points
    if obj.get('kind') not in ('box', 'sphere', 'cylinder', 'capsule') or not vector(obj.get('size')) or min(obj['size']) <= 0:
        raise ValueError('part clearance requires primitive actual body dimensions')
    p, q = pose(sample, spec, name)
    return [[v+r for v, r in zip(p, rotate(q, [x*obj['size'][0], y*obj['size'][1], z*obj['size'][2]]))] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]


def measured_part_gap(sample, spec, part_body, index, other_body):
    """Conservative bounding-box gap to a frozen real compound collision part."""
    obj = spec['objects'][part_body]
    parts = obj.get('parts', [])
    if obj.get('kind') != 'compound' or not 0 <= index < len(parts):
        raise ValueError('frozen compound collision part does not exist')
    part = parts[index]
    if part.get('kind') != 'box' or part.get('collision', True) is not True or not vector(part.get('size')) or min(part['size']) <= 0:
        raise ValueError('paddle/retainer must reference an actual colliding box part')
    root_p, root_q = pose(sample, spec, part_body)
    offset = rotate(root_q, part.get('position', [0, 0, 0]))
    center = [a+b for a, b in zip(root_p, offset)]
    rotation = multiply_quaternions(root_q, part.get('orientation_wxyz', [1, 0, 0, 0]))
    points = local_points(primitive_extent_corners(sample, spec, other_body), center, rotation)
    gaps = [max(0., min(p[i] for p in points)-part['size'][i]/2, -part['size'][i]/2-max(p[i] for p in points)) for i in range(3)]
    return math.sqrt(dot(gaps, gaps))


def evaluate_wheel_door(run, spec, case, report, dt):
    samples, roles, joints, t = run['samples'], case['roles'], case['joints'], case['thresholds']
    checks, initial, initial_joints = report['checks'], baseline_observation(run, spec), run['initial_joint_states']
    wheel0 = initial_joints[joints['wheel']]['angle_degrees']
    latch0 = initial_joints[joints['latch']]['position_m']
    door0 = initial_joints[joints['door']]['angle_degrees']
    rows = []
    for s in samples:
        latch_delta = sub(pose(s, spec, roles['latch'])[0], pose(initial, spec, roles['latch'])[0])
        signed = dot(latch_delta, case['axes']['latch_world'])
        pin_delta = sub(pose(s, spec, roles['rollingpin'])[0], pose(initial, spec, roles['rollingpin'])[0])
        rows.append({'step': s['physics_steps'], 'wheel_signed_degrees': case['axes']['wheel_joint_sign']*(s['joints'][joints['wheel']]['angle_degrees']-wheel0), 'latch_signed_m': signed, 'latch_joint_m': abs(s['joints'][joints['latch']]['position_m']-latch0), 'latch_off_axis_m': math.sqrt(max(0., dot(latch_delta, latch_delta)-signed*signed)), 'door_signed_degrees': case['axes']['door_joint_sign']*(s['joints'][joints['door']]['angle_degrees']-door0), 'rollingpin_signed_m': dot(pin_delta, case['axes']['rollingpin_world']), 'paddle_latch_gap_m': measured_part_gap(s, spec, roles['wheel'], case['geometry']['wheel_paddle_part_index'], roles['latch']), 'retainer_pin_gap_m': measured_part_gap(s, spec, roles['retainer'], case['geometry']['retainer_part_index'], roles['rollingpin'])})
    wheel = first_flag(samples, [r['wheel_signed_degrees'] >= t['wheel_activation_degrees'] for r in rows])
    latch = first_flag(samples, [r['latch_signed_m'] >= t['latch_min_travel_m'] and r['latch_joint_m'] >= t['latch_min_travel_m'] for r in rows])
    door = first_flag(samples, [r['door_signed_degrees'] >= t['door_activation_degrees'] for r in rows])
    bridge_flags = [abs(r['door_signed_degrees']-t['door_bridge_angle_degrees']) <= t['door_bridge_angle_tolerance_degrees'] for r in rows]
    bridge_index = first_run(bridge_flags, t['bridge_hold_steps'])
    bridge = samples[bridge_index]['physics_steps'] if bridge_index is not None else None
    bridge_confirm = samples[bridge_index+t['bridge_hold_steps']-1]['physics_steps'] if bridge_index is not None else None
    pin = first_flag(samples, [r['rollingpin_signed_m'] >= t['rollingpin_release_travel_m'] for r in rows])
    retainer_clear = first_flag(samples, [r['retainer_pin_gap_m'] >= t['retainer_release_clearance_m'] for r in rows])
    region_entries = []
    for bounds in case['bridge_regions_world']:
        flags = [points_contained([pose(s, spec, roles['rollingpin'])[0]], bounds) for s in samples]
        region_entries.append(first_flag(samples, [flag and (i == 0 or not flags[i-1]) for i, flag in enumerate(flags)]))
    before = [s for s in samples if s['physics_steps'] <= case['release_step']] if case['release_step'] else [s for s in samples if wheel is not None and s['physics_steps'] < wheel]
    quiet_observations = ([initial] if spec.get('observation', {}).get('strict_start') is True else []) + before
    checks['sufficient_initial_observation_window'] = len(before) >= t['initial_hold_steps']
    quiet_roles = ('wheel', 'latch', 'door', 'rollingpin') if case['release_step'] else ('latch', 'door', 'rollingpin')
    checks['downstream_initially_quiet'] = bool(before) and all(stable_poses(quiet_observations, spec, roles[k], t['initial_max_motion_m'], t['initial_max_rotation_degrees']) for k in quiet_roles)
    checks['latch_follows_frozen_xyz_axis'] = max(r['latch_off_axis_m'] for r in rows) <= t['max_off_axis_m'] and min(r['latch_signed_m'] for r in rows) >= -t['latch_initial_max_m']
    checks['latch_initial_joint_coordinate_quiet'] = bool(before) and all(abs(s['joints'][joints['latch']]['position_m']-latch0) <= t['latch_initial_max_m'] for s in before)
    checks['wheel_latch_door_events_ordered'] = all(v is not None for v in (wheel, latch, door, bridge)) and case['release_step'] < wheel <= latch < door <= bridge
    checks['door_is_bridge_before_physical_pin_release'] = all(v is not None for v in (bridge, bridge_confirm, pin, retainer_clear)) and bridge <= pin and bridge <= retainer_clear
    checks['pin_crosses_regions_in_order'] = pin is not None and all(v is not None for v in region_entries) and pin < region_entries[0] and all(a < b for a, b in zip(region_entries, region_entries[1:]))
    last_region = region_entries[-1]
    checks['door_remains_a_bridge_during_crossing'] = bridge is not None and last_region is not None and bridge <= last_region and all(bridge_flags[s['physics_steps']-1] for s in samples if bridge <= s['physics_steps'] <= last_region)
    checks['initial_pin_is_physically_restrained_by_actual_retainer'] = bool(before) and all(rows[s['physics_steps']-1]['retainer_pin_gap_m'] <= t['part_contact_tolerance_m'] for s in before) and contact_window(run, roles['retainer'], roles['rollingpin'], 0, before[-1]['physics_steps'] if before else None)['passed']
    tolerance = t['contact_window_tolerance_steps']
    paddle_touch_steps = [r['step'] for r in rows if wheel is not None and latch is not None and wheel <= r['step'] <= latch+tolerance and r['paddle_latch_gap_m'] <= t['part_contact_tolerance_m']]
    checks['actual_wheel_paddle_reaches_latch'] = bool(paddle_touch_steps)
    contacts = {
        'wheel_paddle_to_latch': contact_window(run, roles['wheel'], roles['latch'], wheel, latch, tolerance),
        'latch_releases_door': contact_window(run, roles['latch'], roles['door'], wheel, door, tolerance),
        'door_reaches_seat': contact_window(run, roles['door'], roles['seat'], bridge, bridge_confirm, tolerance),
        'rollingpin_travels_on_bridge': contact_window(run, roles['rollingpin'], roles['door'], pin, last_region, tolerance),
    }
    if case['release_step'] and case['trigger_id'] != roles['wheel']:
        contacts['trigger_to_wheel'] = contact_window(run, case['trigger_id'], roles['wheel'], case['release_step'], wheel, tolerance)
    checks['all_physical_handoff_contacts_witnessed'] = all(c['passed'] for c in contacts.values())
    report.update({'events': {'release': event_stamp(case['release_step'], dt), 'wheel_activation': event_stamp(wheel, dt), 'latch_clear': event_stamp(latch, dt), 'door_activation': event_stamp(door, dt), 'door_bridge': event_stamp(bridge, dt, bridge_confirm), 'rollingpin_release': event_stamp(pin, dt), 'retainer_clear': event_stamp(retainer_clear, dt)}, 'bridge_region_entry_steps': region_entries, 'contacts': contacts, 'paddle_latch_proximity_steps': paddle_touch_steps, 'motion_per_step': rows, 'geometry_scope': 'Frozen colliding compound box parts plus conservative primitive bounding extents. Root-body contact summaries cannot identify a compound subshape; measured part clearance supplies the separate part evidence.'})


def condition_matches(condition, sample, first, spec):
    kind = condition.get('kind')
    if kind == 'body_displacement':
        name = condition['body_id']
        if spec['objects'][name].get('dynamic') and path(name) not in sample.get('positions', {}):
            return False
        displacement = sub(pose(sample, spec, name)[0], pose(first, spec, name)[0])
        direction = condition.get('direction_world')
        if direction is not None and not unit(direction):
            raise ValueError('event direction_world must include a normalized XYZ direction')
        value = dot(displacement, direction) if direction is not None else math.sqrt(dot(displacement, displacement))
        return condition.get('minimum_m', -math.inf) <= value <= condition.get('maximum_m', math.inf)
    if kind == 'joint_coordinate':
        name, coordinate = condition['joint_id'], condition['coordinate']
        if coordinate not in ('position_m', 'angle_degrees'):
            raise ValueError('unsupported event joint coordinate')
        value = sample['joints'][name][coordinate]
        if condition.get('relative_to_initial', False):
            value -= first['joints'][name][coordinate]
        return condition.get('minimum', -math.inf) <= value <= condition.get('maximum', math.inf)
    if kind == 'contained_box':
        body, receiver = condition['body_id'], condition['receiver_id']
        if any(spec['objects'][n].get('dynamic') and path(n) not in sample.get('positions', {}) for n in (body, receiver)):
            return False
        size = spec['objects'][body].get('size')
        if spec['objects'][body].get('kind') != 'box' or not vector(size) or min(size) <= 0:
            raise ValueError('whole-box containment requires actual box dimensions')
        lower, upper = condition['inner_min_m'], condition['inner_max_m']
        if not vector(lower) or not vector(upper) or any(a >= b for a, b in zip(lower, upper)):
            raise ValueError('invalid frozen receiver interior bounds')
        p, q = pose(sample, spec, body)
        center, receiver_q = pose(sample, spec, receiver)
        inverse = [receiver_q[0], *[-v for v in receiver_q[1:]]]
        for x in (-.5, .5):
            for y in (-.5, .5):
                for z in (-.5, .5):
                    offset = rotate(q, [size[0]*x, size[1]*y, size[2]*z])
                    local = rotate(inverse, [a+b-c for a, b, c in zip(p, offset, center)])
                    if not all(a <= v <= b for a, v, b in zip(lower, local, upper)):
                        return False
        return True
    raise ValueError('unsupported event condition ' + str(kind))


def event_times(samples, spec, definitions, run=None):
    result = {}
    pending = dict(definitions)
    initial = baseline_observation(run, spec) if run is not None else samples[0]
    first_seen = {name: initial if path(name) in initial.get('positions', {}) else next((s for s in samples if path(name) in s.get('positions', {})), samples[0]) for name, obj in spec['objects'].items() if obj.get('dynamic')}
    while pending:
        progress = False
        for name, definition in list(pending.items()):
            if definition.get('kind') == 'spawn':
                body_id, step = definition['body_id'], definition['physics_step']
                if type(step) is not int or step <= 0 or spec['objects'][body_id].get('spawn_step') != step:
                    raise ValueError('spawn boundary must match the frozen initial trigger')
                matches = [e for e in (run or {}).get('spawn_events', []) if e.get('id') == body_id and e.get('physics_step') == step]
                result[name] = {'onset_step': step if len(matches) == 1 else None, 'confirmation_step': step if len(matches) == 1 else None}
                del pending[name]
                progress = True
                continue
            dependency = definition.get('after_event')
            if dependency and dependency not in result:
                if dependency not in definitions:
                    raise ValueError('event dependency is not frozen')
                continue
            hold = definition.get('hold_steps', 1)
            if type(hold) is not int or hold < 1 or not definition.get('conditions'):
                raise ValueError('events require conditions and positive hold_steps')
            start = definition.get('not_before_step', 1)
            if dependency:
                dependency_step = result[dependency]['confirmation_step']
                if dependency_step is None:
                    result[name] = {'onset_step': None, 'confirmation_step': None}
                    del pending[name]
                    progress = True
                    continue
                start = max(start, dependency_step+1)
            flags = [s['physics_steps'] >= start and all(condition_matches(c, s, first_seen.get(c.get('body_id'), initial), spec) for c in definition['conditions']) for s in samples]
            found = None
            for i in range(len(flags)-hold+1):
                if not all(flags[i:i+hold]):
                    continue
                stable = definition.get('stability')
                if stable:
                    if hold < 2 or not finite(stable.get('max_motion_m')) or stable['max_motion_m'] <= 0:
                        raise ValueError('stability needs at least two steps and positive max_motion_m')
                    points = [pose(s, spec, stable['body_id'])[0] for s in samples[i:i+hold]]
                    # Exact diameter; no center-only first/last approximation.
                    if any(math.dist(a, b) > stable['max_motion_m'] for j, a in enumerate(points) for b in points[j+1:]):
                        continue
                    if 'max_rotation_degrees' in stable:
                        rotations = [pose(s, spec, stable['body_id'])[1] for s in samples[i:i+hold]]
                        if any(angle_degrees(a, b) > stable['max_rotation_degrees'] for j, a in enumerate(rotations) for b in rotations[j+1:]):
                            continue
                found = i
                break
            result[name] = {'onset_step': samples[found]['physics_steps'] if found is not None else None, 'confirmation_step': samples[found+hold-1]['physics_steps'] if found is not None else None}
            del pending[name]
            progress = True
        if not progress:
            raise ValueError('cyclic event dependencies')
    return result


def measure_activity(run, spec, activity, dt=1/60):
    """Auditable union of task motion, with frozen event gates and world ROIs."""
    clock = timeline(run, spec, dt)
    strict = strict_initial_state(run, spec, activity, dt)
    passive = not run.get('followers') and not spec.get('drivers') and not spec.get('followers') and all(not any(o.get(k) for k in ('pose_follower', 'conveyor', 'driver', 'drive', 'motor', 'kinematic')) for o in spec.get('objects', {}).values()) and all(not s.get('followers') and all(j.get('drive_present') is False for j in s.get('joints', {}).values()) for s in run.get('samples', [])) and all(not j.get('drives') and not j.get('drive_attributes') for j in run.get('mechanism_configuration', {}).get('joints', []))
    report = {'passed': False, 'timeline': clock, 'strict_initial_state': strict, 'passive_sources': passive, 'formal_whole_room_acceptance': False, 'scope': 'Frozen task-phase/ROI body motion in original per-step simulation time; simultaneous sources count once. This metric alone does not establish whole-room causal acceptance. Receiver interior bounds require independent measurement before freezing.'}
    if not clock['passed'] or not strict['passed']:
        return report
    samples = run['samples']
    definitions = activity.get('events', {})
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError('activity must freeze event definitions')
    events = event_times(samples, spec, definitions, run)
    report['events'] = events
    window = activity['window']
    start = events[window['start_event']][window.get('start_time', 'onset')+'_step']
    end = events[window['end_event']][window.get('end_time', 'onset')+'_step']
    if start is None or end is None or end <= start:
        report['error'] = 'task-window boundary events missing or unordered'
        return report
    stages = activity.get('stages', [])
    if not stages or len({s['id'] for s in stages}) != len(stages):
        raise ValueError('activity needs distinct frozen task stages')
    flags = []
    for previous, current in zip(samples, samples[1:]):
        step = current['physics_steps']
        if not start < step <= end:
            continue
        sources, eligible_stages = set(), set()
        for stage in stages:
            stage_start = events[stage['start_event']][stage.get('start_time', 'onset')+'_step']
            stage_end = events[stage['end_event']][stage.get('end_time', 'onset')+'_step']
            if stage_start is None or stage_end is None or not stage_start < step <= stage_end:
                continue
            roi = stage['roi_world']
            lower, upper = roi['min'], roi['max']
            if not vector(lower) or not vector(upper) or any(a >= b for a, b in zip(lower, upper)):
                raise ValueError('freeze valid stage world ROI bounds')
            if not stage.get('purpose') or not stage.get('bodies'):
                raise ValueError('stages require task purpose and explicit physical body sources')
            for source in stage['bodies']:
                name = source['id']
                obj = spec['objects'].get(name, {})
                if not obj.get('dynamic') or obj.get('kind') in ('joint', 'camera'):
                    raise ValueError('activity sources must be measured dynamic bodies')
                linear = source.get('minimum_speed_m_s')
                angular = source.get('minimum_angular_speed_degrees_s')
                if not any(finite(v) and v > 0 for v in (linear, angular)) or any(v is not None and (not finite(v) or v <= 0) for v in (linear, angular)):
                    raise ValueError('freeze positive source motion thresholds')
                if path(name) not in previous.get('positions', {}) or path(name) not in current.get('positions', {}):
                    continue
                p0, q0 = pose(previous, spec, name)
                p1, q1 = pose(current, spec, name)
                if not all(all(a <= v <= b for a, v, b in zip(lower, point, upper)) for point in (p0, p1)):
                    continue
                speed, angular_speed = math.dist(p0, p1)/dt, angle_degrees(q0, q1)/dt
                if linear is not None and speed >= linear or angular is not None and angular_speed >= angular:
                    sources.add(name)
                    eligible_stages.add(stage['id'])
        flags.append({'physics_step': step, 'simulation_time_s': current['simulation_time_s'], 'active': bool(sources), 'body_ids': sorted(sources), 'stage_ids': sorted(eligible_stages)})
    expected = end-start
    if len(flags) != expected:
        report['error'] = 'missing interval inside task window'
        return report
    active = sum(f['active'] for f in flags)
    longest = idle = 0
    for flag in flags:
        idle = 0 if flag['active'] else idle+1
        longest = max(longest, idle)
    duration = expected*dt
    metrics = {'chain_duration_s': duration, 'net_effective_action_s': active*dt, 'motion_occupancy': active/expected, 'maximum_idle_s': longest*dt, 'window_start_step': start, 'window_end_step': end}
    limits = activity.get('limits', {})
    checks = {
        'minimum_chain_duration': duration >= limits.get('minimum_chain_duration_s', 0),
        'minimum_net_effective_action': active*dt >= limits.get('minimum_net_effective_action_s', 0),
        'minimum_motion_occupancy': active/expected >= limits.get('minimum_motion_occupancy', 0),
        'maximum_idle': longest*dt <= limits.get('maximum_idle_s', math.inf),
    }
    report.update({'passed': passive and all(checks.values()), 'checks': checks, 'metrics': metrics, 'per_step_motion_flags': flags})
    return report


def verify_run(directory, case_path=None, mode='positive', reference_run=None):
    """Verify hashes before reading acceptance telemetry; never writes a run."""
    from simscene.run_integrity import verify as verify_inputs
    from simscene.evidence_integrity import verify as verify_outputs
    root = Path(directory).expanduser().resolve()
    inputs, outputs = verify_inputs(root), verify_outputs(root)
    lock = json.loads((root/'run-lock.json').read_text())
    pinned = root/lock.get('acceptance_case_file', 'acceptance-case.json')
    selected = Path(case_path).expanduser().resolve() if case_path else pinned
    case_bytes = selected.read_bytes()
    digest = hashlib.sha256(case_bytes).hexdigest()
    case_pinned = digest == lock.get('acceptance_case_sha256') and pinned.is_file() and pinned.read_bytes() == case_bytes
    worker_pinned = bool(lock.get('worker_code_sha256')) and inputs.get('checks', {}).get('worker_code_snapshot') is True
    integrity = {'input_integrity': inputs, 'output_integrity': outputs, 'case_pinned_to_run': case_pinned, 'case_sha256': digest, 'runtime_worker_snapshot_pinned': worker_pinned, 'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if not inputs['passed'] or not outputs['passed'] or outputs.get('partial') is not False or not case_pinned or not worker_pinned:
        return {'passed': False, **integrity, 'scope': 'integrity failed; telemetry was not accepted'}
    if selected.suffix.lower() == '.json':
        case = json.loads(case_bytes)
    else:
        import yaml
        case = yaml.safe_load(case_bytes)
    reference_spec = None
    if reference_run:
        reference = Path(reference_run).expanduser().resolve()
        reference_report = verify_run(reference, case_path, 'positive')
        integrity['reference_positive_passed'] = reference_report['passed'] and reference_report.get('case_sha256') == digest
        integrity['reference_run'] = str(reference)
        reference_lock = json.loads((reference/'run-lock.json').read_text())
        integrity['paired_manifest_fields_match'] = {key: key in lock and key in reference_lock and lock[key] == reference_lock[key] for key in PAIRED_MANIFEST_FIELDS}
        integrity['paired_runtime_configuration_matches'] = all(integrity['paired_manifest_fields_match'].values())
        if reference_report['passed']:
            reference_spec = json.loads((reference/'spec.json').read_text())
    result = json.loads((root/'result.json').read_text())
    integrity['requested_steps_match_run_lock'] = type(lock.get('requested_physics_steps')) is int and lock['requested_physics_steps'] == result.get('requested_physics_steps')
    integrity['result_seed_matches_run_lock'] = 'seed' in result and 'seed' in lock and (lock['seed'] is None or type(lock['seed']) is int) and type(result['seed']) is type(lock['seed']) and result['seed'] == lock['seed']
    report = evaluate(result, json.loads((root/'spec.json').read_text()), case, mode, reference_spec, lock.get('physics_dt_s', 1/60))
    report.update(integrity)
    report['passed'] = bool(report['passed'] and integrity.get('reference_positive_passed', True) and integrity['requested_steps_match_run_lock'] and integrity['result_seed_matches_run_lock'] and integrity.get('paired_runtime_configuration_matches', True))
    if mode == 'positive':
        report['paired_control_required_for_causal_acceptance'] = case['mechanism'] == 'rope_drawer'
    elif report['passed']:
        report['paired_causal_acceptance'] = True
        report['wrapped_pulley_success'] = report.get('rope_model') == 'segmented_over_free_pulley'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('case', nargs='?')
    parser.add_argument('--mode', choices=('positive', 'detached_drawer'), default='positive')
    parser.add_argument('--reference-run')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        report = verify_run(args.run, args.case, args.mode, args.reference_run)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        report = {'passed': False, 'error': str(error), 'scope': 'invalid or incomplete evidence'}
    serialized = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        protected = [Path(args.run).expanduser().resolve()]
        if args.reference_run:
            protected.append(Path(args.reference_run).expanduser().resolve())
        if any(output.is_relative_to(p) for p in protected) or args.case and output == Path(args.case).expanduser().resolve():
            parser.error('acceptance output must be outside immutable runs and cannot overwrite the frozen case')
        output.write_text(serialized+'\n')
    print(serialized)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
