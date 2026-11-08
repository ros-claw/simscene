"""CPU counterexamples for the independent checker; no physics success claim.

Fixtures below are deliberately synthetic telemetry, not Isaac runs.
"""
import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from experiments.mechanism_check import PAIRED_MANIFEST_FIELDS, evaluate, measure_activity, strict_initial_state, validate_case, verify_run


def body(position, kind='box', size=None):
    return {'kind': kind, 'dynamic': True, 'collision': True, 'position': position,
            'orientation_wxyz': [1, 0, 0, 0], 'size': size or [.04]*3, 'mass_kg': .1}


def loaded_configuration(spec):
    result = []
    for name, obj in spec['objects'].items():
        if obj.get('kind') != 'joint':
            continue
        cfg = obj['joint']
        result.append({'path': '/World/'+name, 'type': 'Physics'+cfg['type'].title()+'Joint',
                       'enabled': cfg.get('enabled', True), 'drives': [], 'drive_attributes': [],
                       'body0': ['/World/'+cfg['body0']] if cfg.get('body0') else [],
                       'body1': ['/World/'+cfg['body1']] if cfg.get('body1') else []})
    return {'joints': result, 'body_settings': {}}


def fixture():
    segments = ['segment_'+str(i) for i in range(7)]
    chain = ['rope_joint_'+str(i) for i in range(8)]
    objects = {'weight': body([1, 0, 1]), 'drawer': body([-1, 0, 1]),
               'pulley': body([0, 0, 1], 'cylinder', [1, 1, .04])}
    objects.update({n: body([0, 0, 1], 'capsule', [.01, .01, .12]) for n in segments})
    ordered = ['drawer']+segments+['weight']
    for i, name in enumerate(chain):
        objects[name] = {'kind': 'joint', 'joint': {'type': 'spherical', 'body0': ordered[i], 'body1': ordered[i+1], 'enabled': True}}
    objects['slide'] = {'kind': 'joint', 'joint': {'type': 'prismatic', 'body0': None, 'body1': 'drawer', 'axis': 'X'}}
    objects['axle'] = {'kind': 'joint', 'joint': {'type': 'revolute', 'body0': None, 'body1': 'pulley', 'axis': 'Z'}}
    case = {'schema': 'simscene.mechanism.v1', 'mechanism': 'rope_drawer',
            'rope_model': 'segmented_over_free_pulley', 'trigger_id': 'weight', 'release_step': 0,
            'roles': {'weight': 'weight', 'drawer': 'drawer', 'pulley': 'pulley'},
            'joints': {'drawer': 'slide', 'pulley': 'axle', 'drawer_end': chain[0]},
            'drawer_axis_world': [1, 0, 0],
            'rope': {'segment_ids': segments, 'joint_ids': chain, 'free_spans': [[0, 3], [5, 7]],
                     'wrap_span': [3, 5], 'pulley_radius_m': .5, 'axle_local_axis': 'Z',
                     'minimum_wrap_degrees': 85, 'radial_tolerance_m': .01, 'axial_tolerance_m': .01},
            'thresholds': {'slack_min_excess_m': .03, 'taut_max_excess_m': .005,
                           'slack_drawer_max_m': .005, 'drawer_min_travel_m': .08,
                           'weight_min_drop_m': .2, 'weight_slack_min_drop_m': .03,
                           'pulley_min_rotation_degrees': 10, 'max_anchor_error_m': .005,
                           'max_off_axis_m': .003, 'slack_min_steps': 5, 'taut_hold_steps': 3}}
    spec = {'schema_version': '0.1', 'scene_id': 'synthetic', 'revision': 1, 'requests': {},
            'observation': {'sample_interval_steps': 1}, 'objects': objects}
    samples = []
    for step in range(1, 37):
        shift = min(.12, max(0, (step-14)*.02))
        positions = {'/World/'+n: copy.deepcopy(o['position']) for n, o in objects.items() if o.get('dynamic')}
        positions['/World/drawer'][0] += shift
        positions['/World/weight'][2] -= (step-1)*.01
        c = math.sqrt(.125)
        nodes = [[-1+shift, 0, 1], [-.9, .3, 1], [-.6, .1, 1], [-c, c, 1], [0, .5, 1], [c, c, 1], [.65, .18, 1], [1, 0, 1]]
        if step >= 11:
            for first, last in ((0, 3), (5, 7)):
                a, b = nodes[first][:], nodes[last][:]
                for i in range(first+1, last):
                    fraction = (i-first)/(last-first)
                    nodes[i] = [x+(y-x)*fraction for x, y in zip(a, b)]
        joints = {}
        for i, name in enumerate(chain):
            joints[name] = {'type': 'spherical', 'enabled': True, 'anchor_error_m': 0,
                            'anchor0_world_m': nodes[i], 'anchor1_world_m': nodes[i], 'drive_present': False}
        for name, kind, coordinate, value in [('slide', 'prismatic', 'position_m', shift), ('axle', 'revolute', 'angle_degrees', max(0, step-10)*2)]:
            joints[name] = {'type': kind, 'enabled': True, 'anchor_error_m': 0, 'anchor0_world_m': [0, 0, 1],
                            'anchor1_world_m': [0, 0, 1], 'drive_present': False, coordinate: value}
        samples.append({'physics_steps': step, 'simulation_time_s': step/60, 'positions': positions,
                        'orientations_wxyz': {p: [1, 0, 0, 0] for p in positions}, 'joints': joints})
    run = {'requested_physics_steps': 36, 'actual_physics_steps': 36, 'simulation_time_s': .6,
           'observation_interval_steps': 1, 'samples': samples, 'spawn_events': [], 'followers': {},
           'mechanism_configuration': loaded_configuration(spec), 'initial_joint_states': copy.deepcopy(samples[0]['joints']),
           'contacts_truncated': False, 'contact_counts': {'segment_3|/World/pulley|': {'count': 30, 'first_physics_step': 1, 'last_physics_step': 36}}}
    return run, spec, case


def detach(run, spec, case):
    joint = case['joints']['drawer_end']
    spec['objects'][joint]['joint']['enabled'] = False
    run['mechanism_configuration'] = loaded_configuration(spec)
    run['initial_joint_states'][joint]['enabled'] = False
    for sample in run['samples']:
        sample['joints'][joint]['enabled'] = False
        sample['joints'][joint]['anchor_error_m'] = .5
        sample['positions']['/World/drawer'] = [-1, 0, 1]
        sample['joints']['slide']['position_m'] = 0


def activity_fixture():
    spec = {'observation': {'sample_interval_steps': 1}, 'objects': {'weight': body([0, 0, 1]), 'wheel': body([0, 0, 1])}}
    samples = []
    for step in range(1, 62):
        theta = (step-1)*.02
        samples.append({'physics_steps': step, 'simulation_time_s': step/60,
                        'positions': {'/World/weight': [0, 0, 1-(step-1)*.01], '/World/wheel': [0, 0, 1]},
                        'orientations_wxyz': {'/World/weight': [1, 0, 0, 0], '/World/wheel': [math.cos(theta/2), 0, 0, math.sin(theta/2)]}})
    run = {'samples': samples, 'actual_physics_steps': 61, 'requested_physics_steps': 61,
           'simulation_time_s': 61/60, 'observation_interval_steps': 1}
    event = lambda minimum: {'conditions': [{'kind': 'body_displacement', 'body_id': 'weight', 'direction_world': [0, 0, -1], 'minimum_m': minimum}]}
    activity = {'events': {'start': event(0), 'handoff': event(.295), 'end': event(.595)},
                'window': {'start_event': 'start', 'end_event': 'end'},
                'stages': [{'id': 'wheel_pulls', 'purpose': 'wheel transfers motion before its handoff',
                            'start_event': 'start', 'end_event': 'handoff',
                            'roi_world': {'min': [-1, -1, 0], 'max': [1, 1, 2]},
                            'bodies': [{'id': 'wheel', 'minimum_angular_speed_degrees_s': 1}, {'id': 'weight', 'minimum_speed_m_s': .1}]}],
                'limits': {'minimum_chain_duration_s': 1, 'minimum_net_effective_action_s': .5,
                           'minimum_motion_occupancy': .5, 'maximum_idle_s': .5}}
    return run, spec, activity


