"""Offline acceptance of one pinned two-DOF native tree, never command echoes.

The two driven coordinates are compared to both path-keyed PhysX tensor q/v
and same-sample body frames.  Link linear velocities are at each link's center
of mass; the recorded cooked COM is needed to reconstruct anchor velocities.
"""
import json
import math
from pathlib import Path
import re

SCHEMA = 'simscene.articulated_asset_two_joint.v1'
_NATIVE = 'PhysX_articulation_tensor_DOF_readback_SI'
_RECONSTRUCTED = 'same_sample_PhysX_body_poses_joint_frame_reconstruction'
_JOINT_FIELDS = {'joint_path', 'parent_body', 'child_body', 'type', 'axis', 'limits', 'position_unit',
                 'initial_position', 'initial_tolerance', 'coordinate_tolerance', 'velocity_tolerance',
                 'anchor_tolerance_m', 'angular_tolerance_rad'}
_PHASE_FIELDS = {'joint_id', 'command_step', 'by_step', 'target_position', 'target_tolerance', 'min_travel',
                 'other_target_position', 'other_target_tolerance', 'max_other_drift',
                 'stiffness', 'damping', 'max_effort', 'hold_command'}
_BINDING_FIELDS = ('joint_path', 'parent_body', 'child_body', 'type', 'axis', 'limits', 'position_unit')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _strictly_below(value, upper):
    return value < upper and not math.isclose(value, upper, rel_tol=1e-12, abs_tol=0.)


