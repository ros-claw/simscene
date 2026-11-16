"""Two-joint checker consumes measured, path-keyed data, never command echoes."""
import copy
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

BASE = '/World/cabinet/Asset/Native/Links/base'
FIRST = '/World/cabinet/Asset/Native/Links/first'
SECOND = '/World/cabinet/Asset/Native/Links/second'
JOINT_A = '/World/cabinet/Asset/Native/Joints/slide'
JOINT_B = '/World/cabinet/Asset/Native/Joints/hinge'
SOURCE_REF = {'source_id': 'usdcraft', 'asset_id': 'fixture', 'revision': 'a' * 40, 'variant_id': None}


def binding_joint(path, child, kind, axis, limits, unit):
    return {'joint_path': path, 'parent_body': BASE, 'child_body': child,
            'type': kind, 'axis': axis, 'position_unit': unit, 'limits': limits,
            'local_pos0_m': [0., 0., 0.], 'local_pos1_m': [0., 0., 0.],
            'local_rot0_wxyz': [1., 0., 0., 0.], 'local_rot1_wxyz': [1., 0., 0., 0.],
            'passive': True, 'drive': None}


def fixture(*, first=None, second=None):
    first = first or [0., .1, .2, .3, .3, .3, .3, .3, .3]
    second = second or [0., 0., 0., 0., 0., .1, .2, .3, .3]
    joints = {
        'slide': binding_joint(JOINT_A, FIRST, 'prismatic', 'X', [-1., 1.], 'm'),
        'hinge': binding_joint(JOINT_B, SECOND, 'revolute', 'Z', [-1., 1.], 'rad'),
    }
    binding = {'profile_id': 'articulated_prop_v2', 'root_body': BASE,
               'motion_bodies': [BASE, FIRST, SECOND], 'joints': joints}
    expectations = {}
    for name, joint in joints.items():
        expectations[name] = {key: copy.deepcopy(joint[key]) for key in
                              ('joint_path', 'parent_body', 'child_body', 'type', 'axis', 'limits', 'position_unit')}
        expectations[name].update(initial_position=0., initial_tolerance=.001, coordinate_tolerance=.00001,
                                  velocity_tolerance=.00001, anchor_tolerance_m=.00001, angular_tolerance_rad=.01)
    phases = [
        {'joint_id': 'slide', 'command_step': 0, 'by_step': 3, 'target_position': .3, 'target_tolerance': .005,
         'min_travel': .2, 'other_target_position': 0., 'other_target_tolerance': .01, 'max_other_drift': .005,
         'stiffness': 30., 'damping': 4., 'max_effort': 50., 'hold_command': None},
        {'joint_id': 'hinge', 'command_step': 4, 'by_step': 7, 'target_position': .3, 'target_tolerance': .005,
         'min_travel': .2, 'other_target_position': .3, 'other_target_tolerance': .02, 'max_other_drift': .005,
         'stiffness': 30., 'damping': 4., 'max_effort': 50., 'hold_command': None},
    ]
    case = {'schema': 'simscene.articulated_asset_two_joint.v1', 'schema_version': 1, 'mode': 'driven',
            'physics_dt_s': .1, 'objects': {'cabinet': {'prepared_manifest_sha256': 'b' * 64,
            'source_ref': copy.deepcopy(SOURCE_REF), 'joints': expectations, 'phases': phases}}}
    events = [
        {'command_index': 0, 'joint_id': 'slide', 'joint_path': JOINT_A, 'physics_step': 0,
         'trigger': {'type': 'at_step', 'physics_step': 0}, 'target_position': .3, 'position_unit': 'm',
         'cause': 'declared_at_step_schedule', 'drive_readback': {'type': 'force', 'target_position': .3,
         'target_velocity': 0., 'stiffness': 30., 'damping': 4., 'max_force': 50.,
         'instance': 'linear', 'position_unit': 'm', 'scope': 'loaded_USD_drive_attributes'}},
        {'command_index': 1, 'joint_id': 'hinge', 'joint_path': JOINT_B, 'physics_step': 4,
         'trigger': {'type': 'at_step', 'physics_step': 4}, 'target_position': .3, 'position_unit': 'rad',
         'cause': 'declared_at_step_schedule', 'drive_readback': {'type': 'force', 'target_position': math.degrees(.3),
         'target_velocity': 0., 'stiffness': 30. * math.pi / 180., 'damping': 4. * math.pi / 180., 'max_force': 50.,
         'instance': 'angular', 'position_unit': 'degree', 'scope': 'loaded_USD_drive_attributes'}},
    ]
    frames = []
    for step, (a, b) in enumerate(zip(first, second)):
        va = (a - first[step - 1]) / .1 if step else 0.
        vb = (b - second[step - 1]) / .1 if step else 0.
        positions = {BASE: [0., 0., 0.], FIRST: [a, 0., 0.], SECOND: [0., 0., 0.]}
        orientations = {BASE: [1., 0., 0., 0.], FIRST: [1., 0., 0., 0.],
                        SECOND: [math.cos(b / 2), 0., 0., math.sin(b / 2)]}
        linear = {BASE: [0., 0., 0.], FIRST: [va, 0., 0.],
                  SECOND: [-vb * math.sin(b), vb * math.cos(b), 0.]}
        angular = {BASE: [0., 0., 0.], FIRST: [0., 0., 0.], SECOND: [0., 0., vb]}
        measurements = {}
        for name, value, velocity in (('slide', a, va), ('hinge', b, vb)):
            joint = joints[name]
            measurements[name] = {'position': value, 'velocity': velocity if step else None,
                'position_unit': joint['position_unit'], 'velocity_unit': joint['position_unit'] + '/s',
                'physics_step': step, 'anchor_error_m': 0., 'locked_rotation_error_rad': 0.,
                'parent_body': BASE, 'child_body': joint['child_body'],
                'joint_path': joint['joint_path'], 'measurement_source': 'same_sample_PhysX_body_poses_joint_frame_reconstruction',
                'native_position': value, 'native_velocity': velocity,
                'native_measurement_source': 'PhysX_articulation_tensor_DOF_readback_SI'}
        frames.append({'physics_steps': step, 'simulation_time_s': step * .1,
            'absolute_physics_step': 10 + step, 'absolute_simulation_time_s': 1. + step * .1,
            'positions': positions, 'orientations_wxyz': orientations, 'linear_velocities_m_s': linear,
            'angular_velocities_rad_s': angular, 'native_joint_positions': {JOINT_A: a, JOINT_B: b},
            'native_joint_velocities': {JOINT_A: va, JOINT_B: vb},
            'native_joint_measurement_source': 'PhysX_articulation_tensor_DOF_readback_SI',
            'mechanisms': {'cabinet': {'physics_step': step, 'joints': measurements,
                # Step 4 is observed before the step-4 command runs; that
                # command first appears after stepping into frame 5.
                'command_events': copy.deepcopy(events[:1 if step <= 4 else 2])}}})
    props = {path: {'center_of_mass_local_m': com, 'observed_at_physics_step': 0,
                    'source': 'PhysX native articulation/rigid tensor cooked mass properties'}
             for path, com in ((BASE, [0., 1., 0.]), (FIRST, [0., 2., 0.]), (SECOND, [1., 0., 0.]))}
    run = {'initial_observation': frames[0], 'samples': frames[1:], 'body_bindings': {'cabinet': binding},
           'actual_physics_steps': 8, 'requested_physics_steps': 8, 'observation_interval_steps': 1,
           'simulation_time_s': .8, 'run_zero_absolute_physics_step': 10, 'run_zero_absolute_simulation_time_s': 1.,
           'partial': False, 'samples_truncated': False, 'followers': {}, 'task_status': 'unverified',
           'physics_settings': {'before_warmup': {'authored_time_steps_per_second': 10., 'requested_device': 'cpu',
                                                   'enable_gpu_dynamics': False, 'request_matches_observation': True},
                                'after_run': {'authored_time_steps_per_second': 10., 'requested_device': 'cpu',
                                              'enable_gpu_dynamics': False, 'request_matches_observation': True}},
           'mechanism_configuration': {'mass_properties_by_prim_path': props}}
    return run, case