def spoon_fixture():
    objects = {'trigger': {**body([0, 0, .6], 'sphere'), 'spawn_step': 10},
               'tile': body([-.2, 0, .2]), 'stopper': body([0, 0, .2]),
               'spoon': body([0, 0, .2]), 'sugar': body([0, 0, .25]),
               'cup': {'kind': 'box', 'collision': True, 'position': [1, 0, .1], 'size': [.3, .3, .3]},
               'slide': {'kind': 'joint', 'joint': {'type': 'prismatic', 'body0': None, 'body1': 'stopper', 'axis': 'Y'}},
               'hinge': {'kind': 'joint', 'joint': {'type': 'revolute', 'body0': None, 'body1': 'spoon', 'axis': 'Y'}}}
    case = {'schema': 'simscene.mechanism.v1', 'mechanism': 'spoon_sugar', 'trigger_id': 'trigger', 'release_step': 10,
            'roles': {'lasttile': 'tile', 'stopper': 'stopper', 'spoon': 'spoon', 'sugar': 'sugar', 'cup': 'cup'},
            'joints': {'stopper': 'slide', 'spoon': 'hinge'}, 'axes': {'stopper_world': [0, 1, 0], 'spoon_joint_sign': 1},
            'support_region_local': {'min': [-.05, -.05, 0], 'max': [.05, .05, .1]},
            'receiver': {'interior_world': {'min': [.9, -.1, 0], 'max': [1.1, .1, .2]}, 'sugar_size_m': [.04]*3},
            'thresholds': {'initial_hold_steps': 5, 'initial_max_motion_m': .003, 'initial_max_rotation_degrees': 2,
                           'lasttile_activation_degrees': 5, 'stopper_min_travel_m': .055, 'stopper_initial_max_m': .003,
                           'spoon_activation_degrees': 5, 'spoon_initial_max_degrees': 2,
                           'sugar_leave_min_distance_m': .02, 'sugar_leave_clearance_m': .001,
                           'max_anchor_error_m': .005, 'max_off_axis_m': .003, 'terminal_hold_steps': 20,
                           'terminal_max_motion_m': .002, 'terminal_max_rotation_degrees': 2, 'contact_window_tolerance_steps': 5}}
    spec = {'observation': {'sample_interval_steps': 1}, 'objects': objects}
    samples = []
    for step in range(1, 101):
        positions = {'/World/'+n: copy.deepcopy(o['position']) for n, o in objects.items() if o.get('dynamic') and (n != 'trigger' or step > 10)}
        orientations = {p: [1, 0, 0, 0] for p in positions}
        if step >= 20:
            orientations['/World/tile'] = [math.cos(math.pi/36), 0, math.sin(math.pi/36), 0]
        if step >= 25:
            positions['/World/stopper'][1] += .1
        if step >= 30:
            orientations['/World/spoon'] = [math.cos(math.pi/36), 0, math.sin(math.pi/36), 0]
        if step >= 40:
            positions['/World/sugar'] = [.3, 0, .2]
        if step >= 50:
            positions['/World/sugar'] = [1, 0, .1]
        joints = {}
        for name, kind, coordinate, value in [('slide', 'prismatic', 'position_m', .1 if step >= 25 else 0), ('hinge', 'revolute', 'angle_degrees', 10 if step >= 30 else 0)]:
            joints[name] = {'type': kind, 'enabled': True, 'anchor_error_m': 0, 'anchor0_world_m': [0, 0, .2], 'anchor1_world_m': [0, 0, .2], 'drive_present': False, coordinate: value}
        samples.append({'physics_steps': step, 'simulation_time_s': step/60, 'positions': positions, 'orientations_wxyz': orientations, 'joints': joints})
    contacts = {}
    for a, b, first, last in [('trigger', 'tile', 19, 20), ('tile', 'stopper', 24, 25), ('stopper', 'spoon', 1, 25), ('sugar', 'spoon', 1, 39), ('sugar', 'cup/part_0/Shape', 52, 100)]:
        contacts[a+'|/World/'+b+'|'] = {'count': 10, 'first_physics_step': first, 'last_physics_step': last}
    run = {'requested_physics_steps': 100, 'actual_physics_steps': 100, 'simulation_time_s': 100/60, 'observation_interval_steps': 1,
           'samples': samples, 'spawn_events': [{'id': 'trigger', 'physics_step': 10}], 'contacts_truncated': False,
           'contact_counts': contacts, 'mechanism_configuration': loaded_configuration(spec), 'initial_joint_states': copy.deepcopy(samples[0]['joints'])}
    return run, spec, case


