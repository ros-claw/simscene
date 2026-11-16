"""Paired acceptance requires the isolated missing second command, not any failure."""
import copy
import json
import math

import pytest

from simscene.cache import _sha256
from simscene.evidence_integrity import seal
from simscene.verification.articulated_asset_two_joint import verify_run
from test_articulated_asset_two_joint import JOINT_B, fixture, frozen_run


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf8')


def update_run(root, *, spec=None, result=None, case=None):
    """Reseal actual fixture inputs and results, as a new frozen run would."""
    lock_path = root / 'run-lock.json'
    lock = json.loads(lock_path.read_text())
    if spec is not None:
        write_json(root / 'spec.json', spec)
        lock['spec_sha256'] = _sha256(root / 'spec.json')
    if case is not None:
        write_json(root / 'acceptance-case.json', case)
        lock['acceptance_case_sha256'] = _sha256(root / 'acceptance-case.json')
    if result is not None:
        write_json(root / 'result.json', result)
        lock['body_bindings'] = result['body_bindings']
    write_json(lock_path, lock)
    seal(root)


def paired_fixture(tmp_path):
    positive = tmp_path / 'positive'
    control = tmp_path / 'control'
    positive.mkdir(); control.mkdir()
    _, positive_run, case = frozen_run(positive)
    _, control_run, control_case = frozen_run(control)
    assert case == control_case

    # Keep an explicit first-phase hold on the second axis in both trials.
    hold = {'stiffness': 15., 'damping': 2., 'max_effort': 40.}
    case['objects']['cabinet']['phases'][0]['hold_command'] = hold
    hold_command = {'joint_id': 'hinge', 'trigger': {'type': 'at_step', 'physics_step': 0},
                    'target_position': 0., 'position_unit': 'rad', **hold}
    hold_event = {'command_index': 1, 'joint_id': 'hinge', 'joint_path': JOINT_B,
                  'physics_step': 0, 'trigger': {'type': 'at_step', 'physics_step': 0},
                  'target_position': 0., 'position_unit': 'rad', 'cause': 'declared_at_step_schedule',
                  'drive_readback': {'type': 'force', 'target_position': 0., 'target_velocity': 0.,
                    'stiffness': 15. * math.pi / 180., 'damping': 2. * math.pi / 180.,
                    'max_force': 40., 'instance': 'angular', 'position_unit': 'degree',
                    'scope': 'loaded_USD_drive_attributes'}}
    stationary, _ = fixture(second=[0.] * 9)
    control_run['initial_observation'] = stationary['initial_observation']
    control_run['samples'] = stationary['samples']
    for run, is_control in ((positive_run, False), (control_run, True)):
        run['seed'] = 42
        for frame in [run['initial_observation'], *run['samples']]:
            events = frame['mechanisms']['cabinet']['command_events']
            if is_control:
                del events[1:]
            elif len(events) == 2:
                events[1]['command_index'] = 2
            events.insert(1, copy.deepcopy(hold_event))

    for root, run, is_control in ((positive, positive_run, False), (control, control_run, True)):
        spec = json.loads((root / 'spec.json').read_text())
        spec.update(scene_id='control' if is_control else 'positive', revision=4 if is_control else 1,
                    requests={'different-id': 1} if is_control else {})
        commands = spec['objects']['cabinet']['mechanism']['commands']
        commands.insert(1, copy.deepcopy(hold_command))
        if is_control:
            commands.pop(2)
        lock = json.loads((root / 'run-lock.json').read_text())
        worker_root = root / 'runtime' / 'simscene'
        hashes = {}
        for name in ('worker/isaac_run.py', 'worker/initial_state.py', 'worker/mechanism.py',
                     'worker/mechanism_v2.py'):
            path = worker_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture worker: ' + name, encoding='utf8')
            hashes[name] = _sha256(path)
        lock.update(run_id=root.name, worker_code_sha256=hashes, runtime_version='fixture-version', seed=42)
        write_json(root / 'run-lock.json', lock)
        update_run(root, spec=spec, result=run, case=case)
    assert verify_run(positive)['passed']
    return positive, control


def test_paired_control_passes_with_only_second_drive_removed_and_hold_preserved(tmp_path):
    from simscene.verification.articulated_asset_two_joint_pair import verify_pair
    positive, control = paired_fixture(tmp_path)
    report = verify_pair(positive, control)
    assert report['passed'], report
    assert report['checks']['control_only_second_drive_removed']
    assert report['checks']['control_command_events_match']
    assert report['checks']['control_first_phase_passed']
    assert report['checks']['control_target_stationary']
    assert report['checks']['control_target_not_reached']
    assert report['checks']['control_travel_insufficient']