def frozen_run(directory):
    """Build real input/evidence locks around a small local prepared closure."""
    from simscene.cache import _sha256
    from simscene.evidence_integrity import seal
    root = Path(directory)
    package = root / 'prepared'
    (package / 'source').mkdir(parents=True)
    main = package / 'main.usda'
    main.write_text('#usda 1.0\n')
    acquired = package / 'source' / 'acquired.json'
    acquired.write_text(json.dumps({'source_ref': SOURCE_REF}))
    run, case = fixture()
    binding = run['body_bindings']['cabinet']
    body_map = {name: {'relative_prim_path': 'Native/Links/' + name, 'role': 'rigid',
                       'visual_relative_prim_paths': [], 'collider_relative_prim_paths': []}
                for name in ('base', 'first', 'second')}
    joint_map = {}
    for name, child in (('slide', 'first'), ('hinge', 'second')):
        joint = copy.deepcopy(binding['joints'][name])
        joint.pop('joint_path'); joint.pop('parent_body'); joint.pop('child_body')
        joint.update(relative_prim_path='Native/Joints/' + name, parent_body_id='base', child_body_id=child)
        joint_map[name] = joint
        binding['joints'][name].update(relative_prim_path=joint['relative_prim_path'],
                                      parent_body_id='base', child_body_id=child)
    report = {'schema': 'simscene.articulation_inspection.v2', 'schema_version': 2,
              'body_map': body_map, 'joint_map': joint_map, 'root_body_id': 'base'}
    manifest = {'schema': 'simscene.prepared_asset.v1', 'schema_version': 1,
                'profile_id': 'articulated_prop_v2', 'main': 'main.usda', 'default_prim': '/Asset',
                'body_map': body_map, 'joint_map': joint_map, 'articulation_report': report,
                'parameters': {'source_physics_policy': 'preserve_valid'}, 'source_ref': SOURCE_REF,
                'files': [{'path': path.relative_to(package).as_posix(), 'size': path.stat().st_size,
                           'sha256': _sha256(path)} for path in (main, acquired)]}
    manifest_path = package / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    manifest_hash = _sha256(manifest_path)
    case['objects']['cabinet']['prepared_manifest_sha256'] = manifest_hash
    commands = [{'joint_id': phase['joint_id'], 'trigger': {'type': 'at_step', 'physics_step': phase['command_step']},
                 'target_position': phase['target_position'], 'position_unit': case['objects']['cabinet']['joints'][phase['joint_id']]['position_unit'],
                 'stiffness': phase['stiffness'], 'damping': phase['damping'], 'max_effort': phase['max_effort']}
                for phase in case['objects']['cabinet']['phases']]
    spec = {'objects': {'cabinet': {'kind': 'asset', 'dynamic': True, 'asset_path': str(main),
              'asset_binding': {'manifest_path': str(manifest_path), 'manifest_sha256': manifest_hash},
              'mechanism': {'commands': commands}}}}
    asset_lock = {'cabinet': {'kind': 'external', 'path': str(main), 'files': [
        {'path': str(path), 'size': path.stat().st_size, 'sha256': _sha256(path)}
        for path in (main, acquired, manifest_path)]}}
    for name, value in (('spec.json', spec), ('asset-lock.json', asset_lock), ('runtime-lock.json', {}),
                        ('result.json', run), ('acceptance-case.json', case)):
        (root / name).write_text(json.dumps(value))
    (root / 'scene.usda').write_text('#usda 1.0\n')
    launcher = str(Path(sys.executable).resolve())
    lock = {'spec_sha256': _sha256(root / 'spec.json'), 'stage_sha256': _sha256(root / 'scene.usda'),
            'asset_lock_sha256': _sha256(root / 'asset-lock.json'), 'runtime_lock_sha256': _sha256(root / 'runtime-lock.json'),
            'acceptance_case_file': 'acceptance-case.json', 'acceptance_case_sha256': _sha256(root / 'acceptance-case.json'),
            'runtime_python': launcher, 'runtime_python_sha256': _sha256(Path(launcher)), 'body_bindings': run['body_bindings'],
            'physics_device': 'cpu', 'physics_dt_s': .1, 'requested_physics_steps': 8}
    (root / 'run-lock.json').write_text(json.dumps(lock))
    seal(root)
    return root, run, case