def wheel_fixture():
    compound = lambda position, size, offset: {**body(position, 'compound'), 'parts': [{'kind': 'box', 'size': size, 'position': offset, 'collision': True}]}
    objects = {'trigger': {**body([0, 0, .8], 'sphere'), 'spawn_step': 10},
               'wheel': compound([0, 0, .5], [.1]*3, [.2, 0, 0]), 'latch': body([.25, 0, .5]),
               'door': compound([0, 0, .5], [.08]*3, [0, 0, 0]),
               'seat': {'kind': 'box', 'collision': True, 'position': [0, 0, 0], 'size': [.1]*3},
               'pin': body([.05, 0, .5], 'cylinder', [.04, .04, .1])}
    for name, kind, target, axis in [('wheel_axle', 'revolute', 'wheel', 'Z'), ('latch_slide', 'prismatic', 'latch', 'Y'), ('door_axle', 'revolute', 'door', 'Y')]:
        objects[name] = {'kind': 'joint', 'joint': {'type': kind, 'body0': None, 'body1': target, 'axis': axis}}
    spec = {'observation': {'sample_interval_steps': 1}, 'objects': objects}
    case = {'schema': 'simscene.mechanism.v1', 'mechanism': 'wheel_door_bridge', 'trigger_id': 'trigger', 'release_step': 10,
            'roles': {'wheel': 'wheel', 'latch': 'latch', 'door': 'door', 'seat': 'seat', 'rollingpin': 'pin', 'retainer': 'door'},
            'joints': {'wheel': 'wheel_axle', 'latch': 'latch_slide', 'door': 'door_axle'},
            'axes': {'latch_world': [0, 1, 0], 'rollingpin_world': [1, 0, 0], 'wheel_joint_sign': 1, 'door_joint_sign': 1},
            'geometry': {'wheel_paddle_part_index': 0, 'retainer_part_index': 0},
            'bridge_regions_world': [{'min': [.15, -.1, .4], 'max': [.2, .1, .6]}, {'min': [.27, -.1, .4], 'max': [.32, .1, .6]}],
            'thresholds': {'initial_hold_steps': 5, 'initial_max_motion_m': .003, 'initial_max_rotation_degrees': 2,
                           'wheel_activation_degrees': 5, 'latch_min_travel_m': .055, 'latch_initial_max_m': .003,
                           'door_activation_degrees': 5, 'door_bridge_angle_degrees': 90, 'door_bridge_angle_tolerance_degrees': 2,
                           'rollingpin_release_travel_m': .04, 'max_anchor_error_m': .005, 'max_off_axis_m': .003,
                           'bridge_hold_steps': 5, 'contact_window_tolerance_steps': 5, 'part_contact_tolerance_m': .005,
                           'retainer_release_clearance_m': .005}}
    samples = []
    for step in range(1, 81):
        positions = {'/World/'+n: copy.deepcopy(o['position']) for n, o in objects.items() if o.get('dynamic') and (n != 'trigger' or step > 10)}
        orientations = {p: [1, 0, 0, 0] for p in positions}
        wheel_angle, latch_travel = (10 if step >= 20 else 0), (.1 if step >= 25 else 0)
        door_angle = 90 if step >= 40 else 20 if step >= 30 else 0
        orientations['/World/wheel'] = [math.cos(math.radians(wheel_angle)/2), 0, 0, math.sin(math.radians(wheel_angle)/2)]
        orientations['/World/door'] = [math.cos(math.radians(door_angle)/2), 0, math.sin(math.radians(door_angle)/2), 0]
        positions['/World/latch'][1] += latch_travel
        if step >= 45:
            positions['/World/pin'][0] = .1
        if step >= 50:
            positions['/World/pin'][0] = .17
        if step >= 60:
            positions['/World/pin'][0] = .29
        if step >= 70:
            positions['/World/pin'][0] = .5
        joints = {}
        for name, kind, coordinate, value in [('wheel_axle', 'revolute', 'angle_degrees', wheel_angle), ('latch_slide', 'prismatic', 'position_m', latch_travel), ('door_axle', 'revolute', 'angle_degrees', door_angle)]:
            joints[name] = {'type': kind, 'enabled': True, 'anchor_error_m': 0, 'anchor0_world_m': [0, 0, .5], 'anchor1_world_m': [0, 0, .5], 'drive_present': False, coordinate: value}
        samples.append({'physics_steps': step, 'simulation_time_s': step/60, 'positions': positions, 'orientations_wxyz': orientations, 'joints': joints})
    contacts = {}
    for a, b, first, last in [('trigger', 'wheel', 19, 20), ('wheel', 'latch', 1, 24), ('latch', 'door', 1, 29), ('door', 'seat/part_0/Shape', 40, 80), ('pin', 'door', 1, 58)]:
        contacts[a+'|/World/'+b+'|'] = {'count': 10, 'first_physics_step': first, 'last_physics_step': last}
    run = {'requested_physics_steps': 80, 'actual_physics_steps': 80, 'simulation_time_s': 80/60, 'observation_interval_steps': 1,
           'samples': samples, 'spawn_events': [{'id': 'trigger', 'physics_step': 10}], 'contacts_truncated': False,
           'contact_counts': contacts, 'mechanism_configuration': loaded_configuration(spec), 'initial_joint_states': copy.deepcopy(samples[0]['joints'])}
    return run, spec, case


def make_strict(run, spec):
    spec['observation']['strict_start'] = True
    objects = {n: o for n, o in spec['objects'].items() if o.get('dynamic') and not o.get('spawn_step', 0)}
    initial = {'physics_steps': 0, 'simulation_time_s': 0., 'absolute_physics_step': 3, 'absolute_simulation_time_s': .05,
               'positions': {'/World/'+n: copy.deepcopy(o.get('position', [0, 0, 0])) for n, o in objects.items()},
               'orientations_wxyz': {'/World/'+n: copy.deepcopy(o.get('orientation_wxyz', [1, 0, 0, 0])) for n, o in objects.items()},
               'linear_velocities_m_s': {'/World/'+n: [0, 0, 0] for n in objects},
               'angular_velocities_rad_s': {'/World/'+n: [0, 0, 0] for n in objects},
               'joints': copy.deepcopy(run.setdefault('initial_joint_states', {})), 'followers': {}}
    run['initial_observation'] = initial
    run['run_zero_absolute_physics_step'], run['run_zero_absolute_simulation_time_s'] = 3, .05
    run['initialization_reset'] = {'applied': True, 'phase': 'before_task_start', 'reset_count': 1,
                                  'body_ids': list(objects), 'body_paths': list(initial['positions']),
                                  'authored_pose_readback_max_error_m': 0., 'max_quaternion_error': 0.,
                                  'authored_orientation_readback_max_error_degrees': 0.,
                                  'max_linear_speed_m_s': 0., 'max_angular_speed_rad_s': 0., 'setters_during_task': False,
                                  'absolute_physics_step': 3, 'absolute_simulation_time_s': .05,
                                  'before_warmup_absolute_physics_step': 0, 'before_warmup_absolute_simulation_time_s': 0.,
                                  'after_warmup_absolute_physics_step': 3, 'after_warmup_absolute_simulation_time_s': .05}
    for sample in run['samples']:
        sample['absolute_physics_step'] = 3+sample['physics_steps']
        sample['absolute_simulation_time_s'] = .05+sample['simulation_time_s']
        for field in ('linear_velocities_m_s', 'angular_velocities_rad_s'):
            sample[field] = {p: [0, 0, 0] for p in sample['positions']}
    return run, spec


def seal_fixture(root, run, spec, case, launcher=None):
    from simscene.evidence_integrity import seal
    run = copy.deepcopy(run)
    run.setdefault('seed', 42)
    for name, value in [('result.json', run), ('spec.json', spec), ('acceptance-case.json', case), ('asset-lock.json', {}), ('runtime-lock.json', {})]:
        (root/name).write_text(json.dumps(value))
    (root/'scene.usda').write_text('#usda 1.0\n')
    launcher = launcher or root/'python.sh'
    if not launcher.exists():
        launcher.write_text('synthetic launcher, not executed\n')
    worker = root/'runtime'/'simscene'/'worker'/'isaac_run.py'
    worker.parent.mkdir(parents=True)
    worker.write_text('# synthetic locked worker; never executed\n')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    lock = {'runtime_python': str(launcher), 'runtime_python_sha256': digest(launcher), 'physics_dt_s': 1/60,
            'queue_launcher_python': str(launcher), 'queue_launcher_python_sha256': digest(launcher),
            'seed': run['seed'], 'physics_device': 'cpu', 'runtime_version': 'synthetic',
            'gpu_selection': {'simscene_gpu': '0', 'cuda_visible_devices': '0'},
            'continue_on_controller_error': False, 'archive_verified_objects': False,
            'worker_code_sha256': {'worker/isaac_run.py': digest(worker)}, 'requested_physics_steps': run['requested_physics_steps'],
            'acceptance_case_file': 'acceptance-case.json', 'acceptance_case_sha256': digest(root/'acceptance-case.json')}
    for file, key in [('spec.json', 'spec_sha256'), ('scene.usda', 'stage_sha256'), ('asset-lock.json', 'asset_lock_sha256'), ('runtime-lock.json', 'runtime_lock_sha256')]:
        lock[key] = digest(root/file)
    (root/'run-lock.json').write_text(json.dumps(lock))
    seal(root)