@pytest.mark.parametrize('mutation', ['same_run', 'scene', 'wrong_command', 'missing_hold_event',
                                     'phase_two_motion', 'unsealed_evidence', 'unlocked_stage', 'case'])
def test_pair_rejects_unmatched_scene_commands_measurements_and_locks(tmp_path, mutation):
    from simscene.verification.articulated_asset_two_joint_pair import verify_pair
    positive, control = paired_fixture(tmp_path)
    if mutation == 'same_run':
        control = positive
    elif mutation == 'scene':
        spec = json.loads((control / 'spec.json').read_text())
        spec['objects']['cabinet']['position'] = [1., 0., 0.]
        update_run(control, spec=spec)
    elif mutation == 'wrong_command':
        spec = json.loads((control / 'spec.json').read_text())
        spec['objects']['cabinet']['mechanism']['commands'].pop(0)
        update_run(control, spec=spec)
    elif mutation == 'missing_hold_event':
        result = json.loads((control / 'result.json').read_text())
        for frame in [result['initial_observation'], *result['samples']]:
            frame['mechanisms']['cabinet']['command_events'].pop(1)
        update_run(control, result=result)
    elif mutation == 'phase_two_motion':
        result = json.loads((control / 'result.json').read_text())
        moving, _ = fixture(second=[0., 0., 0., 0., 0., .03, .03, .03, .03])
        for old, new in zip([result['initial_observation'], *result['samples']],
                            [moving['initial_observation'], *moving['samples']]):
            for key in ('positions', 'orientations_wxyz', 'linear_velocities_m_s', 'angular_velocities_rad_s',
                        'native_joint_positions', 'native_joint_velocities'):
                old[key] = new[key]
            old['mechanisms']['cabinet']['joints'] = new['mechanisms']['cabinet']['joints']
        update_run(control, result=result)
    elif mutation == 'unsealed_evidence':
        path = control / 'result.json'
        path.write_text(path.read_text() + ' ')
    elif mutation == 'unlocked_stage':
        (control / 'scene.usda').write_text('#usda 1.0\n# changed\n')
    else:
        case = json.loads((control / 'acceptance-case.json').read_text())
        case['objects']['cabinet']['joints']['slide']['anchor_tolerance_m'] = .00002
        update_run(control, case=case)
    assert verify_pair(positive, control)['passed'] is False


@pytest.mark.parametrize('key,value', [('seed', 43), ('runtime_version', 'other'),
                                       ('physics_device', 'gpu'), ('requested_physics_steps', 7)])
def test_pair_rejects_different_frozen_runtime_seed_device_or_step_count(tmp_path, key, value):
    from simscene.verification.articulated_asset_two_joint_pair import verify_pair
    positive, control = paired_fixture(tmp_path)
    lock = json.loads((control / 'run-lock.json').read_text())
    lock[key] = value
    write_json(control / 'run-lock.json', lock)
    assert verify_pair(positive, control)['passed'] is False


def test_pair_rejects_different_but_independently_valid_worker_snapshot(tmp_path):
    from simscene.verification.articulated_asset_two_joint_pair import verify_pair
    positive, control = paired_fixture(tmp_path)
    worker = control / 'runtime' / 'simscene' / 'worker' / 'mechanism_v2.py'
    worker.write_text('different worker implementation')
    lock = json.loads((control / 'run-lock.json').read_text())
    lock['worker_code_sha256']['worker/mechanism_v2.py'] = _sha256(worker)
    write_json(control / 'run-lock.json', lock)
    assert verify_pair(positive, control)['passed'] is False


def test_pair_rejects_boolean_result_seed_even_when_it_equals_locked_integer(tmp_path):
    from simscene.verification.articulated_asset_two_joint_pair import verify_pair
    positive, control = paired_fixture(tmp_path)
    for root, actual in ((positive, True), (control, 1)):
        lock = json.loads((root / 'run-lock.json').read_text())
        lock['seed'] = 1
        write_json(root / 'run-lock.json', lock)
        result = json.loads((root / 'result.json').read_text())
        result['seed'] = actual
        update_run(root, result=result)
    assert verify_pair(positive, control)['passed'] is False