def validate_case(case):
    """Validate a single object, exactly two joint identities and disjoint stages."""
    from ..catalog.models import AssetRef
    from ..scene import _id
    from ..worker.mechanism import _path
    required = {'schema', 'schema_version', 'mode', 'physics_dt_s', 'objects'}
    if (not isinstance(case, dict) or not required <= set(case) or set(case) - required - {'physics_device'}
            or case['schema'] != SCHEMA or type(case['schema_version']) is not int or case['schema_version'] != 1
            or case['mode'] != 'driven' or not _number(case['physics_dt_s']) or case['physics_dt_s'] <= 0
            or 'physics_device' in case and case['physics_device'] not in ('default', 'cpu', 'gpu')):
        raise ValueError('invalid versioned two-joint acceptance case')
    objects = case['objects']
    if not isinstance(objects, dict) or len(objects) != 1:
        raise ValueError('two-joint acceptance requires one selected object')
    name, obj = next(iter(objects.items()))
    _id(name)
    if (not isinstance(obj, dict) or set(obj) != {'prepared_manifest_sha256', 'source_ref', 'joints', 'phases'}
            or not isinstance(obj['prepared_manifest_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', obj['prepared_manifest_sha256'])):
        raise ValueError('selected object requires a pinned prepared manifest')
    AssetRef.from_dict(obj['source_ref']).validate_selection()
    joints = obj['joints']
    if not isinstance(joints, dict) or len(joints) != 2:
        raise ValueError('two distinct frozen joint identities are required')
    paths = set()
    asset_prefix = '/World/' + name.replace('-', '_') + '/Asset/'
    for joint_id, joint in joints.items():
        _id(joint_id)
        if not isinstance(joint, dict) or set(joint) != _JOINT_FIELDS:
            raise ValueError('invalid frozen joint case fields')
        if not all(_path(joint[key]) and joint[key].startswith(asset_prefix)
                   for key in ('joint_path', 'parent_body', 'child_body')):
            raise ValueError('explicit absolute joint and link paths are required')
        if joint['parent_body'] == joint['child_body'] or joint['joint_path'] in paths:
            raise ValueError('joint paths and endpoints must be distinct')
        paths.add(joint['joint_path'])
        unit = {'revolute': 'rad', 'prismatic': 'm'}.get(joint['type'])
        limits = joint['limits']
        if (unit is None or joint['position_unit'] != unit or joint['axis'] not in ('X', 'Y', 'Z')
                or not isinstance(limits, list) or len(limits) != 2 or not all(_number(x) for x in limits)
                or limits[0] >= limits[1] or not math.isfinite(limits[1] - limits[0])
                or unit == 'rad' and limits[1] - limits[0] >= 2 * math.pi):
            raise ValueError('invalid scalar joint type, units, axis or limits')
        for key in ('initial_position', 'initial_tolerance', 'coordinate_tolerance', 'velocity_tolerance',
                    'anchor_tolerance_m', 'angular_tolerance_rad'):
            if not _number(joint[key]) or key != 'initial_position' and joint[key] <= 0:
                raise ValueError('invalid initial coordinate or tolerance')
        span = limits[1] - limits[0]
        speed_cap = .05 if unit == 'm' else .1
        if (joint['anchor_tolerance_m'] > .005 or joint['angular_tolerance_rad'] > .05
                or joint['velocity_tolerance'] > speed_cap
                or not _strictly_below(joint['coordinate_tolerance'] / span, .01)
                or not _strictly_below(joint['initial_tolerance'] / span, .01)
                or not _strictly_below(joint['velocity_tolerance'] / span * case['physics_dt_s'], .01)):
            raise ValueError('joint measurement tolerances exceed their physical-scale bounds')
        if not limits[0] <= joint['initial_position'] <= limits[1]:
            raise ValueError('initial coordinate outside frozen limits')
    phases = obj['phases']
    if not isinstance(phases, list) or not 2 <= len(phases) <= 128:
        raise ValueError('two or more bounded independent drive phases are required')
    last_end = -1
    driven = set()
    for phase in phases:
        if (not isinstance(phase, dict) or set(phase) != _PHASE_FIELDS
                or not isinstance(phase['joint_id'], str) or phase['joint_id'] not in joints):
            raise ValueError('invalid two-joint drive phase')
        start, end = phase['command_step'], phase['by_step']
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or start < last_end:
            raise ValueError('drive phases must be ordered and not overlap')
        last_end = end
        joint = joints[phase['joint_id']]
        other_id = next(key for key in joints if key != phase['joint_id'])
        other = joints[other_id]
        for key in _PHASE_FIELDS - {'joint_id', 'command_step', 'by_step', 'hold_command'}:
            if not _number(phase[key]):
                raise ValueError('phase parameters must be finite')
        for key in ('target_tolerance', 'min_travel', 'other_target_tolerance', 'stiffness', 'max_effort'):
            if phase[key] <= 0:
                raise ValueError('phase targets, motion and drive tolerances must be positive')
        if phase['damping'] < 0 or phase['max_other_drift'] < 0:
            raise ValueError('negative damping or drift is unsupported')
        hold = phase['hold_command']
        if hold is not None and (not isinstance(hold, dict) or set(hold) != {'stiffness', 'damping', 'max_effort'}
                or any(not _number(hold[key]) for key in hold) or hold['stiffness'] <= 0
                or hold['damping'] < 0 or hold['max_effort'] <= 0):
            raise ValueError('invalid explicit other-joint holding drive')
        if (not joint['limits'][0] <= phase['target_position'] <= joint['limits'][1]
                or not other['limits'][0] <= phase['other_target_position'] <= other['limits'][1]
                or phase['min_travel'] > joint['limits'][1] - joint['limits'][0]):
            raise ValueError('phase target or travel outside joint limits')
        # Compare held and moving tolerances as fractions of their respective
        # joint spans, so a slider and hinge remain dimensionally comparable.
        moving_span = joint['limits'][1] - joint['limits'][0]
        other_span = other['limits'][1] - other['limits'][0]
        relative_budget = .2 * phase['min_travel'] / moving_span
        if (not _strictly_below(phase['target_tolerance'] / moving_span, relative_budget)
                or not _strictly_below(phase['other_target_tolerance'] / other_span, relative_budget)
                or not _strictly_below(phase['max_other_drift'] / other_span, relative_budget)):
            raise ValueError('phase tolerances are too large relative to required travel')
        motion = phase['min_travel']
        if (not _strictly_below(joint['coordinate_tolerance'] / motion, .1)
                or not _strictly_below(joint['initial_tolerance'] / motion, .1)
                or joint['type'] == 'prismatic' and not _strictly_below(joint['anchor_tolerance_m'] / motion, .1)
                or joint['type'] == 'revolute' and not _strictly_below(joint['angular_tolerance_rad'] / motion, .1)):
            raise ValueError('joint measurement tolerances are too large relative to required travel')
        driven.add(phase['joint_id'])
    if driven != set(joints):
        raise ValueError('both independent coordinates must be driven in separate phases')
    return case


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _cross(a, b):
    return [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]


def _instantaneous_velocity(joint, frame, coms):
    """Reconstruct SI DOF speed from link poses and COM-relative tensor speeds."""
    from ..worker.mechanism import _mul, _quaternion, _rotate, _vector
    anchors = []
    rotations = []
    angular = []
    velocities = []
    for suffix, body in (('0', joint['parent_body']), ('1', joint['child_body'])):
        position = _vector(frame.get('positions', {}).get(body), 3, 'actual link position')
        q = _quaternion(frame.get('orientations_wxyz', {}).get(body))
        linear = _vector(frame.get('linear_velocities_m_s', {}).get(body), 3, 'link COM linear velocity')
        omega = _vector(frame.get('angular_velocities_rad_s', {}).get(body), 3, 'link angular velocity')
        local_anchor = _vector(joint['local_pos' + suffix + '_m'], 3, 'joint anchor')
        com = _vector(coms[body], 3, 'cooked link center of mass')
        lever = _rotate(q, _sub(local_anchor, com))
        anchor = _rotate(q, local_anchor)
        anchors.append([x + y for x, y in zip(position, anchor)])
        velocities.append([x + y for x, y in zip(linear, _cross(omega, lever))])
        angular.append(omega)
        rotations.append(_mul(q, joint['local_rot' + suffix + '_wxyz']))
    axis = [0., 0., 0.]
    axis[('X', 'Y', 'Z').index(joint['axis'])] = 1.
    world_axis = _rotate(rotations[0], axis)
    if joint['type'] == 'revolute':
        difference = _sub(angular[1], angular[0])
    else:
        # A moving parent joint frame rotates the translation basis as well.
        difference = _sub(_sub(velocities[1], velocities[0]),
                          _cross(angular[0], _sub(anchors[1], anchors[0])))
    return sum(a * b for a, b in zip(world_axis, difference))


def _commands(joints, phases):
    commands = []
    for phase in phases:
        joint_id = phase['joint_id']
        commands.append({'joint_id': joint_id, 'trigger': {'type': 'at_step', 'physics_step': phase['command_step']},
                         'target_position': phase['target_position'], 'position_unit': joints[joint_id]['position_unit'],
                         **{key: phase[key] for key in ('stiffness', 'damping', 'max_effort')}})
        if phase['hold_command'] is not None:
            other = next(key for key in joints if key != phase['joint_id'])
            commands.append({'joint_id': other, 'trigger': {'type': 'at_step', 'physics_step': phase['command_step']},
                             'target_position': phase['other_target_position'], 'position_unit': joints[other]['position_unit'],
                             **phase['hold_command']})
    return commands


def _check_events(frames, name, joints, phases):
    from ..worker.mechanism import usd_drive_values
    final = frames[-1]['mechanisms'][name]['command_events']
    commands = _commands(joints, phases)
    if not isinstance(final, list) or len(final) != len(commands):
        return False
    for index, (event, command) in enumerate(zip(final, commands)):
        if not isinstance(event, dict):
            return False
        joint_id = command['joint_id']
        step = command['trigger']['physics_step']
        target = command['target_position']
        joint = joints[joint_id]
        if (type(event.get('command_index')) is not int or event['command_index'] != index or event.get('joint_id') != joint_id
                or event.get('joint_path') != joint['joint_path'] or type(event.get('physics_step')) is not int
                or event['physics_step'] != step or not isinstance(event.get('trigger'), dict)
                or type(event['trigger'].get('physics_step')) is not int
                or event.get('trigger') != {'type': 'at_step', 'physics_step': step}
                or event.get('position_unit') != joint['position_unit']
                or event.get('cause') != 'declared_at_step_schedule'
                or not _number(event.get('target_position'))
                or abs(event['target_position'] - target) > 1e-12):
            return False
        expected = usd_drive_values(joint, command)
        actual = event.get('drive_readback')
        if not isinstance(actual, dict) or actual.get('scope') != 'loaded_USD_drive_attributes':
            return False
        for key, value in expected.items():
            observed = actual.get(key)
            if isinstance(value, str):
                if observed != value:
                    return False
            elif not _number(observed) or abs(observed - value) > max(1e-6, abs(value) * 1e-5):
                return False
    for frame in frames:
        step = frame['physics_steps']
        # Step zero is commanded during initialization. Later commands are
        # applied after observing their named step and before the next step.
        count = sum(command['trigger']['physics_step'] == 0 or command['trigger']['physics_step'] < step
                    for command in commands)
        if frame['mechanisms'][name].get('command_events') != final[:count]:
            return False
    return True


def evaluate(run, case):
    """Evaluate recorded frames; malformed or incomplete evidence fails closed."""
    validate_case(case)
    try:
        return _evaluate(run, case)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return {'schema_version': 1, 'passed': False, 'checks': {'valid_measurements': False},
                'objects': {}, 'errors': [str(error)]}


def _evaluate(run, case):
    from ..worker.mechanism import measure_joint
    from ..worker.mechanism_v2 import TwoDofTensorState
    if not isinstance(run, dict):
        raise ValueError('run must be an object')
    name, obj = next(iter(case['objects'].items()))
    dt = case['physics_dt_s']
    steps = run.get('actual_physics_steps')
    frames = [run.get('initial_observation')] + run.get('samples', [])
    zero = run.get('run_zero_absolute_physics_step')
    absolute_time = run.get('run_zero_absolute_simulation_time_s')
    checks = {
        'full_physics_steps': type(steps) is int and steps > 0 and type(run.get('requested_physics_steps')) is int
            and steps == run['requested_physics_steps'],
        'not_partial': run.get('partial') is False and run.get('evidence_incomplete', False) is False,
        'samples_not_truncated': run.get('samples_truncated') is False,
        'task_not_failed': run.get('task_status') in ('unverified', 'completed'),
        'no_followers': isinstance(run.get('followers'), dict) and not run['followers'],
        'complete_per_step_timeline': False,
        'observed_physics_timestep': False,
        'observed_device_configuration': False,
    }
    checks['complete_per_step_timeline'] = (checks['full_physics_steps'] and run.get('observation_interval_steps') == 1
        and type(zero) is int and zero >= 0 and _number(absolute_time) and len(frames) == steps + 1
        and all(isinstance(frame, dict) and type(frame.get('physics_steps')) is int and frame['physics_steps'] == i
            and type(frame.get('absolute_physics_step')) is int and frame['absolute_physics_step'] == zero + i
            and _number(frame.get('simulation_time_s'))
            and abs(frame['simulation_time_s'] - i * dt) <= 1e-6 and _number(frame.get('absolute_simulation_time_s'))
            and abs(frame['absolute_simulation_time_s'] - absolute_time - i * dt) <= 1e-5
            for i, frame in enumerate(frames)) and _number(run.get('simulation_time_s'))
        and abs(run['simulation_time_s'] - steps * dt) <= 1e-6)
    settings = run.get('physics_settings', {})
    checks['observed_physics_timestep'] = all(
        isinstance(settings.get(key), dict) and _number(settings[key].get('authored_time_steps_per_second'))
        and abs(settings[key]['authored_time_steps_per_second'] * dt - 1.) <= 1e-5
        for key in ('before_warmup', 'after_run')) if isinstance(settings, dict) else False
    if isinstance(settings, dict):
        devices = []
        valid_device = True
        for key in ('before_warmup', 'after_run'):
            info = settings.get(key)
            if not isinstance(info, dict):
                valid_device = False
                break
            requested = info.get('requested_device')
            devices.append(requested)
            if requested not in ('default', 'cpu', 'gpu') or ('physics_device' in case and requested != case['physics_device']):
                valid_device = False
            elif requested == 'default':
                valid_device &= info.get('request_matches_observation') is None
            else:
                valid_device &= (info.get('request_matches_observation') is True
                                 and info.get('enable_gpu_dynamics') is (requested == 'gpu'))
        checks['observed_device_configuration'] = bool(valid_device and len(devices) == 2 and devices[0] == devices[1])
    if not checks['complete_per_step_timeline']:
        return {'schema_version': 1, 'passed': False, 'checks': checks, 'objects': {}}
    binding = run.get('body_bindings', {}).get(name)
    TwoDofTensorState._validate_binding(binding)
    if binding.get('profile_id') != 'articulated_prop_v2' or set(binding['joints']) != set(obj['joints']):
        raise ValueError('binding is not the selected two-joint profile')
    joints = binding['joints']
    if any(any(joints[joint_id].get(key) != expected[key] for key in _BINDING_FIELDS)
           for joint_id, expected in obj['joints'].items()):
        raise ValueError('runtime joint binding differs from the frozen case')
    mass = run.get('mechanism_configuration', {}).get('mass_properties_by_prim_path', {})
    coms = {}
    for body in binding['motion_bodies']:
        data = mass.get(body)
        if (not isinstance(data, dict) or type(data.get('observed_at_physics_step')) is not int
                or data['observed_at_physics_step'] != 0
                or not isinstance(data.get('source'), str) or 'PhysX' not in data['source']):
            raise ValueError('native cooked link center of mass is missing')
        values = data.get('center_of_mass_local_m')
        if not isinstance(values, (list, tuple)) or len(values) != 3 or not all(_number(v) for v in values):
            raise ValueError('native cooked link center of mass is invalid')
        coms[body] = values
    actual = {key: [] for key in joints}
    previous = {}
    joint_reports = {key: {'max_anchor_error_m': 0., 'max_locked_rotation_error_rad': 0., 'max_native_position_error': 0.,
                           'max_native_velocity_error': 0.} for key in joints}
    for frame in frames:
        step = frame['physics_steps']
        mechanism = frame['mechanisms'][name]
        if type(mechanism.get('physics_step')) is not int or mechanism['physics_step'] != step or set(mechanism['joints']) != set(joints):
            raise ValueError('frame joint observations differ from the frozen binding')
        if frame.get('native_joint_measurement_source') != _NATIVE:
            raise ValueError('native tensor measurement source is missing')
        for key, joint in joints.items():
            expected = obj['joints'][key]
            path = joint['joint_path']
            native_position = frame['native_joint_positions'][path]
            native_velocity = frame['native_joint_velocities'][path]
            record = mechanism['joints'][key]
            measured = measure_joint(joint, frame, previous.get(key), physics_step=step, physics_dt_s=dt,
                                     require_unique_initial=True)
            if (not _number(native_position) or not _number(native_velocity) or not isinstance(record, dict)
                    or record.get('joint_path') != path or record.get('parent_body') != joint['parent_body']
                    or record.get('child_body') != joint['child_body'] or type(record.get('physics_step')) is not int
                    or record['physics_step'] != step
                    or record.get('position_unit') != joint['position_unit']
                    or record.get('velocity_unit') != joint['position_unit'] + '/s'
                    or record.get('measurement_source') != _RECONSTRUCTED
                    or record.get('native_measurement_source') != _NATIVE
                    or not _number(record.get('position')) or abs(record['position'] - measured['position']) > 1e-6
                    or not _number(record.get('native_position')) or abs(record['native_position'] - native_position) > 1e-9
                    or not _number(record.get('native_velocity')) or abs(record['native_velocity'] - native_velocity) > 1e-9
                    or not _number(record.get('anchor_error_m')) or abs(record['anchor_error_m'] - measured['anchor_error_m']) > 1e-6
                    or not _number(record.get('locked_rotation_error_rad'))
                    or abs(record['locked_rotation_error_rad'] - measured['locked_rotation_error_rad']) > 1e-6):
                raise ValueError('native DOF or reconstructed joint observation differs from its same-step paths')
            if step == 0:
                if record.get('velocity') is not None:
                    raise ValueError('initial finite-difference velocity must be unknown')
            elif not _number(record.get('velocity')) or abs(record['velocity'] - measured['velocity']) > 1e-5:
                raise ValueError('recorded finite-difference velocity differs from body frames')
            instant = _instantaneous_velocity(joint, frame, coms)
            q_error = abs(native_position - measured['position'])
            v_error = abs(native_velocity - instant)
            if (q_error > expected['coordinate_tolerance'] or v_error > expected['velocity_tolerance']
                    or measured['anchor_error_m'] > expected['anchor_tolerance_m']
                    or measured['locked_rotation_error_rad'] > expected['angular_tolerance_rad']
                    or not expected['limits'][0] - expected['coordinate_tolerance'] <= native_position
                    <= expected['limits'][1] + expected['coordinate_tolerance']):
                raise ValueError('native q/v, frame reconstruction, limits or anchor check failed')
            previous[key] = measured
            actual[key].append(native_position)
            report = joint_reports[key]
            report['max_anchor_error_m'] = max(report['max_anchor_error_m'], measured['anchor_error_m'])
            report['max_locked_rotation_error_rad'] = max(report['max_locked_rotation_error_rad'], measured['locked_rotation_error_rad'])
            report['max_native_position_error'] = max(report['max_native_position_error'], q_error)
            report['max_native_velocity_error'] = max(report['max_native_velocity_error'], v_error)
    phase_reports = []
    for phase in obj['phases']:
        start, end = phase['command_step'], phase['by_step']
        if end >= len(frames):
            raise ValueError('phase ends outside recorded physics timeline')
        key = phase['joint_id']
        other = next(item for item in joints if item != key)
        values = actual[key][start:end+1]
        held = actual[other][start:end+1]
        travel = max(values) - min(values)
        displacement = abs(values[-1] - values[0])
        drift = max(abs(value - held[0]) for value in held)
        phase_checks = {
            'target_reached': abs(values[-1] - phase['target_position']) <= phase['target_tolerance'],
            'measured_travel': travel >= phase['min_travel'] and displacement >= phase['min_travel'],
            'other_target_held': all(abs(value - phase['other_target_position']) <= phase['other_target_tolerance'] for value in held),
            'other_drift_within_limit': drift <= phase['max_other_drift'],
        }
        phase_reports.append({'joint_id': key, 'joint_path': joints[key]['joint_path'], 'other_joint_id': other,
                              'command_step': start, 'by_step': end, 'observed_travel': travel,
                              'observed_net_displacement': displacement, 'max_other_drift': drift,
                              'final_position': values[-1], 'checks': phase_checks,
                              'passed': all(phase_checks.values())})
    object_checks = {
        'initial_coordinates_match': all(abs(actual[key][0] - item['initial_position']) <= item['initial_tolerance']
                                         for key, item in obj['joints'].items()),
        'command_events_match': _check_events(frames, name, joints, obj['phases']),
        'all_phases_passed': all(phase['passed'] for phase in phase_reports),
        'full_actual_measurements': True,
    }
    result = {'checks': object_checks, 'joints': joint_reports, 'phases': phase_reports,
              'passed': all(object_checks.values())}
    checks['all_objects_passed'] = result['passed']
    return {'schema_version': 1, 'passed': all(checks.values()), 'checks': checks, 'objects': {name: result},
            'negative_control': {'status': 'not_evaluated',
                'scope': 'A matched frozen control run and its paired comparison must be verified externally.'},
            'scope': 'one run of two scheduled coordinates, independent native and body-frame measurements; no paired-control, contact-triggered or robot-control claim'}


def _pin_manifest(manifest, binding, name):
    """Match the whole resolved joint tree to the already hash-checked manifest."""
    from ..physics_binding import _relative
    from ..preparation.articulation_v2 import runtime_joint
    if manifest.get('profile_id') != 'articulated_prop_v2' or binding.get('profile_id') != 'articulated_prop_v2':
        raise ValueError('selected object is not a two-DOF prepared profile')
    body_map = manifest['body_map']
    joint_map = manifest['joint_map']
    report = manifest['articulation_report']
    if report.get('body_map') != body_map or report.get('joint_map') != joint_map:
        raise ValueError('prepared joint graph differs from its inspected graph')
    base = '/World/' + name.replace('-', '_') + '/Asset'
    def path(relative):
        relative = _relative(relative, allow_root=True)
        return base + ('/' + relative if relative else '')
    paths = {local_id: path(item['relative_prim_path']) for local_id, item in body_map.items()}
    if (set(binding['motion_bodies']) != set(paths.values()) or binding['root_body'] != paths[report['root_body_id']]
            or set(binding['joints']) != set(joint_map)):
        raise ValueError('runtime link tree differs from the prepared manifest')
    for key, item in joint_map.items():
        expected = dict(runtime_joint(item), joint_path=path(item['relative_prim_path']),
                        parent_body=paths[item['parent_body_id']], child_body=paths[item['child_body_id']])
        if binding['joints'][key] != expected:
            raise ValueError('runtime joint tree differs from the prepared manifest')


def verify_run(directory, case_path=None):
    """Check frozen case, selection, all inputs and complete evidence hashes."""
    from ..cache import _sha256
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    from ..physics_binding import validate_asset_binding
    root = Path(directory)
    for name in ('run-lock.json', 'acceptance-case.json', 'spec.json', 'result.json'):
        if (root / name).is_symlink():
            raise ValueError('two-joint acceptance requires ordinary frozen files')
    lock = json.loads((root / 'run-lock.json').read_text())
    frozen = root / 'acceptance-case.json'
    expected = lock.get('acceptance_case_sha256')
    if (lock.get('acceptance_case_file') != 'acceptance-case.json' or not isinstance(expected, str)
            or _sha256(frozen) != expected or case_path is not None and _sha256(Path(case_path)) != expected):
        raise ValueError('two-joint acceptance case differs from the frozen case')
    case = json.loads(frozen.read_text())
    validate_case(case)
    run = json.loads((root / 'result.json').read_text())
    result = evaluate(run, case)
    checks = result['checks']
    checks['bindings_pinned_to_run'] = (isinstance(lock.get('body_bindings'), dict)
        and bool(lock['body_bindings']) and run.get('body_bindings') == lock['body_bindings'])
    checks['timing_pinned_to_run'] = (_number(lock.get('physics_dt_s'))
        and abs(lock['physics_dt_s'] - case['physics_dt_s']) <= 1e-12
        and type(lock.get('requested_physics_steps')) is int
        and lock['requested_physics_steps'] == run.get('requested_physics_steps'))
    settings = run.get('physics_settings', {})
    checks['device_pinned_to_run'] = (lock.get('physics_device') in ('default', 'cpu', 'gpu')
        and isinstance(settings, dict) and all(isinstance(settings.get(key), dict)
        and settings[key].get('requested_device') == lock['physics_device']
        for key in ('before_warmup', 'after_run'))
        and ('physics_device' not in case or case['physics_device'] == lock['physics_device']))
    checks['prepared_selection_pinned'] = False
    checks['commands_pinned_to_spec'] = False
    errors = []
    try:
        spec = json.loads((root / 'spec.json').read_text())
        name, item = next(iter(case['objects'].items()))
        obj = spec['objects'][name]
        if obj.get('kind') != 'asset' or obj.get('dynamic') is not True:
            raise ValueError('selected object must be one dynamic prepared asset')
        checks['commands_pinned_to_spec'] = obj.get('mechanism') == {'commands': _commands(item['joints'], item['phases'])}
        selection = obj['asset_binding']
        if selection['manifest_sha256'] != item['prepared_manifest_sha256']:
            raise ValueError('prepared manifest differs from the frozen case')
        manifest = validate_asset_binding(selection, require_dynamic=True, asset_path=obj['asset_path'])
        if manifest.get('source_ref') != item['source_ref']:
            raise ValueError('source reference differs from the frozen case')
        _pin_manifest(manifest, run['body_bindings'][name], name)
        checks['prepared_selection_pinned'] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        errors.append(str(error))
    try:
        inputs = verify_inputs(root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        inputs = {'passed': False, 'errors': [str(error)]}
    try:
        evidence = verify_evidence(root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        evidence = {'passed': False, 'partial': None, 'errors': [str(error)]}
    result.update(input_integrity=inputs, evidence_integrity=evidence, case_pinned_to_run=True, errors=errors)
    result['passed'] = bool(all(checks.values()) and inputs.get('passed') is True
                            and evidence.get('passed') is True and evidence.get('partial') is False)
    return result