class MechanismCheckTest(unittest.TestCase):
    def test_positive_geometry_does_not_claim_paired_success(self):
        run, spec, case = fixture()
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertTrue(report['wrapped_pulley_geometry_passed'])
        self.assertFalse(report['wrapped_pulley_success'])
        self.assertEqual(report['taut_onset_step'], 11)

    def test_preexisting_pulley_contact_is_not_used_as_activation(self):
        run, spec, case = fixture()
        run['contact_counts']['segment_3|/World/pulley|']['first_physics_step'] = 0
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'])
        self.assertEqual(report['taut_onset_step'], 11)

    def test_falling_weight_with_only_drawer_end_disabled_is_valid_control(self):
        run, spec, case = fixture()
        reference = copy.deepcopy(spec)
        detach(run, spec, case)
        report = evaluate(run, spec, case, 'detached_drawer', reference)
        self.assertTrue(report['passed'], report['checks'])
        spec['objects']['weight']['mass_kg'] *= 2
        self.assertFalse(evaluate(run, spec, case, 'detached_drawer', reference)['checks']['only_drawer_end_joint_changed'])

    def test_detached_drawer_drifting_vertically_cannot_hide_in_xy(self):
        run, spec, case = fixture()
        reference = copy.deepcopy(spec)
        detach(run, spec, case)
        run['samples'][-1]['positions']['/World/drawer'][2] -= .04
        self.assertFalse(evaluate(run, spec, case, 'detached_drawer', reference)['passed'])

    def test_motion_during_slack_and_failure_to_fall_are_rejected(self):
        for kind in ('slack', 'fall'):
            run, spec, case = fixture()
            for sample in run['samples']:
                if kind == 'slack' and sample['physics_steps'] == 6:
                    sample['positions']['/World/drawer'][0] += .02
                if kind == 'fall':
                    sample['positions']['/World/weight'][2] = 1
            self.assertFalse(evaluate(run, spec, case)['passed'])

    def test_endpoint_tension_without_wrap_and_without_contact_fail(self):
        for kind in ('wrap', 'contact'):
            run, spec, case = fixture()
            if kind == 'contact':
                run['contact_counts'] = {}
            else:
                for sample in run['samples']:
                    for name in case['rope']['joint_ids'][3:6]:
                        sample['joints'][name]['anchor0_world_m'][2] += .2
                        # Shared node lists also move anchor1 in this fixture.
            self.assertFalse(evaluate(run, spec, case)['passed'])

    def test_pulley_only_rotating_before_rope_tightens_is_insufficient(self):
        run, spec, case = fixture()
        for sample in run['samples']:
            sample['joints']['axle']['angle_degrees'] = min(20, sample['physics_steps']*2)
        self.assertFalse(evaluate(run, spec, case)['checks']['free_pulley_rotates_during_pull'])

    def test_missing_first_interior_last_duplicate_and_wrong_time_fail(self):
        for kind in ('first', 'interior', 'last', 'duplicate', 'clock', 'pose', 'nan'):
            run, spec, case = fixture()
            if kind in ('first', 'interior', 'last'):
                del run['samples'][{'first': 0, 'interior': 15, 'last': -1}[kind]]
            elif kind == 'duplicate':
                run['samples'][10] = copy.deepcopy(run['samples'][9])
            elif kind == 'clock':
                run['samples'][10]['simulation_time_s'] *= 2
            elif kind == 'pose':
                del run['samples'][10]['positions']['/World/segment_2']
            else:
                run['samples'][10]['orientations_wxyz']['/World/weight'][0] = float('nan')
            self.assertFalse(evaluate(run, spec, case)['passed'], kind)

    def test_hidden_loaded_drive_and_wrong_joint_target_fail(self):
        for kind in ('drive', 'target', 'missing_config', 'initial', 'interval'):
            run, spec, case = fixture()
            if kind == 'drive':
                run['mechanism_configuration']['joints'][-1]['drives'] = ['PhysicsDriveAPI:angular']
            elif kind == 'target':
                run['mechanism_configuration']['joints'][-1]['body1'] = ['/World/weight']
            elif kind == 'missing_config':
                del run['mechanism_configuration']
            elif kind == 'initial':
                del run['initial_joint_states']
            else:
                run['observation_interval_steps'] = 5
            self.assertFalse(evaluate(run, spec, case)['passed'], kind)

    def test_follower_conveyor_and_scheduled_downstream_fail(self):
        for field, value in [('pose_follower', {'enabled': True}), ('conveyor', {'speed_m_s': 1}), ('spawn_step', 10)]:
            run, spec, case = fixture()
            spec['objects']['drawer'][field] = value
            self.assertFalse(evaluate(run, spec, case)['passed'])

    def test_free_span_selection_cannot_skip_bad_rope_nodes(self):
        _, _, case = fixture()
        case['rope']['free_spans'] = [[0, 1], [5, 7]]
        with self.assertRaisesRegex(ValueError, 'partition'):
            validate_case(case)

    def test_rigidly_fixed_segment_chain_is_not_a_rope(self):
        run, spec, case = fixture()
        name = case['rope']['joint_ids'][3]
        spec['objects'][name]['joint']['type'] = 'fixed'
        run['mechanism_configuration'] = loaded_configuration(spec)
        run['initial_joint_states'][name]['type'] = 'fixed'
        for sample in run['samples']:
            sample['joints'][name]['type'] = 'fixed'
        self.assertFalse(evaluate(run, spec, case)['checks']['continuous_physical_rope_topology'])

    def test_frozen_geometry_rule_tracks_rope_nodes_sliding_around_rim(self):
        run, spec, case = fixture()
        for sample in run['samples'][14:]:
            shift = sample['positions']['/World/drawer'][0]+1
            c = math.sqrt(.125)
            nodes = [[-1+shift, 0, 1], [0, 0, 1], [-c, c, 1], [0, .5, 1], [c, c, 1], [0, 0, 1], [0, 0, 1], [1, 0, 1]]
            for first, last in ((0, 2), (4, 7)):
                a, b = nodes[first][:], nodes[last][:]
                for i in range(first+1, last):
                    t = (i-first)/(last-first)
                    nodes[i] = [x+(y-x)*t for x, y in zip(a, b)]
            for i, name in enumerate(case['rope']['joint_ids']):
                sample['joints'][name]['anchor0_world_m'] = nodes[i]
                sample['joints'][name]['anchor1_world_m'] = nodes[i]
        self.assertFalse(evaluate(run, spec, case)['passed'])
        case['rope']['partition_mode'] = 'rim_geometry'
        case['rope']['wrap_span'] = [1, 6]
        del case['rope']['free_spans']
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertEqual(report['geometry_per_step'][0]['measured_wrap_span'], [3, 5])
        self.assertEqual(report['geometry_per_step'][-1]['measured_wrap_span'], [2, 4])

    def test_direct_fallback_never_counts_as_wrapped_success(self):
        run, spec, case = fixture()
        case['rope_model'] = 'segmented_direct'
        case['rope']['free_spans'] = [[0, 7]]
        del case['roles']['pulley']
        del case['joints']['pulley']
        del spec['objects']['pulley']
        del spec['objects']['axle']
        del run['initial_joint_states']['axle']
        for sample in run['samples']:
            del sample['positions']['/World/pulley']
            del sample['orientations_wxyz']['/World/pulley']
            del sample['joints']['axle']
            if sample['physics_steps'] >= 11:
                for i, name in enumerate(case['rope']['joint_ids']):
                    node = [-1+i*2/7, 0, 1]
                    sample['joints'][name]['anchor0_world_m'] = node
                    sample['joints'][name]['anchor1_world_m'] = node
        run['mechanism_configuration'] = loaded_configuration(spec)
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertFalse(report['wrapped_pulley_success'])
        self.assertFalse(report['wrapped_pulley_geometry_passed'])
        self.assertEqual(report['rope_model'], 'segmented_direct')

    def test_output_case_and_spec_tampering_fail_before_physics_acceptance(self):
        for changed in ('result.json', 'spec.json', 'acceptance-case.json'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run, spec, case = fixture()
                seal_fixture(root, run, spec, case)
                self.assertTrue(verify_run(root)['passed'])
                with (root/changed).open('a') as file:
                    file.write(' ')
                report = verify_run(root)
                self.assertFalse(report['passed'], changed)
                self.assertNotIn('motion_per_step', report)

    def test_paired_locked_runs_establish_paired_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            positive, control = Path(directory)/'positive', Path(directory)/'control'
            positive.mkdir()
            control.mkdir()
            run, spec, case = fixture()
            seal_fixture(positive, run, spec, case)
            detach(run, spec, case)
            seal_fixture(control, run, spec, case, positive/'python.sh')
            report = verify_run(control, mode='detached_drawer', reference_run=positive)
            self.assertTrue(report['passed'], report.get('checks'))
            self.assertTrue(report['paired_causal_acceptance'])
            self.assertTrue(report['wrapped_pulley_success'])

    def test_paired_runs_with_different_frozen_cases_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            positive, control = Path(directory)/'positive', Path(directory)/'control'
            positive.mkdir()
            control.mkdir()
            run, spec, case = fixture()
            seal_fixture(positive, run, spec, case)
            detach(run, spec, case)
            case['thresholds']['weight_min_drop_m'] = .19
            seal_fixture(control, run, spec, case, positive/'python.sh')
            self.assertFalse(verify_run(control, mode='detached_drawer', reference_run=positive)['passed'])

    def test_invalid_mass_kg_cannot_hide_behind_legacy_mass_field(self):
        for factory in (fixture, spoon_fixture, wheel_fixture):
            for value in (0, -.1, True, float('nan')):
                run, spec, case = factory()
                name = case['roles']['sugar' if case['mechanism'] == 'spoon_sugar' else 'weight' if case['mechanism'] == 'rope_drawer' else 'rollingpin']
                spec['objects'][name]['mass_kg'] = value
                spec['objects'][name]['mass'] = 1
                self.assertFalse(evaluate(run, spec, case)['checks']['all_roles_are_physical_bodies'])

    def test_sleep_threshold_and_scene_ccd_require_actual_loaded_readback(self):
        for wrong in ('sleep_missing', 'sleep_wrong', 'scene_missing', 'scene_false', 'scene_integer'):
            run, spec, case = fixture()
            spec['objects']['weight']['physics'] = {'sleep_threshold': 0, 'enable_ccd': True}
            run['mechanism_configuration']['body_settings']['weight'] = {'sleep_threshold': 0, 'enable_ccd': True}
            run['mechanism_configuration']['scene_enable_ccd'] = True
            if wrong == 'sleep_missing':
                del run['mechanism_configuration']['body_settings']['weight']['sleep_threshold']
            elif wrong == 'sleep_wrong':
                run['mechanism_configuration']['body_settings']['weight']['sleep_threshold'] = .005
            elif wrong == 'scene_missing':
                del run['mechanism_configuration']['scene_enable_ccd']
            else:
                run['mechanism_configuration']['scene_enable_ccd'] = False if wrong == 'scene_false' else 1
            self.assertFalse(evaluate(run, spec, case)['passed'], wrong)
        run['mechanism_configuration']['scene_enable_ccd'] = True
        self.assertTrue(evaluate(run, spec, case)['passed'])

    def test_result_seed_must_match_its_run_lock(self):
        from simscene.evidence_integrity import seal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, spec, case = fixture()
            seal_fixture(root, run, spec, case)
            result = json.loads((root/'result.json').read_text())
            result['seed'] = 43
            (root/'result.json').write_text(json.dumps(result))
            seal(root)
            report = verify_run(root)
            self.assertFalse(report['passed'])
            self.assertFalse(report['result_seed_matches_run_lock'])
            self.assertTrue(report['output_integrity']['passed'])

    def test_paired_runs_require_equal_runtime_manifests_even_when_both_are_sealed(self):
        from simscene.evidence_integrity import seal
        for field in PAIRED_MANIFEST_FIELDS:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                positive, control = Path(directory)/'positive', Path(directory)/'control'
                positive.mkdir()
                control.mkdir()
                run, spec, case = fixture()
                seal_fixture(positive, run, spec, case)
                detach(run, spec, case)
                seal_fixture(control, run, spec, case, positive/'python.sh')
                lock = json.loads((control/'run-lock.json').read_text())
                result = json.loads((control/'result.json').read_text())
                if field == 'seed':
                    lock[field] = result['seed'] = 43
                elif field == 'requested_physics_steps':
                    last = copy.deepcopy(result['samples'][-1])
                    last['physics_steps'] += 1
                    last['simulation_time_s'] = last['physics_steps']/60
                    result['samples'].append(last)
                    lock[field] = result['requested_physics_steps'] = result['actual_physics_steps'] = last['physics_steps']
                    result['simulation_time_s'] = last['simulation_time_s']
                elif field == 'physics_dt_s':
                    lock[field] /= 2
                    result['simulation_time_s'] /= 2
                    for sample in result['samples']:
                        sample['simulation_time_s'] /= 2
                elif field == 'worker_code_sha256':
                    code = control/'runtime/simscene/worker/isaac_run.py'
                    code.write_text('# different synthetic worker, not executed\n')
                    lock[field] = {'worker/isaac_run.py': hashlib.sha256(code.read_bytes()).hexdigest()}
                elif field in ('runtime_python', 'runtime_python_sha256', 'queue_launcher_python', 'queue_launcher_python_sha256'):
                    code = control/'other-python.sh'
                    code.write_text('other synthetic launcher, not executed\n')
                    prefix = 'queue_launcher_python' if field.startswith('queue_') else 'runtime_python'
                    lock[prefix] = str(code)
                    lock[prefix+'_sha256'] = hashlib.sha256(code.read_bytes()).hexdigest()
                elif field == 'gpu_selection':
                    lock[field] = {'simscene_gpu': '1', 'cuda_visible_devices': '1'}
                elif field in ('continue_on_controller_error', 'archive_verified_objects'):
                    lock[field] = True
                else:
                    lock[field] = 'different'
                (control/'run-lock.json').write_text(json.dumps(lock))
                (control/'result.json').write_text(json.dumps(result))
                seal(control)
                report = verify_run(control, mode='detached_drawer', reference_run=positive)
                self.assertTrue(report['input_integrity']['passed'])
                self.assertTrue(report['output_integrity']['passed'])
                self.assertTrue(report['reference_positive_passed'])
                self.assertTrue(report['checks']['only_drawer_end_joint_changed'])
                self.assertFalse(report['paired_manifest_fields_match'][field])
                self.assertFalse(report['passed'])

    def test_two_missing_runtime_fields_do_not_count_as_matching_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            positive, control = Path(directory)/'positive', Path(directory)/'control'
            positive.mkdir()
            control.mkdir()
            run, spec, case = fixture()
            seal_fixture(positive, run, spec, case)
            detach(run, spec, case)
            seal_fixture(control, run, spec, case, positive/'python.sh')
            for root in (positive, control):
                lock = json.loads((root/'run-lock.json').read_text())
                del lock['gpu_selection']
                (root/'run-lock.json').write_text(json.dumps(lock))
            report = verify_run(control, mode='detached_drawer', reference_run=positive)
            self.assertTrue(report['reference_positive_passed'])
            self.assertFalse(report['paired_manifest_fields_match']['gpu_selection'])
            self.assertFalse(report['passed'])


class StrictInitialStateTest(unittest.TestCase):
    def test_all_mechanism_branches_accept_complete_strict_same_boundary_zero(self):
        for factory in (fixture, spoon_fixture, wheel_fixture):
            run, spec, case = factory()
            make_strict(run, spec)
            report = evaluate(run, spec, case)
            self.assertTrue(report['passed'], report['checks'])
            self.assertTrue(report['strict_initial_state']['required'])
            self.assertTrue(report['strict_initial_state']['passed'])
            self.assertEqual(run['samples'][0]['physics_steps'], 1)

    def test_legacy_mode_does_not_claim_strict_initial_evidence(self):
        run, spec, case = fixture()
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'])
        self.assertFalse(report['strict_initial_state']['required'])
        self.assertIn('Legacy', report['strict_initial_state']['scope'])

    def test_case_or_spec_request_requires_strict_evidence(self):
        for source in ('case', 'spec', 'invalid_flag'):
            run, spec, case = fixture()
            if source == 'spec':
                spec['observation']['strict_start'] = True
            else:
                case['require_strict_initial_state'] = True if source == 'case' else 'false'
            report = evaluate(run, spec, case)
            self.assertFalse(report['passed'])
            self.assertTrue(report['strict_initial_state']['required'])

    def test_case_requirement_cannot_be_bypassed_by_attaching_reset_to_legacy_mode(self):
        run, spec, case = fixture()
        make_strict(run, spec)
        case['require_strict_initial_state'] = True
        spec['observation']['strict_start'] = False
        report = evaluate(run, spec, case)
        self.assertFalse(report['checks']['strict_initial_mode_enabled'])

    def test_initial_pose_quaternion_and_velocity_are_independently_recomputed(self):
        for change in ('position', 'quaternion', 'linear', 'angular'):
            run, spec, case = fixture()
            make_strict(run, spec)
            initial = run['initial_observation']
            if change == 'position':
                initial['positions']['/World/weight'][0] += 2e-6
            elif change == 'quaternion':
                initial['orientations_wxyz']['/World/weight'] = [math.cos(.001), 0, 0, math.sin(.001)]
            else:
                initial['linear_velocities_m_s' if change == 'linear' else 'angular_velocities_rad_s']['/World/weight'][0] = 2e-7
            report = evaluate(run, spec, case)
            self.assertTrue(report['checks']['strict_initial_reset_readback_errors_bounded'])
            self.assertFalse(report['checks']['strict_initial_measured_state_matches_authored_zero_velocity'])

    def test_reset_once_before_task_and_reported_readback_bounds_are_required(self):
        for field, wrong in [('applied', False), ('phase', 'during_task'), ('reset_count', 2), ('setters_during_task', True), ('authored_pose_readback_max_error_m', .01), ('max_quaternion_error', .01), ('max_linear_speed_m_s', .01)]:
            run, spec, case = fixture()
            make_strict(run, spec)
            run['initialization_reset'][field] = wrong
            self.assertFalse(evaluate(run, spec, case)['passed'], field)

    def test_all_initial_bodies_and_only_unspawned_bodies_must_be_present(self):
        for change in ('map', 'ids', 'paths', 'premature_spawn'):
            run, spec, case = spoon_fixture()
            make_strict(run, spec)
            if change == 'map':
                del run['initial_observation']['linear_velocities_m_s']['/World/sugar']
            elif change == 'ids':
                run['initialization_reset']['body_ids'].remove('sugar')
            elif change == 'paths':
                run['initialization_reset']['body_paths'].remove('/World/sugar')
            else:
                run['initial_observation']['positions']['/World/trigger'] = [0, 0, .6]
            self.assertFalse(evaluate(run, spec, case)['passed'], change)

    def test_every_absolute_step_and_time_must_share_the_sample_zero_boundary(self):
        for change in ('counter', 'time', 'zero_counter', 'zero_time', 'warmup_advanced', 'relative_zero'):
            run, spec, case = fixture()
            make_strict(run, spec)
            if change == 'counter':
                run['samples'][9]['absolute_physics_step'] += 1
            elif change == 'time':
                run['samples'][9]['absolute_simulation_time_s'] += .01
            elif change == 'zero_counter':
                run['run_zero_absolute_physics_step'] += 1
            elif change == 'zero_time':
                run['run_zero_absolute_simulation_time_s'] += .01
            elif change == 'warmup_advanced':
                run['initialization_reset']['after_warmup_absolute_physics_step'] -= 1
            else:
                run['initial_observation']['physics_steps'] = False
            self.assertFalse(evaluate(run, spec, case)['passed'], change)

    def test_joint_zero_and_all_task_tensor_velocities_must_be_complete(self):
        for change in ('joint', 'missing_initial_joint', 'missing_task_joint', 'velocity', 'nan'):
            run, spec, case = fixture()
            make_strict(run, spec)
            if change == 'joint':
                run['initial_observation']['joints']['axle']['angle_degrees'] = 1
            elif change == 'missing_initial_joint':
                del run['initial_observation']['joints']['axle']
                del run['initial_joint_states']['axle']
            elif change == 'missing_task_joint':
                del run['samples'][8]['joints']['axle']
            elif change == 'velocity':
                del run['samples'][8]['angular_velocities_rad_s']['/World/segment_2']
            else:
                run['samples'][8]['linear_velocities_m_s']['/World/segment_2'][0] = float('nan')
            self.assertFalse(evaluate(run, spec, case)['passed'], change)

    def test_strict_motion_origin_is_sample_zero_not_first_completed_step(self):
        run, spec, case = fixture()
        make_strict(run, spec)
        for sample in run['samples']:
            sample['positions']['/World/weight'][2] -= .1
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertAlmostEqual(report['motion_per_step'][0]['weight_drop_m'], .1)

    def test_initial_quiet_window_includes_the_restored_zero(self):
        run, spec, case = spoon_fixture()
        make_strict(run, spec)
        for sample in run['samples'][:10]:
            sample['positions']['/World/sugar'][0] += .01
        self.assertFalse(evaluate(run, spec, case)['checks']['initial_mechanism_is_quiet'])

    def test_standalone_activity_also_rejects_missing_strict_zero(self):
        run, spec, activity = activity_fixture()
        spec['observation']['strict_start'] = True
        report = measure_activity(run, spec, activity)
        self.assertFalse(report['passed'])
        self.assertNotIn('metrics', report)

    def test_distinct_ids_cannot_alias_the_same_physics_body_path(self):
        run, spec, case = fixture()
        for name in ('alias-name', 'alias_name'):
            spec['objects'][name] = body([0, 0, 1])
        for sample in run['samples']:
            sample['positions']['/World/alias_name'] = [0, 0, 1]
            sample['orientations_wxyz']['/World/alias_name'] = [1, 0, 0, 0]
        make_strict(run, spec)
        report = strict_initial_state(run, spec, case)
        self.assertFalse(report['checks']['strict_initial_body_paths_are_unique'])
        self.assertFalse(report['passed'])

    def test_complete_strict_activity_remains_a_union_of_measured_motion(self):
        run, spec, activity = activity_fixture()
        make_strict(run, spec)
        report = measure_activity(run, spec, activity)
        self.assertTrue(report['passed'], report)
        self.assertAlmostEqual(report['metrics']['net_effective_action_s'], .5)

    def test_strict_relative_joint_event_uses_zero_not_first_task_joint_sample(self):
        run, spec, activity = activity_fixture()
        spec['objects']['hinge'] = {'kind': 'joint', 'joint': {'type': 'revolute', 'body0': None, 'body1': 'wheel', 'axis': 'Z'}}
        zero = {'type': 'revolute', 'enabled': True, 'anchor_error_m': 0., 'anchor0_world_m': [0, 0, 1], 'anchor1_world_m': [0, 0, 1], 'drive_present': False, 'angle_degrees': 0.}
        run['initial_joint_states'] = {'hinge': zero}
        for sample in run['samples']:
            value = 10+sample['physics_steps']
            sample['joints'] = {'hinge': {**zero, 'angle_degrees': value}}
            sample['orientations_wxyz']['/World/wheel'] = [math.cos(math.radians(value)/2), 0, 0, math.sin(math.radians(value)/2)]
        make_strict(run, spec)
        activity['events']['hinge_started'] = {'conditions': [{'kind': 'joint_coordinate', 'joint_id': 'hinge', 'coordinate': 'angle_degrees', 'relative_to_initial': True, 'minimum': 5}]}
        report = measure_activity(run, spec, activity)
        self.assertEqual(report['events']['hinge_started']['onset_step'], 1)


class SpoonMechanismTest(unittest.TestCase):
    def test_ordered_passive_spoon_reports_touch_entry_and_confirmation_separately(self):
        run, spec, case = spoon_fixture()
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertEqual(report['events']['first_whole_sugar_entry']['onset_step'], 50)
        self.assertEqual(report['events']['first_cup_contact']['onset_step'], 52)
        self.assertEqual(report['events']['sugar_stable']['confirmation_step'], 69)
        self.assertFalse(report['paired_control_required_for_causal_acceptance'])
        self.assertFalse(report['formal_whole_room_acceptance'])

    def test_touching_cup_or_center_only_inside_cannot_pass_whole_sugar(self):
        for location in ([1, 0, -.01], [1.09, 0, .1]):
            run, spec, case = spoon_fixture()
            for sample in run['samples'][49:]:
                sample['positions']['/World/sugar'] = list(location)
            report = evaluate(run, spec, case)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['whole_sugar_received_and_stable'])
            self.assertTrue(report['checks']['first_cup_contact_is_new_and_observed'])
            self.assertEqual(report['events']['first_cup_contact']['onset_step'], 52)

    def test_early_spoon_or_sugar_activation_cannot_be_hidden_by_after_gate(self):
        for kind in ('spoon', 'sugar'):
            run, spec, case = spoon_fixture()
            if kind == 'spoon':
                run['samples'][20]['joints']['hinge']['angle_degrees'] = 10
            else:
                run['samples'][27]['positions']['/World/sugar'] = [.3, 0, .2]
            self.assertFalse(evaluate(run, spec, case)['checks']['physical_events_in_required_order'])

    def test_existing_first_contact_is_not_handoff_timing(self):
        run, spec, case = spoon_fixture()
        pair = run['contact_counts']['tile|/World/stopper|']
        pair['first_physics_step'], pair['last_physics_step'] = 1, 100
        report = evaluate(run, spec, case)
        self.assertFalse(report['passed'])
        self.assertFalse(report['contacts']['lasttile_to_stopper']['passed'])
        self.assertEqual(report['events']['stopper_clear']['onset_step'], 25)

    def test_inverted_or_out_of_run_contact_summary_is_not_a_witness(self):
        for first, last in ((25, 24), (24, 101)):
            run, spec, case = spoon_fixture()
            pair = run['contact_counts']['tile|/World/stopper|']
            pair['first_physics_step'], pair['last_physics_step'] = first, last
            self.assertFalse(evaluate(run, spec, case)['contacts']['lasttile_to_stopper']['passed'])

    def test_sugar_must_initially_be_quiet_on_physical_spoon(self):
        for kind in ('support', 'motion', 'size'):
            run, spec, case = spoon_fixture()
            if kind == 'support':
                del run['contact_counts']['sugar|/World/spoon|']
            elif kind == 'motion':
                run['samples'][4]['positions']['/World/sugar'][2] += .01
            else:
                case['receiver']['sugar_size_m'][0] = .03
            self.assertFalse(evaluate(run, spec, case)['passed'], kind)

    def test_temporary_cup_stability_followed_by_escape_fails(self):
        run, spec, case = spoon_fixture()
        run['samples'][-1]['positions']['/World/sugar'][0] = 2
        self.assertFalse(evaluate(run, spec, case)['checks']['sugar_remains_contained_after_stability'])

    def test_locked_spoon_case_supported_without_mutating_inputs_or_results(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, case = spoon_fixture()
            root = Path(directory)
            seal_fixture(root, run, spec, case)
            digest = lambda: {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            original = digest()
            report = verify_run(root)
            self.assertTrue(report['passed'], report['checks'])
            self.assertFalse(report['paired_control_required_for_causal_acceptance'])
            self.assertEqual(digest(), original)


class WheelDoorMechanismTest(unittest.TestCase):
    def test_real_part_evidence_ordered_bridge_and_traversal(self):
        run, spec, case = wheel_fixture()
        report = evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertEqual(report['events']['door_bridge']['onset_step'], 40)
        self.assertEqual(report['events']['door_bridge']['confirmation_step'], 44)
        self.assertEqual(report['events']['rollingpin_release']['onset_step'], 45)
        self.assertEqual(report['bridge_region_entry_steps'], [50, 60])

    def test_pin_release_before_door_becomes_bridge_fails(self):
        run, spec, case = wheel_fixture()
        run['samples'][34]['positions']['/World/pin'][0] = .1
        self.assertFalse(evaluate(run, spec, case)['checks']['door_is_bridge_before_physical_pin_release'])

    def test_root_contact_without_the_real_paddle_near_latch_fails(self):
        run, spec, case = wheel_fixture()
        spec['objects']['wheel']['parts'][0]['position'] = [1, 0, 0]
        self.assertFalse(evaluate(run, spec, case)['checks']['actual_wheel_paddle_reaches_latch'])

    def test_noncolliding_or_nonexistent_retainer_part_cannot_be_invented(self):
        for kind in ('collision', 'index'):
            run, spec, case = wheel_fixture()
            if kind == 'collision':
                spec['objects']['door']['parts'][0]['collision'] = False
                self.assertFalse(evaluate(run, spec, case)['passed'])
            else:
                case['geometry']['retainer_part_index'] = 3
                with self.assertRaisesRegex(ValueError, 'does not exist'):
                    evaluate(run, spec, case)

    def test_preexisting_contact_does_not_supply_wheel_activation_time(self):
        run, spec, case = wheel_fixture()
        run['contact_counts']['wheel|/World/latch|']['last_physics_step'] = 80
        self.assertFalse(evaluate(run, spec, case)['contacts']['wheel_paddle_to_latch']['passed'])

    def test_pin_must_cross_regions_in_order_and_have_actual_bridge_contact(self):
        for kind in ('order', 'contact'):
            run, spec, case = wheel_fixture()
            if kind == 'order':
                run['samples'][46]['positions']['/World/pin'][0] = .29
            else:
                del run['contact_counts']['pin|/World/door|']
            self.assertFalse(evaluate(run, spec, case)['passed'])

    def test_door_must_stay_a_bridge_and_physically_reach_its_seat(self):
        for kind in ('angle', 'seat'):
            run, spec, case = wheel_fixture()
            if kind == 'angle':
                run['samples'][54]['joints']['door_axle']['angle_degrees'] = 60
            else:
                del run['contact_counts']['door|/World/seat/part_0/Shape|']
            self.assertFalse(evaluate(run, spec, case)['passed'])

    def test_off_axis_latch_motion_including_z_cannot_count_as_withdrawal(self):
        run, spec, case = wheel_fixture()
        for sample in run['samples'][24:]:
            sample['positions']['/World/latch'][1] = 0
            sample['positions']['/World/latch'][2] += .1
        self.assertFalse(evaluate(run, spec, case)['checks']['latch_follows_frozen_xyz_axis'])


class ActivityCheckTest(unittest.TestCase):
    def test_identical_float32_quaternions_cannot_create_angular_activity(self):
        run, spec, activity = activity_fixture()
        activity['stages'][0]['bodies'] = [{'id': 'wheel', 'minimum_angular_speed_degrees_s': 1}]
        for sample in run['samples']:
            sample['orientations_wxyz']['/World/wheel'] = [.9999999, 0, 0, 0]
        report = measure_activity(run, spec, activity)
        self.assertEqual(report['metrics']['net_effective_action_s'], 0)
        self.assertFalse(report['passed'])

    def test_xyz_motion_parallel_union_and_phase_excludes_residual_wheel(self):
        run, spec, activity = activity_fixture()
        report = measure_activity(run, spec, activity)
        self.assertTrue(report['passed'], report)
        self.assertAlmostEqual(report['metrics']['chain_duration_s'], 1)
        self.assertAlmostEqual(report['metrics']['net_effective_action_s'], .5)
        self.assertAlmostEqual(report['metrics']['motion_occupancy'], .5)
        self.assertAlmostEqual(report['metrics']['maximum_idle_s'], .5)
        self.assertEqual(report['per_step_motion_flags'][0]['body_ids'], ['weight', 'wheel'])
        self.assertFalse(report['per_step_motion_flags'][-1]['active'])

    def test_roi_and_camera_motion_do_not_add_activity(self):
        run, spec, activity = activity_fixture()
        activity['stages'][0]['roi_world'] = {'min': [10, 10, 10], 'max': [11, 11, 11]}
        for sample in run['samples']:
            sample['cameras'] = {'cinematic': {'position': [sample['physics_steps'], 0, 0]}}
        report = measure_activity(run, spec, activity)
        self.assertFalse(report['passed'])
        self.assertEqual(report['metrics']['net_effective_action_s'], 0)

    def test_missing_step_cannot_be_interpolated_into_action_time(self):
        run, spec, activity = activity_fixture()
        del run['samples'][23]
        report = measure_activity(run, spec, activity)
        self.assertFalse(report['passed'])
        self.assertNotIn('metrics', report)

    def test_spawn_boundary_and_first_observed_baseline(self):
        run, spec, activity = activity_fixture()
        spec['objects']['ball'] = body([0, 0, 1])
        spec['objects']['ball']['spawn_step'] = 10
        for sample in run['samples'][10:]:
            sample['positions']['/World/ball'] = [0, 0, 1-(sample['physics_steps']-11)*.01]
            sample['orientations_wxyz']['/World/ball'] = [1, 0, 0, 0]
        run['spawn_events'] = [{'id': 'ball', 'physics_step': 10}]
        activity['events']['start'] = {'kind': 'spawn', 'body_id': 'ball', 'physics_step': 10}
        activity['events']['ball_falls'] = {'conditions': [{'kind': 'body_displacement', 'body_id': 'ball', 'direction_world': [0, 0, -1], 'minimum_m': .045}]}
        activity['limits'] = {}
        report = measure_activity(run, spec, activity)
        self.assertTrue(report['passed'])
        self.assertEqual(report['events']['start']['onset_step'], 10)
        self.assertEqual(report['events']['ball_falls']['onset_step'], 16)

    def test_driver_cannot_inflate_standalone_activity_measurement(self):
        run, spec, activity = activity_fixture()
        spec['objects']['wheel']['pose_follower'] = {'enabled': True}
        self.assertFalse(measure_activity(run, spec, activity)['passed'])

    def test_rotated_whole_sugar_and_stability_onset_are_measured(self):
        run, spec, activity = activity_fixture()
        spec['objects']['weight']['size'] = [.08, .08, .08]
        spec['objects']['cup'] = {'kind': 'box', 'position': [0, 0, 0]}
        for sample in run['samples']:
            sample['positions']['/World/weight'] = ([.3, 0, .1] if sample['physics_steps'] < 31 else [0, 0, .1])
        activity['events'] = {
            'start': {'conditions': [{'kind': 'body_displacement', 'body_id': 'weight', 'minimum_m': 0}]},
            'sugar_stable': {'hold_steps': 20, 'conditions': [{'kind': 'contained_box', 'body_id': 'weight', 'receiver_id': 'cup', 'inner_min_m': [-.06, -.06, 0], 'inner_max_m': [.06, .06, .2]}],
                             'stability': {'body_id': 'weight', 'max_motion_m': .001, 'max_rotation_degrees': 1}},
        }
        activity['window']['end_event'] = 'sugar_stable'
        activity['stages'][0]['end_event'] = 'sugar_stable'
        activity['limits'] = {}
        report = measure_activity(run, spec, activity)
        self.assertTrue(report['passed'])
        self.assertEqual(report['events']['sugar_stable'], {'onset_step': 31, 'confirmation_step': 50})
        self.assertAlmostEqual(report['metrics']['chain_duration_s'], .5)
        # Center still fits, but a rotated corner no longer fits this narrow cup.
        for sample in run['samples'][30:]:
            sample['orientations_wxyz']['/World/weight'] = [math.cos(math.pi/8), 0, 0, math.sin(math.pi/8)]
        activity['events']['sugar_stable']['conditions'][0]['inner_max_m'][0] = .05
        self.assertFalse(measure_activity(run, spec, activity)['passed'])

    def test_short_quiet_tail_and_excursion_inside_hold_fail_stability(self):
        run, spec, activity = activity_fixture()
        spec['objects']['cup'] = {'kind': 'box', 'position': [0, 0, 0]}
        definition = {'hold_steps': 61, 'conditions': [{'kind': 'contained_box', 'body_id': 'weight', 'receiver_id': 'cup', 'inner_min_m': [-1, -1, 0], 'inner_max_m': [1, 1, 2]}],
                      'stability': {'body_id': 'weight', 'max_motion_m': .01}}
        activity['events']['end'] = definition
        for sample in run['samples']:
            sample['positions']['/World/weight'] = [0, 0, 1]
        run['samples'][30]['positions']['/World/weight'][0] = .02
        self.assertFalse(measure_activity(run, spec, activity)['passed'])


if __name__ == '__main__':
    unittest.main()
