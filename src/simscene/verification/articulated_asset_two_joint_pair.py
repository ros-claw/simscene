"""Verify a driven two-joint run against its matched, frozen control run.

The control omits only the second phase's drive command. Both input closures,
recorded evidence and every physical sample are checked by the single-run
verifier; its expected control failure is not, by itself, a control pass.
"""
import copy
import json
import os
from pathlib import Path
import re

from . import articulated_asset_two_joint as single


_WORKER_FILES = frozenset({'worker/isaac_run.py', 'worker/initial_state.py',
                           'worker/mechanism.py', 'worker/mechanism_v2.py'})
_CONTROL_REQUIRED = frozenset({'full_physics_steps', 'not_partial', 'samples_not_truncated',
    'task_not_failed', 'no_followers', 'complete_per_step_timeline', 'observed_physics_timestep',
    'observed_device_configuration', 'bindings_pinned_to_run', 'timing_pinned_to_run',
    'device_pinned_to_run', 'prepared_selection_pinned'})


def _document(root, name):
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('paired run requires an ordinary frozen file: ' + name)
    value = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(value, dict):
        raise ValueError('paired run document must be an object: ' + name)
    return value


def _normalize(value, root):
    """Keep semantic scene content, replacing only this run's storage prefix."""
    if isinstance(value, dict):
        return {key: _normalize(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, str):
        prefix = str(root) + os.sep
        if value.startswith(prefix):
            return '${RUN}/' + value[len(prefix):]
    return value


def _scene(spec, root):
    result = copy.deepcopy(spec)
    for key in ('scene_id', 'revision', 'requests'):
        result.pop(key, None)
    return _normalize(result, root)


def _stage(root):
    path = root / 'scene.usda'
    if path.is_symlink() or not path.is_file():
        raise ValueError('paired run requires an ordinary frozen stage')
    return path.read_bytes().replace((str(root) + os.sep).encode(), b'${RUN}/')


def _same_runtime(first, second, positive, control):
    """Compare identities that can change simulation while ignoring run IDs."""
    keys = ('runtime_version', 'runtime_python_sha256', 'worker_code_sha256', 'seed',
            'physics_device', 'physics_dt_s', 'requested_physics_steps')
    if any(key not in first or key not in second or first[key] != second[key] for key in keys):
        return False
    if (not isinstance(first['runtime_version'], str) or not first['runtime_version']
            or not isinstance(first['runtime_python_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', first['runtime_python_sha256'])
            or type(first['seed']) is not int or not 0 <= first['seed'] < 2**32
            or type(positive.get('seed')) is not int or type(control.get('seed')) is not int
            or positive.get('seed') != first['seed'] or control.get('seed') != second['seed']
            or first['physics_device'] not in ('default', 'cpu', 'gpu')
            or not single._number(first['physics_dt_s']) or first['physics_dt_s'] <= 0
            or type(first['requested_physics_steps']) is not int or first['requested_physics_steps'] <= 0):
        return False
    hashes = first['worker_code_sha256']
    if (not isinstance(hashes, dict) or not _WORKER_FILES <= set(hashes)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                   for value in hashes.values())):
        return False
    for key in ('queue_launcher_python_sha256', 'gpu_selection',
                'continue_on_controller_error', 'archive_verified_objects'):
        if first.get(key) != second.get(key):
            return False
    return True


def _control_events(positive, control, name, omitted_index, commands):
    """Require every observed control event to match the frozen command prefix."""
    positive_frames = [positive['initial_observation'], *positive['samples']]
    control_frames = [control['initial_observation'], *control['samples']]
    positive_events = positive_frames[-1]['mechanisms'][name]['command_events']
    if not isinstance(positive_events, list) or len(positive_events) != len(commands) + 1:
        return False
    expected = copy.deepcopy(positive_events)
    expected.pop(omitted_index)
    for index, event in enumerate(expected):
        event['command_index'] = index
    for frame in control_frames:
        step = frame['physics_steps']
        count = sum(command['trigger']['physics_step'] == 0 or command['trigger']['physics_step'] < step
                    for command in commands)
        if frame['mechanisms'][name].get('command_events') != expected[:count]:
            return False
    return True


def verify_pair(positive_directory, control_directory, case_path=None):
    """Return a fail-closed comparison of two independent sealed runs.

    Exactly two phases are supported. The control must keep every first-phase
    command, including an optional hold, and omit the unique second-phase
    drive. Its second joint must remain within that phase's target tolerance of
    its own starting value and fail the original target and minimum-travel
    requirements. File hashes establish consistency, not signed authenticity.
    """
    checks = {name: False for name in ('distinct_runs', 'same_frozen_case', 'positive_passed',
        'same_runtime_seed_device_and_steps', 'same_scene', 'same_stage', 'same_body_bindings',
        'control_input_and_evidence_valid', 'control_only_second_drive_removed',
        'control_command_events_match', 'control_first_phase_passed', 'control_other_joint_held',
        'control_target_stationary', 'control_target_not_reached', 'control_travel_insufficient')}
    result = {'schema_version': 1, 'passed': False, 'checks': checks, 'errors': [],
              'scope': 'two sealed, matched runs; no claim of signed authenticity or contact causality'}
    try:
        positive_root = Path(positive_directory).expanduser().resolve()
        control_root = Path(control_directory).expanduser().resolve()
        positive_lock = _document(positive_root, 'run-lock.json')
        control_lock = _document(control_root, 'run-lock.json')
        positive_id, control_id = positive_lock.get('run_id'), control_lock.get('run_id')
        checks['distinct_runs'] = (positive_root != control_root and isinstance(positive_id, str)
            and isinstance(control_id, str) and bool(positive_id) and bool(control_id) and positive_id != control_id)
        positive_case = _document(positive_root, 'acceptance-case.json')
        control_case = _document(control_root, 'acceptance-case.json')
        single.validate_case(positive_case)
        single.validate_case(control_case)
        from ..cache import _sha256
        case_hash = _sha256(positive_root / 'acceptance-case.json')
        checks['same_frozen_case'] = (positive_case == control_case
            and case_hash == _sha256(control_root / 'acceptance-case.json')
            and positive_lock.get('acceptance_case_sha256') == case_hash
            and control_lock.get('acceptance_case_sha256') == case_hash
            and (case_path is None or _sha256(Path(case_path)) == case_hash))

        positive_report = single.verify_run(positive_root, case_path=case_path)
        control_report = single.verify_run(control_root, case_path=case_path)
        result['positive'] = positive_report
        result['control'] = control_report
        checks['positive_passed'] = positive_report.get('passed') is True
        positive = _document(positive_root, 'result.json')
        control = _document(control_root, 'result.json')
        positive_spec = _document(positive_root, 'spec.json')
        control_spec = _document(control_root, 'spec.json')
        checks['same_runtime_seed_device_and_steps'] = _same_runtime(positive_lock, control_lock, positive, control)
        checks['same_body_bindings'] = (isinstance(positive.get('body_bindings'), dict)
            and positive['body_bindings'] == control.get('body_bindings'))
        checks['same_stage'] = _stage(positive_root) == _stage(control_root)

        name, obj = next(iter(positive_case['objects'].items()))
        phases = obj['phases']
        if len(phases) != 2 or phases[0]['joint_id'] == phases[1]['joint_id']:
            raise ValueError('paired control requires exactly two different joint phases')
        positive_commands = positive_spec['objects'][name]['mechanism']['commands']
        control_commands = control_spec['objects'][name]['mechanism']['commands']
        if not isinstance(positive_commands, list) or not isinstance(control_commands, list):
            raise ValueError('paired mechanism commands must be lists')
        phase = phases[1]
        matches = [index for index, command in enumerate(positive_commands)
                   if isinstance(command, dict) and command.get('joint_id') == phase['joint_id']
                   and command.get('trigger') == {'type': 'at_step', 'physics_step': phase['command_step']}]
        if len(matches) != 1:
            raise ValueError('second phase must have one unique drive command')
        omitted = matches[0]
        expected_control = copy.deepcopy(positive_commands)
        expected_control.pop(omitted)
        checks['control_only_second_drive_removed'] = control_commands == expected_control
        normalized_positive = copy.deepcopy(positive_spec)
        normalized_positive['objects'][name]['mechanism']['commands'] = expected_control
        checks['same_scene'] = _scene(normalized_positive, positive_root) == _scene(control_spec, control_root)
        checks['control_command_events_match'] = _control_events(positive, control, name, omitted, expected_control)

        control_checks = control_report.get('checks', {})
        integrity = control_report.get('input_integrity', {})
        evidence = control_report.get('evidence_integrity', {})
        allowed_failures = {'all_objects_passed', 'commands_pinned_to_spec'}
        checks['control_input_and_evidence_valid'] = (
            control_report.get('passed') is False and control_report.get('case_pinned_to_run') is True
            and isinstance(control_checks, dict) and _CONTROL_REQUIRED <= set(control_checks)
            and all(value is True for key, value in control_checks.items() if key not in allowed_failures)
            and all(control_checks.get(key) is False for key in allowed_failures)
            and integrity.get('passed') is True and integrity.get('checks', {}).get('worker_code_snapshot') is True
            and evidence.get('passed') is True and evidence.get('partial') is False
            and positive_report.get('input_integrity', {}).get('checks', {}).get('worker_code_snapshot') is True)
        observed = control_report.get('objects', {}).get(name, {})
        object_checks = observed.get('checks', {})
        reports = observed.get('phases', [])
        if (not isinstance(object_checks, dict) or object_checks.get('initial_coordinates_match') is not True
                or object_checks.get('full_actual_measurements') is not True
                or object_checks.get('command_events_match') is not False
                or object_checks.get('all_phases_passed') is not False
                or not isinstance(reports, list) or len(reports) != 2):
            raise ValueError('control lacks complete independently measured two-phase evidence')
        checks['control_first_phase_passed'] = reports[0].get('passed') is True
        second_checks = reports[1].get('checks', {})
        checks['control_other_joint_held'] = (second_checks.get('other_target_held') is True
            and second_checks.get('other_drift_within_limit') is True)
        frames = [control['initial_observation'], *control['samples']]
        path = obj['joints'][phase['joint_id']]['joint_path']
        values = [frame['native_joint_positions'][path]
                  for frame in frames[phase['command_step']:phase['by_step'] + 1]]
        if not values or not all(single._number(value) for value in values):
            raise ValueError('control second-phase native positions are missing or nonfinite')
        deviation = max(abs(value - values[0]) for value in values)
        travel = max(values) - min(values)
        target_error = abs(values[-1] - phase['target_position'])
        checks['control_target_stationary'] = deviation <= phase['target_tolerance']
        checks['control_target_not_reached'] = (target_error > phase['target_tolerance']
            and second_checks.get('target_reached') is False)
        checks['control_travel_insufficient'] = (travel < phase['min_travel']
            and second_checks.get('measured_travel') is False)
        result['negative_control'] = {'joint_id': phase['joint_id'], 'joint_path': path,
            'command_step': phase['command_step'], 'by_step': phase['by_step'],
            'start_position': values[0], 'final_position': values[-1], 'max_start_deviation': deviation,
            'observed_travel': travel, 'target_error': target_error,
            'stationary_tolerance': phase['target_tolerance'], 'minimum_travel': phase['min_travel']}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as error:
        result['errors'].append(str(error))
    result['passed'] = all(value is True for value in checks.values())
    return result