class TwoJointAcceptanceTests(unittest.TestCase):
    def checker(self):
        spec = importlib.util.find_spec('simscene.verification.articulated_asset_two_joint')
        self.assertIsNotNone(spec, 'two-joint acceptance checker is not implemented')
        from simscene.verification import articulated_asset_two_joint
        return articulated_asset_two_joint

    def test_two_phases_require_observed_travel_and_each_other_axis_holds(self):
        run, case = fixture()
        report = self.checker().evaluate(run, case)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['negative_control']['status'], 'not_evaluated')
        phases = report['objects']['cabinet']['phases']
        self.assertEqual(len(phases), 2)
        self.assertAlmostEqual(phases[0]['observed_travel'], .3)
        self.assertAlmostEqual(phases[1]['observed_travel'], .3)
        self.assertAlmostEqual(phases[0]['max_other_drift'], 0.)
        self.assertAlmostEqual(phases[1]['max_other_drift'], 0.)

    def test_explicit_same_step_hold_command_is_frozen_and_does_not_supply_motion(self):
        run, case = fixture()
        phases = case['objects']['cabinet']['phases']
        phases[0]['hold_command'] = {'stiffness': 15., 'damping': 2., 'max_effort': 40.}
        phases[1]['hold_command'] = None
        for frame in [run['initial_observation'], *run['samples']]:
            events = frame['mechanisms']['cabinet']['command_events']
            hold = {'command_index': 1, 'joint_id': 'hinge', 'joint_path': JOINT_B, 'physics_step': 0,
                    'trigger': {'type': 'at_step', 'physics_step': 0}, 'target_position': 0., 'position_unit': 'rad',
                    'cause': 'declared_at_step_schedule', 'drive_readback': {'type': 'force', 'target_position': 0.,
                    'target_velocity': 0., 'stiffness': 15. * math.pi / 180., 'damping': 2. * math.pi / 180.,
                    'max_force': 40., 'instance': 'angular', 'position_unit': 'degree', 'scope': 'loaded_USD_drive_attributes'}}
            if len(events) == 2:
                events[1]['command_index'] = 2
            events.insert(1, hold)
        self.assertTrue(self.checker().evaluate(run, case)['passed'])
        wrong = copy.deepcopy(run)
        for frame in [wrong['initial_observation'], *wrong['samples']]:
            frame['mechanisms']['cabinet']['command_events'][1]['joint_path'] = JOINT_A
        self.assertFalse(self.checker().evaluate(wrong, case)['passed'])
        wrong = copy.deepcopy(run)
        for frame in [wrong['initial_observation'], *wrong['samples']]:
            frame['mechanisms']['cabinet']['command_events'][1]['drive_readback']['stiffness'] = 0.
        self.assertFalse(self.checker().evaluate(wrong, case)['passed'])

    def test_missing_native_q_or_velocity_and_missing_com_fail_closed(self):
        for mutation in ('q', 'velocity', 'source', 'com'):
            with self.subTest(mutation=mutation):
                run, case = fixture()
                frame = run['samples'][1]
                if mutation == 'q': del frame['native_joint_positions'][JOINT_A]
                elif mutation == 'velocity': del frame['native_joint_velocities'][JOINT_B]
                elif mutation == 'source': frame['native_joint_measurement_source'] = 'command_echo'
                else: del run['mechanism_configuration']['mass_properties_by_prim_path'][FIRST]
                self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_swapped_native_paths_and_wrong_command_path_fail(self):
        run, case = fixture()
        frame = run['samples'][1]
        q = frame['native_joint_positions']
        q[JOINT_A], q[JOINT_B] = q[JOINT_B], q[JOINT_A]
        self.assertFalse(self.checker().evaluate(run, case)['passed'])
        run, case = fixture()
        for frame in [run['initial_observation'], *run['samples']]:
            frame['mechanisms']['cabinet']['command_events'][0]['joint_path'] = JOINT_B
        self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_unreached_driven_or_held_target_and_excess_drift_fail_independently(self):
        run, case = fixture(second=[0., 0., 0., 0., 0., .04, .08, .12, .12])
        report = self.checker().evaluate(run, case)
        self.assertFalse(report['passed'])
        self.assertFalse(report['objects']['cabinet']['phases'][1]['checks']['target_reached'])
        run, case = fixture()
        case['objects']['cabinet']['phases'][0]['other_target_position'] = .1
        self.assertFalse(self.checker().evaluate(run, case)['objects']['cabinet']['phases'][0]['checks']['other_target_held'])
        run, case = fixture(first=[0., .1, .2, .3, .3, .306, .312, .318, .318])
        report = self.checker().evaluate(run, case)
        self.assertFalse(report['passed'])
        self.assertTrue(report['objects']['cabinet']['phases'][1]['checks']['other_target_held'])
        self.assertFalse(report['objects']['cabinet']['phases'][1]['checks']['other_drift_within_limit'])

    def test_synchronous_motion_cannot_be_accepted_by_large_holding_thresholds(self):
        positions = [0., .1, .2, .3, .3, .4, .5, .6, .6]
        run, case = fixture(first=positions, second=positions)
        phases = case['objects']['cabinet']['phases']
        phases[1]['target_position'] = .6
        for phase in phases:
            phase['other_target_tolerance'] = .5
            phase['max_other_drift'] = .5
        for frame in run['samples']:
            events = frame['mechanisms']['cabinet']['command_events']
            if len(events) == 2:
                events[1]['target_position'] = .6
                events[1]['drive_readback']['target_position'] = math.degrees(.6)
        with self.assertRaisesRegex(ValueError, 'relative to'):
            self.checker().evaluate(run, case)

    def test_weak_target_or_hold_tolerances_cannot_swallow_required_motion(self):
        for key in ('target_tolerance', 'other_target_tolerance', 'max_other_drift'):
            with self.subTest(tolerance=key):
                run, case = fixture()
                case['objects']['cabinet']['phases'][0][key] = .04
                with self.assertRaisesRegex(ValueError, 'relative to'):
                    self.checker().validate_case(case)

    def test_large_measurement_tolerances_cannot_hide_bad_native_or_frame_data(self):
        for mutation in ('coordinate', 'velocity', 'anchor', 'initial', 'angular'):
            with self.subTest(mutation=mutation):
                run, case = fixture()
                expected = case['objects']['cabinet']['joints']['slide' if mutation != 'angular' else 'hinge']
                frame = run['samples'][-1]
                record = frame['mechanisms']['cabinet']['joints']['slide']
                if mutation == 'coordinate':
                    expected['coordinate_tolerance'] = 1000.
                    frame['native_joint_positions'][JOINT_A] = 10.
                    record['native_position'] = 10.
                elif mutation == 'velocity':
                    expected['velocity_tolerance'] = 1000.
                    frame['native_joint_velocities'][JOINT_A] = 500.
                    record['native_velocity'] = 500.
                elif mutation == 'anchor':
                    expected['anchor_tolerance_m'] = 1000.
                    frame['positions'][FIRST][1] = 1.
                    record['anchor_error_m'] = 1.
                elif mutation == 'initial':
                    expected['initial_tolerance'] = 1000.
                else:
                    expected['angular_tolerance_rad'] = .05
                with self.assertRaises(ValueError):
                    self.checker().evaluate(run, case)

    def test_missing_step_and_command_echo_without_motion_are_rejected(self):
        run, case = fixture()
        del run['samples'][2]
        self.assertFalse(self.checker().evaluate(run, case)['passed'])
        run, case = fixture(first=[0.] * 9, second=[0.] * 9)
        report = self.checker().evaluate(run, case)
        self.assertFalse(report['passed'])
        self.assertFalse(report['objects']['cabinet']['phases'][0]['checks']['target_reached'])

    def test_default_device_allows_unknown_matching_flag_but_dt_remains_verified(self):
        run, case = fixture()
        for settings in run['physics_settings'].values():
            settings.update(requested_device='default', enable_gpu_dynamics=None, request_matches_observation=None)
        self.assertTrue(self.checker().evaluate(run, case)['passed'])
        run['physics_settings']['after_run']['authored_time_steps_per_second'] = 20.
        self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_explicit_device_case_requires_matching_observed_physics_configuration(self):
        run, case = fixture()
        case['physics_device'] = 'cpu'
        self.assertTrue(self.checker().evaluate(run, case)['passed'])
        run['physics_settings']['after_run']['enable_gpu_dynamics'] = True
        self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_incomplete_status_and_boolean_step_values_are_rejected(self):
        for mutation in ('missing_status', 'missing_followers', 'incomplete_marker', 'boolean_event_step', 'boolean_record_step'):
            with self.subTest(mutation=mutation):
                run, case = fixture()
                if mutation == 'missing_status': del run['task_status']
                elif mutation == 'missing_followers': del run['followers']
                elif mutation == 'incomplete_marker': run['evidence_incomplete'] = 'yes'
                elif mutation == 'boolean_record_step':
                    run['initial_observation']['mechanisms']['cabinet']['joints']['slide']['physics_step'] = False
                else:
                    for frame in [run['initial_observation'], *run['samples']]:
                        event = frame['mechanisms']['cabinet']['command_events'][0]
                        event['physics_step'] = False
                        event['trigger']['physics_step'] = False
                self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_same_sample_velocity_uses_rotated_center_of_mass_and_relative_frame(self):
        run, case = fixture()
        frame = run['samples'][0]  # slide=0.1, native slide velocity=1 m/s
        frame['angular_velocities_rad_s'] = {BASE: [0., 0., 1.], FIRST: [0., 0., 1.], SECOND: [0., 0., 1.]}
        frame['linear_velocities_m_s'] = {BASE: [-1., 0., 0.], FIRST: [-1., .1, 0.], SECOND: [0., 1., 0.]}
        self.assertTrue(self.checker().evaluate(run, case)['passed'])
        frame['linear_velocities_m_s'][FIRST][0] += .1
        self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_slider_rotation_and_hinge_swing_cannot_be_hidden_by_valid_scalar_position(self):
        for joint, path in (('slide', FIRST), ('hinge', SECOND)):
            with self.subTest(joint=joint):
                run, case = fixture()
                frame = run['initial_observation']
                # A 90 degree relative rotation around X is forbidden for a
                # slider and is perpendicular swing for this Z hinge.
                frame['orientations_wxyz'][path] = [math.sqrt(.5), math.sqrt(.5), 0., 0.]
                frame['mechanisms']['cabinet']['joints'][joint]['locked_rotation_error_rad'] = math.pi / 2
                self.assertFalse(self.checker().evaluate(run, case)['passed'])

    def test_joint_case_requires_two_distinct_paths_and_unambiguous_disjoint_phases(self):
        run, case = fixture()
        second = case['objects']['cabinet']['joints']['hinge']
        second['joint_path'] = JOINT_A
        with self.assertRaises(ValueError): self.checker().validate_case(case)
        run, case = fixture()
        case['objects']['cabinet']['phases'][1]['joint_id'] = 'slide'
        with self.assertRaises(ValueError): self.checker().validate_case(case)
        run, case = fixture()
        case['objects']['cabinet']['phases'][1]['command_step'] = 2
        with self.assertRaises(ValueError): self.checker().validate_case(case)
        run, case = fixture()
        case['objects']['cabinet']['joints']['hinge']['child_body'] = '/World/other/Asset/Native/Links/second'
        with self.assertRaises(ValueError): self.checker().validate_case(case)

    def test_verify_run_pins_case_manifest_input_and_evidence_contents(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            self.assertTrue(checker.verify_run(root)['passed'])
            result = root / 'result.json'
            result.write_text(result.read_text() + ' ')
            report = checker.verify_run(root)
            self.assertFalse(report['passed'])
            self.assertFalse(report['evidence_integrity']['passed'])
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            spec = root / 'spec.json'
            spec.write_text(spec.read_text() + ' ')
            report = checker.verify_run(root)
            self.assertFalse(report['passed'])
            self.assertFalse(report['input_integrity']['passed'])
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            manifest = root / 'prepared' / 'manifest.json'
            manifest.write_text(manifest.read_text() + ' ')
            report = checker.verify_run(root)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['prepared_selection_pinned'])
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            case = root / 'acceptance-case.json'
            case.write_text(case.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'frozen case'):
                checker.verify_run(root)

    def test_verify_run_rejects_case_commands_not_present_in_the_frozen_spec(self):
        from simscene.cache import _sha256
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            path = root / 'spec.json'
            spec = json.loads(path.read_text())
            spec['objects']['cabinet']['mechanism']['commands'][0]['target_position'] = .2
            path.write_text(json.dumps(spec))
            lock_path = root / 'run-lock.json'
            lock = json.loads(lock_path.read_text())
            lock['spec_sha256'] = _sha256(path)
            lock_path.write_text(json.dumps(lock))
            report = self.checker().verify_run(root)
            self.assertTrue(report['input_integrity']['passed'])
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['commands_pinned_to_spec'])

    def test_verify_run_rejects_run_lock_device_or_timestep_mismatch(self):
        for field, value in (('physics_device', 'gpu'), ('physics_dt_s', .2), ('requested_physics_steps', 9)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root, _, _ = frozen_run(directory)
                lock_path = root / 'run-lock.json'
                lock = json.loads(lock_path.read_text())
                lock[field] = value
                lock_path.write_text(json.dumps(lock))
                report = self.checker().verify_run(root)
                self.assertTrue(report['input_integrity']['passed'])
                self.assertFalse(report['passed'])

    def test_verify_run_rejects_binding_not_in_the_selected_manifest_even_when_all_hashes_match(self):
        from simscene.cache import _sha256
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = frozen_run(directory)
            manifest_path = root / 'prepared' / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['joint_map']['slide']['local_pos0_m'] = [.1, 0., 0.]
            manifest['articulation_report']['joint_map']['slide']['local_pos0_m'] = [.1, 0., 0.]
            manifest_path.write_text(json.dumps(manifest))
            digest = _sha256(manifest_path)
            case_path = root / 'acceptance-case.json'
            case = json.loads(case_path.read_text())
            case['objects']['cabinet']['prepared_manifest_sha256'] = digest
            case_path.write_text(json.dumps(case))
            spec_path = root / 'spec.json'
            spec = json.loads(spec_path.read_text())
            spec['objects']['cabinet']['asset_binding']['manifest_sha256'] = digest
            spec_path.write_text(json.dumps(spec))
            assets_path = root / 'asset-lock.json'
            assets = json.loads(assets_path.read_text())
            entry = next(item for item in assets['cabinet']['files'] if item['path'] == str(manifest_path))
            entry.update(size=manifest_path.stat().st_size, sha256=digest)
            assets_path.write_text(json.dumps(assets))
            lock_path = root / 'run-lock.json'
            lock = json.loads(lock_path.read_text())
            lock.update(spec_sha256=_sha256(spec_path), asset_lock_sha256=_sha256(assets_path),
                        acceptance_case_sha256=_sha256(case_path))
            lock_path.write_text(json.dumps(lock))
            report = self.checker().verify_run(root)
            self.assertTrue(report['input_integrity']['passed'])
            self.assertTrue(report['evidence_integrity']['passed'])
            self.assertFalse(report['checks']['prepared_selection_pinned'])
            self.assertFalse(report['passed'])


if __name__ == '__main__':
    unittest.main()
