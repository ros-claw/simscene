"""CPU-only counterexamples. All trajectories are synthetic, not Isaac runs."""
import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from simscene.verification import passive_network as p


def body(position, label, kind='box', size=None, spawn=0):
    return {'kind': kind, 'dynamic': True, 'collision': True, 'position': position, 'orientation_wxyz': [1, 0, 0, 0],
            'size': size or [.06]*3, 'mass_kg': .1, 'class_label': label, **({'spawn_step': spawn} if spawn else {})}


def fixture(mode='positive'):
    objects = {'ball': body([-.4, 0, 1], 'initial_ball', 'sphere', [.04]*3, 5),
               'tile_a': body([-.3, 0, .2], 'domino_tile', size=[.012, .04, .1]),
               'tile_b': body([-.2, 0, .2], 'domino_tile', size=[.012, .04, .1]),
               'weight': body([-.1, 0, .5], 'counterweight'), 'rope': body([0, 0, .5], 'rope_link', 'capsule', [.01, .01, .1]),
               'drawer': body([.1, 0, .3], 'drawer'), 'book': body([.25, 0, .3], 'book'),
               'door': body([.4, 0, .4], 'door'), 'spoon': body([.6, 0, .3], 'spoon'),
               'sugar': body([.6, 0, .36], 'sugar', size=[.02]*3),
               'cup': {'kind': 'box', 'collision': True, 'position': [1, 0, 0], 'size': [.3]*3}}
    for name, kind, a, b, axis in [('rope_weight', 'spherical', 'weight', 'rope', None), ('rope_drawer', 'spherical', 'rope', 'drawer', None),
                                   ('drawer_slide', 'prismatic', None, 'drawer', 'X'), ('door_hinge', 'revolute', None, 'door', 'Y'), ('spoon_hinge', 'revolute', None, 'spoon', 'Y')]:
        cfg = {'type': kind, 'body0': a, 'body1': b}
        if axis:
            cfg.update(axis=axis, lower_limit=0, upper_limit=100 if kind == 'revolute' else 1)
        objects[name] = {'kind': 'joint', 'joint': cfg}
    reference = {'schema_version': '0.1', 'scene_id': 'synthetic_network', 'revision': 1, 'requests': {},
                 'observation': {'sample_interval_steps': 1, 'strict_start': True, 'record_contact_pairs': True}, 'objects': copy.deepcopy(objects)}
    moved = lambda name, distance=.01, direction=None: {'conditions': [{'kind': 'body_displacement', 'body_id': name, 'minimum_m': distance, **({'direction_world': direction} if direction else {})}]}
    coordinate = lambda name, key, minimum: {'conditions': [{'kind': 'joint_coordinate', 'joint_id': name, 'coordinate': key, 'relative_to_initial': True, 'minimum': minimum}]}
    events = {'a_moves': moved('tile_a'), 'b_moves': moved('tile_b'), 'weight_falls': moved('weight', .05, [0, 0, -1]),
              'drawer_opens': coordinate('drawer_slide', 'position_m', .05), 'book_moves': moved('book'),
              'door_opens': coordinate('door_hinge', 'angle_degrees', 30), 'spoon_tips': coordinate('spoon_hinge', 'angle_degrees', 5)}
    descriptions = [('hit_a', 'trigger_release', 'a_moves', ['ball', 'tile_a']), ('hit_b', 'a_moves', 'b_moves', ['tile_a', 'tile_b']),
                    ('release_weight', 'b_moves', 'weight_falls', ['tile_b', 'weight']), ('pull_drawer', 'weight_falls', 'drawer_opens', ['weight', 'rope', 'drawer']),
                    ('move_book', 'drawer_opens', 'book_moves', ['drawer', 'book']), ('open_door', 'book_moves', 'door_opens', ['book', 'door']),
                    ('tip_spoon', 'door_opens', 'spoon_tips', ['door', 'spoon']), ('receive_sugar', 'spoon_tips', 'terminal_entered', ['spoon', 'sugar'])]
    handoffs = []
    for name, start, end, path in descriptions:
        links = [{'kind': 'constraint', 'joint_id': j, 'maximum_anchor_error_m': .008} for j in ('rope_weight', 'rope_drawer')] if name == 'pull_drawer' else [{'kind': 'contact'}]
        handoffs.append({'id': name, 'source_event': start, 'target_event': end, 'body_path': path, 'links': links, 'maximum_lag_steps': 20})
    stages = []
    stage_specs = [('ball', 'trigger_release', 'a_moves'), ('tile_a', 'trigger_release', 'b_moves'), ('tile_b', 'a_moves', 'weight_falls'),
                   ('weight', 'b_moves', 'drawer_opens'), ('drawer', 'weight_falls', 'book_moves'), ('book', 'drawer_opens', 'door_opens'),
                   ('door', 'book_moves', 'spoon_tips'), ('spoon', 'door_opens', 'terminal_entered'), ('sugar', 'spoon_tips', 'terminal_entered')]
    for name, start, end in stage_specs:
        stages.append({'id': name+'_phase', 'purpose': 'synthetic transfer contract', 'start_event': start, 'end_event': end,
                       'roi_world': {'min': [-2]*3, 'max': [2]*3}, 'bodies': [{'id': name, 'minimum_speed_m_s': .01, 'minimum_angular_speed_degrees_s': 1}]})
    downstream = ['tile_a', 'tile_b', 'weight', 'rope', 'drawer', 'book', 'door', 'spoon', 'sugar']
    case = {'schema': p.SCHEMA, 'profile': 'pilot', 'require_strict_initial_state': True, 'trigger_id': 'ball', 'release_step': 5,
            'events': events, 'handoffs': handoffs,
            'tiles': {'ids': ['tile_a', 'tile_b'], 'class_label': 'domino_tile', 'up_axis_local': 'Z', 'initial_upright_max_degrees': 2,
                      'tipped_min_degrees': 60, 'minimum_tipped': 2, 'activation_events': {'tile_a': 'a_moves', 'tile_b': 'b_moves'}},
            'household_categories': {name: {'description': 'independently named synthetic '+name, 'body_ids': [name], 'class_labels': [name], 'activation_events': [event]} for name, event in [('book', 'book_moves'), ('door', 'door_opens'), ('spoon', 'spoon_tips')]},
            'minimum_household_categories': 3, 'quiet_limits': {n: {'maximum_motion_m': .003, 'maximum_rotation_degrees': 2} for n in downstream},
            'initial_hold_steps': 3, 'maximum_joint_anchor_error_m': .008, 'contact_window_tolerance_steps': 1, 'rope_body_ids': ['rope'],
            'terminal': {'body_id': 'sugar', 'receiver_id': 'cup', 'size_m': [.02]*3, 'interior_local': {'min': [-.1, -.1, 0], 'max': [.1, .1, .2]},
                         'hold_steps': 10, 'maximum_motion_m': .002, 'maximum_rotation_degrees': 2},
            'activity': {'stages': stages, 'limits': {'minimum_chain_duration_s': .4, 'minimum_net_effective_action_s': .1, 'minimum_motion_occupancy': .2, 'maximum_idle_s': .2}},
            'controls': {'no_trigger': {'downstream_body_ids': downstream, 'upstream_event_ids': []},
                         'broken_rope': {'joint_id': 'rope_drawer', 'cut_handoff_id': 'pull_drawer', 'downstream_body_ids': ['drawer', 'book', 'door', 'spoon', 'sugar'], 'upstream_event_ids': ['weight_falls']},
                         'locked_door': {'joint_id': 'door_hinge', 'door_body_id': 'door', 'locked_angle_degrees': 0, 'cut_event_id': 'door_opens', 'downstream_body_ids': ['door', 'spoon', 'sugar'], 'upstream_event_ids': ['book_moves']}},
            'required_controls': ['no_trigger', 'broken_rope', 'locked_door']}
    if mode == 'no_trigger':
        objects.pop('ball')
    elif mode == 'broken_rope':
        objects['rope_drawer']['joint']['enabled'] = False
    elif mode == 'locked_door':
        objects['door_hinge']['joint']['lower_limit'] = objects['door_hinge']['joint']['upper_limit'] = 0
    spec = {**copy.deepcopy(reference), 'objects': objects}
    active = set(downstream) | {'ball'}
    if mode == 'no_trigger':
        active = set()
    elif mode == 'broken_rope':
        active = {'ball', 'tile_a', 'tile_b', 'weight', 'rope'}
    elif mode == 'locked_door':
        active -= {'door', 'spoon', 'sugar'}
    def joint_values(step):
        values = {}
        for name, obj in objects.items():
            if obj.get('kind') != 'joint':
                continue
            cfg = obj['joint']
            value = {'type': cfg['type'], 'enabled': cfg.get('enabled', True), 'anchor0_world_m': [0, 0, 0], 'anchor1_world_m': [0, 0, 0], 'anchor_error_m': 0., 'drive_present': False}
            if cfg['type'] == 'prismatic':
                value['position_m'] = .08 if step >= 15 and 'drawer' in active else 0.
            elif cfg['type'] == 'revolute':
                value['angle_degrees'] = (90 if step >= 20 and 'door' in active else 0.) if name == 'door_hinge' else (10 if step >= 22 and 'spoon' in active else 0.)
            values[name] = value
        return values
    initial = {'physics_steps': 0, 'simulation_time_s': 0., 'absolute_physics_step': 3, 'absolute_simulation_time_s': .05,
               'positions': {p.m.path(n): copy.deepcopy(o['position']) for n, o in objects.items() if o.get('dynamic') and not o.get('spawn_step')},
               'orientations_wxyz': {p.m.path(n): [1, 0, 0, 0] for n, o in objects.items() if o.get('dynamic') and not o.get('spawn_step')},
               'joints': joint_values(0), 'followers': {}}
    for key in ('linear_velocities_m_s', 'angular_velocities_rad_s'):
        initial[key] = {name: [0, 0, 0] for name in initial['positions']}
    samples = []
    contact_steps = [(8, 'ball', 'tile_a'), (10, 'tile_a', 'tile_b'), (12, 'tile_b', 'weight'), (18, 'drawer', 'book'), (20, 'book', 'door'), (22, 'door', 'spoon'), (29, 'spoon', 'sugar'), (31, 'sugar', 'cup')]
    for step in range(1, 51):
        positions = {p.m.path(n): copy.deepcopy(o['position']) for n, o in objects.items() if o.get('dynamic') and o.get('spawn_step', 0) < step}
        rotations = {name: [1, 0, 0, 0] for name in positions}
        if 'ball' in active and step > 5:
            positions['/World/ball'][2] -= (step-5)*.02
        for name, start in [('tile_a', 8), ('tile_b', 10), ('drawer', 15), ('book', 18)]:
            if name in active and step >= start:
                positions[p.m.path(name)][0] += .08 if name == 'drawer' else .025
                if name.startswith('tile_'):
                    rotations[p.m.path(name)] = [math.sqrt(.5), 0, math.sqrt(.5), 0]
        for name in ('weight', 'rope'):
            if name in active and step >= 12:
                positions[p.m.path(name)][2] -= .1
        if 'door' in active and step >= 20:
            rotations['/World/door'] = [math.sqrt(.5), 0, math.sqrt(.5), 0]
        if 'spoon' in active and step >= 22:
            rotations['/World/spoon'] = [math.cos(math.pi/36), 0, math.sin(math.pi/36), 0]
        if 'sugar' in active and step >= 30:
            positions['/World/sugar'] = [1, 0, .1]
        contacts = []
        for stamp, a, b in contact_steps:
            if stamp == step and a in active and (b in active or b in ('door', 'cup')):
                contacts.append({'actor_paths': [p.m.path(a), p.m.path(b)], 'collider_paths': [p.m.path(a), p.m.path(b)], 'body_ids': [a, b], 'count': 1,
                                 'first_callback_absolute_physics_step': 3+step-1, 'last_callback_absolute_physics_step': 3+step-1, 'minimum_separation_m': 0.})
        samples.append({'physics_steps': step, 'simulation_time_s': step/60, 'absolute_physics_step': 3+step, 'absolute_simulation_time_s': .05+step/60,
                        'positions': positions, 'orientations_wxyz': rotations, 'linear_velocities_m_s': {n: [0, 0, 0] for n in positions},
                        'angular_velocities_rad_s': {n: [0, 0, 0] for n in positions}, 'joints': joint_values(step), 'contact_pairs': contacts, 'followers': {}})
    loaded = []
    for name, obj in objects.items():
        if obj.get('kind') == 'joint':
            cfg = obj['joint'];loaded.append({'path': p.m.path(name), 'type': 'Physics'+cfg['type'].title()+'Joint', 'enabled': cfg.get('enabled', True),
                                             'body0': [p.m.path(cfg['body0'])] if cfg.get('body0') else [], 'body1': [p.m.path(cfg['body1'])], 'drives': [], 'drive_attributes': []})
    reset = {'applied': True, 'phase': 'before_task_start', 'reset_count': 1, 'body_ids': [n for n, o in objects.items() if o.get('dynamic') and not o.get('spawn_step')],
             'body_paths': list(initial['positions']), 'authored_pose_readback_max_error_m': 0., 'authored_orientation_readback_max_error_degrees': 0., 'max_quaternion_error': 0.,
             'max_linear_speed_m_s': 0., 'max_angular_speed_rad_s': 0., 'setters_during_task': False, 'absolute_physics_step': 3, 'absolute_simulation_time_s': .05,
             'before_warmup_absolute_physics_step': 0, 'before_warmup_absolute_simulation_time_s': 0., 'after_warmup_absolute_physics_step': 3, 'after_warmup_absolute_simulation_time_s': .05}
    run = {'requested_physics_steps': 50, 'actual_physics_steps': 50, 'simulation_time_s': 50/60, 'seed': 42, 'observation_interval_steps': 1,
           'initial_observation': initial, 'initialization_reset': reset, 'run_zero_absolute_physics_step': 3, 'run_zero_absolute_simulation_time_s': .05,
           'initial_joint_states': initial['joints'], 'samples': samples, 'mechanism_configuration': {'joints': loaded, 'body_settings': {}, 'scene_enable_ccd': False},
           'spawn_events': [] if mode == 'no_trigger' else [{'id': 'ball', 'physics_step': 5}], 'contacts_truncated': False, 'contact_counts': {}, 'followers': {}}
    return run, spec, case, reference


def seal_fixture(root, run, spec, case, launcher=None):
    from simscene.evidence_integrity import seal
    for name, value in [('result.json', run), ('spec.json', spec), ('acceptance-case.json', case), ('asset-lock.json', {}), ('runtime-lock.json', {})]:
        (root/name).write_text(json.dumps(value))
    (root/'scene.usda').write_text('#usda 1.0\n')
    launcher = launcher or root/'python.sh'
    if not launcher.exists():
        launcher.write_text('synthetic test launcher, never executed\n')
    worker = root/'runtime/simscene/worker/isaac_run.py'
    worker.parent.mkdir(parents=True)
    worker.write_text('# synthetic locked test observer, never executed\n')
    sha = lambda filename: hashlib.sha256(filename.read_bytes()).hexdigest()
    lock = {'runtime_python': str(launcher), 'runtime_python_sha256': sha(launcher), 'queue_launcher_python': str(launcher), 'queue_launcher_python_sha256': sha(launcher),
            'runtime_version': 'synthetic', 'physics_device': 'cpu', 'physics_dt_s': 1/60, 'requested_physics_steps': run['requested_physics_steps'], 'seed': 42,
            'gpu_selection': {'simscene_gpu': '0', 'cuda_visible_devices': '0'}, 'continue_on_controller_error': False, 'archive_verified_objects': False,
            'worker_code_sha256': {'worker/isaac_run.py': sha(worker)}, 'acceptance_case_file': 'acceptance-case.json', 'acceptance_case_sha256': sha(root/'acceptance-case.json')}
    for name, key in [('spec.json', 'spec_sha256'), ('scene.usda', 'stage_sha256'), ('asset-lock.json', 'asset_lock_sha256'), ('runtime-lock.json', 'runtime_lock_sha256')]:
        lock[key] = sha(root/name)
    (root/'run-lock.json').write_text(json.dumps(lock))
    seal(root)


def formal_case():
    """Schema-only synthetic blueprint; no scenario coordinates or run."""
    _, _, case, _ = fixture()
    case['profile'] = 'P3'
    extra = ['extra_tile_'+str(i) for i in range(198)]
    previous_event, previous_body = 'a_moves', 'tile_a'
    case['handoffs'] = [h for h in case['handoffs'] if h['id'] != 'hit_b']
    for i, name in enumerate(extra):
        event = name+'_moves'
        case['events'][event] = {'conditions': [{'kind': 'body_displacement', 'body_id': name, 'minimum_m': .01}]}
        case['handoffs'].append({'id': 'extra_hit_'+str(i), 'source_event': previous_event, 'target_event': event, 'body_path': [previous_body, name], 'links': [{'kind': 'contact'}], 'maximum_lag_steps': 100})
        case['tiles']['activation_events'][name] = event
        case['quiet_limits'][name] = {'maximum_motion_m': .003, 'maximum_rotation_degrees': 2}
        previous_event, previous_body = event, name
    case['handoffs'].append({'id': 'final_extra_hit', 'source_event': previous_event, 'target_event': 'b_moves', 'body_path': [previous_body, 'tile_b'], 'links': [{'kind': 'contact'}], 'maximum_lag_steps': 100})
    case['tiles']['ids'].extend(extra)
    case['tiles']['minimum_tipped'] = 200
    case['tiles']['require_final_tilt'] = True
    case['controls']['no_trigger']['downstream_body_ids'].extend(extra)
    for name, label in [('bottle', 'bottle'), ('rollingpin', 'rolling_pin')]:
        event = name+'_moves'
        case['events'][event] = {'conditions': [{'kind': 'body_displacement', 'body_id': name, 'minimum_m': .01}]}
        case['quiet_limits'][name] = {'maximum_motion_m': .003, 'maximum_rotation_degrees': 2}
        case['household_categories'][name] = {'description': 'synthetic meaningful '+name, 'body_ids': [name], 'class_labels': [label], 'activation_events': [event]}
        case['controls']['no_trigger']['downstream_body_ids'].append(name)
        case['controls']['broken_rope']['downstream_body_ids'].append(name)
    case['household_categories']['drawer'] = {'description': 'synthetic drawer', 'body_ids': ['drawer'], 'class_labels': ['drawer'], 'activation_events': ['drawer_opens']}
    for name, start, end, a, b in [('bottle_edge', 'book_moves', 'bottle_moves', 'book', 'bottle'), ('pin_edge', 'bottle_moves', 'rollingpin_moves', 'bottle', 'rollingpin'), ('pin_door_edge', 'rollingpin_moves', 'door_opens', 'rollingpin', 'door')]:
        case['handoffs'].append({'id': name, 'source_event': start, 'target_event': end, 'body_path': [a, b], 'links': [{'kind': 'contact'}], 'maximum_lag_steps': 100})
    case['minimum_household_categories'] = 6
    case['terminal']['hold_steps'] = 120
    case['activity']['limits'] = {'minimum_chain_duration_s': 50, 'minimum_net_effective_action_s': 45, 'minimum_motion_occupancy': .85, 'maximum_idle_s': 2}
    return case


def support_fixture(mode='positive'):
    run, spec, case, reference = fixture(mode)
    condition = {'kind': 'box_leaves_support', 'body_id': 'sugar', 'support_id': 'spoon',
                 'support_region_local': {'min': [-.02, -.02, .04], 'max': [.02, .02, .08]},
                 'minimum_relative_travel_m': .02, 'clearance_m': .001}
    case['events']['sugar_leaves'] = {'conditions': [condition]}
    handoff = next(h for h in case['handoffs'] if h['id'] == 'receive_sugar')
    handoff['guard_events'] = ['sugar_leaves']
    for stage in case['activity']['stages']:
        if stage['id'] == 'spoon_phase':
            stage['end_event'] = 'sugar_leaves'
        if stage['id'] == 'sugar_phase':
            stage['start_event'] = 'sugar_leaves'
    run['samples'][0]['contact_pairs'].append({'actor_paths': ['/World/spoon', '/World/sugar'], 'collider_paths': ['/World/spoon', '/World/sugar'], 'body_ids': ['spoon', 'sugar'],
                                            'count': 1, 'first_callback_absolute_physics_step': 3, 'last_callback_absolute_physics_step': 3})
    return run, spec, case, reference


def wrapped_fixture(mode='positive'):
    """Combine independent synthetic P1 data with a longer network journal.

    This exercises full-run delegation; it is not a scene builder or Isaac
    evidence. No physical coordinate or production threshold is inferred.
    """
    from test_mechanism_check import fixture as rope_fixture, detach, loaded_configuration
    run, spec, case, reference = fixture(mode)
    rope_run, rope_spec, nested = rope_fixture()
    segments = nested['rope']['segment_ids']
    chain = nested['rope']['joint_ids']
    nested.update(trigger_id='ball', release_step=5, require_strict_initial_state=True)
    nested['joints']['drawer'] = 'drawer_slide'
    case['mechanism_cases'] = {'wrapped_cable': nested}
    case['rope_body_ids'] = segments[:]
    for document in (spec, reference):
        for name in ('rope', 'rope_weight', 'rope_drawer'):
            document['objects'].pop(name)
        for name, obj in rope_spec['objects'].items():
            if name != 'slide':
                document['objects'][name] = copy.deepcopy(obj)
        document['objects']['weight']['class_label'] = 'counterweight'
        document['objects']['drawer']['class_label'] = 'drawer'
    if mode == 'broken_rope':
        spec['objects'][chain[0]]['joint']['enabled'] = False
        detach(rope_run, rope_spec, nested)
    case['controls']['broken_rope']['joint_id'] = chain[0]
    case['controls']['no_trigger']['downstream_body_ids'].remove('rope')
    case['controls']['no_trigger']['downstream_body_ids'].extend(segments+['pulley'])
    case['quiet_limits'].pop('rope')
    for name in segments+['pulley']:
        case['quiet_limits'][name] = {'maximum_motion_m': .003, 'maximum_rotation_degrees': 2}
    cable = next(h for h in case['handoffs'] if h['id'] == 'pull_drawer')
    cable['body_path'] = ['weight', *reversed(segments), 'drawer']
    cable['links'] = [{'kind': 'constraint', 'joint_id': n, 'maximum_anchor_error_m': .008} for n in reversed(chain)]
    for handoff in case['handoffs']:
        handoff['maximum_lag_steps'] = 40
    # Freeze a longer pilot envelope before evaluating the synthetic run.
    case['activity']['limits']['maximum_idle_s'] = 1
    original = copy.deepcopy(run['samples'])
    samples = []
    replacements = {'weight', 'drawer', 'pulley', *segments}
    delayed = {'book', 'door', 'spoon', 'sugar'}
    for step in range(1, 71):
        current = copy.deepcopy(original[min(step, 50)-1])
        old = original[max(1, min(step-20, 50))-1]
        for name in delayed:
            for key in ('positions', 'orientations_wxyz'):
                current[key][p.m.path(name)] = copy.deepcopy(old[key][p.m.path(name)])
        for name in ('door_hinge', 'spoon_hinge'):
            current['joints'][name] = copy.deepcopy(old['joints'][name])
        rope_sample = rope_run['samples'][max(1, min(step-10, 36))-1]
        for key in ('positions', 'orientations_wxyz'):
            current[key].pop('/World/rope')
            for name in replacements:
                source = rope_sample if mode != 'no_trigger' else rope_run['samples'][0]
                current[key][p.m.path(name)] = copy.deepcopy(source[key][p.m.path(name)])
        for name in ('rope_weight', 'rope_drawer', 'drawer_slide'):
            current['joints'].pop(name)
        for name, value in rope_sample['joints'].items():
            source = value if mode != 'no_trigger' else rope_run['samples'][0]['joints'][name]
            current['joints']['drawer_slide' if name == 'slide' else name] = copy.deepcopy(source)
        current['contact_pairs'] = [v for v in current['contact_pairs'] if not set(v['body_ids']) & delayed and step <= 50]
        if step > 20:
            current['contact_pairs'] += [copy.deepcopy(v) for v in old['contact_pairs'] if set(v['body_ids']) & delayed]
        if mode != 'no_trigger' and 21 <= step <= 39:
            current['contact_pairs'].append({'actor_paths': ['/World/segment_3', '/World/pulley'], 'collider_paths': ['/World/segment_3', '/World/pulley'], 'body_ids': ['segment_3', 'pulley'], 'count': 1})
        for value in current['contact_pairs']:
            value['first_callback_absolute_physics_step'] = value['last_callback_absolute_physics_step'] = 3+step-1
        current.update(physics_steps=step, simulation_time_s=step/60, absolute_physics_step=3+step, absolute_simulation_time_s=.05+step/60)
        for key in ('linear_velocities_m_s', 'angular_velocities_rad_s'):
            current[key] = {name: [0, 0, 0] for name in current['positions']}
        samples.append(current)
    initial = copy.deepcopy(samples[0])
    initial.update(physics_steps=0, simulation_time_s=0., absolute_physics_step=3, absolute_simulation_time_s=.05)
    initial.pop('contact_pairs')
    run.update(samples=samples, requested_physics_steps=70, actual_physics_steps=70, simulation_time_s=70/60,
               initial_observation=initial, initial_joint_states=copy.deepcopy(initial['joints']), mechanism_configuration=loaded_configuration(spec),
               contact_counts=copy.deepcopy(rope_run['contact_counts']) if mode != 'no_trigger' else {})
    run['initialization_reset']['body_paths'] = list(initial['positions'])
    run['initialization_reset']['body_ids'] = [n for n, obj in spec['objects'].items() if obj.get('dynamic') and not obj.get('spawn_step')]
    return run, spec, case, reference


class PassiveNetworkTest(unittest.TestCase):
    def test_synthetic_network_has_named_tiles_actual_contacts_and_bounded_activity(self):
        run, spec, case, _ = fixture()
        report = p.evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertEqual(report['actual_tipped_tile_count'], 2)
        self.assertEqual(report['actual_transmitting_household_category_count'], 3)
        self.assertEqual(report['terminal']['first_whole_entry_step'], 30)
        self.assertEqual(report['terminal']['stable_confirmation_step'], 39)
        self.assertFalse(report['formal_stage_accepted'])

    def test_each_isolated_control_keeps_its_downstream_quiet(self):
        for mode in p.MODES[1:]:
            run, spec, case, reference = fixture(mode)
            report = p.evaluate(run, spec, case, mode, reference)
            self.assertTrue(report['passed'], (mode, report['checks']))

    def test_absent_or_false_final_flag_preserves_legacy_reports_and_controls(self):
        for mode in p.MODES:
            run, spec, case, reference = fixture(mode)
            args = {} if mode == 'positive' else {'mode': mode, 'reference_spec': reference}
            if mode == 'positive':
                # A tipped-then-recovered tile remains historical crossing
                # evidence when the legacy contract has no final obligation.
                run['samples'][-1]['orientations_wxyz']['/World/tile_a'] = [1, 0, 0, 0]
            original = p.evaluate(run, spec, case, **args)
            case['tiles']['require_final_tilt'] = False
            self.assertEqual(p.evaluate(run, spec, case, **args), original)
            self.assertTrue(original['passed'])
            self.assertNotIn('actual_final_tipped_tile_count', original)

    def test_final_flag_rejects_rebound_without_rewriting_crossing_count(self):
        run, spec, case, _ = fixture()
        case['tiles']['require_final_tilt'] = True
        self.assertTrue(p.evaluate(run, spec, case)['passed'])
        run['samples'][-1]['orientations_wxyz']['/World/tile_a'] = [math.cos(math.radians(10)), 0, math.sin(math.radians(10)), 0]
        case['tiles']['minimum_tipped'] = 1  # all declared finals still required
        report = p.evaluate(run, spec, case)
        self.assertEqual(report['actual_tipped_tile_count'], 2)
        self.assertEqual(report['actual_final_tipped_tile_count'], 1)
        self.assertTrue(report['checks']['actual_named_tile_count_met'])
        self.assertFalse(report['tiles']['tile_a']['final_tilt_passed'])
        self.assertFalse(report['checks']['every_named_tile_has_required_final_tilt'])
        self.assertFalse(report['passed'])

    def test_final_tilt_uses_last_complete_quaternion_and_frozen_cutoff(self):
        for degrees, expected in [(60, True), (59.99, False), (90, True)]:
            run, spec, case, _ = fixture()
            case['tiles']['require_final_tilt'] = True
            q = [math.sqrt(.75), 0, .5, 0] if degrees == 60 else [math.cos(math.radians(degrees/2)), 0, math.sin(math.radians(degrees/2)), 0]
            run['samples'][-1]['orientations_wxyz']['/World/tile_a'] = [-v for v in q]  # same orientation sign
            report = p.evaluate(run, spec, case)
            self.assertEqual(report['checks']['every_named_tile_has_required_final_tilt'], expected)
            self.assertEqual(report['final_tilt_requirement']['sample_physics_step'], 50)
        run, spec, case, _ = fixture()
        case['tiles']['require_final_tilt'] = True
        run['samples'][-1]['orientations_wxyz']['/World/tile_a'] = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
        self.assertFalse(p.evaluate(run, spec, case)['passed'])
        del run['samples'][-1]
        self.assertFalse(p.evaluate(run, spec, case)['passed'])

    def test_p3_requires_explicit_final_flag_and_every_declared_id(self):
        p.validate_case(formal_case())
        for change in ('missing', 'false', 'untyped', 'extra_id'):
            case = formal_case()
            if change == 'missing':case['tiles'].pop('require_final_tilt')
            elif change == 'false':case['tiles']['require_final_tilt'] = False
            elif change == 'untyped':case['tiles']['require_final_tilt'] = 1
            else:
                case['tiles']['ids'].append('unfulfilled_declared_tile')
                case['tiles']['activation_events']['unfulfilled_declared_tile'] = 'a_moves'
            with self.assertRaisesRegex(ValueError, 'final_tilt|every declared'):
                p.validate_case(case)

    def test_missing_first_interior_last_or_wrong_clock_is_rejected(self):
        for change in ('first', 'middle', 'last', 'clock', 'zero'):
            run, spec, case, _ = fixture()
            if change in ('first', 'middle', 'last'):
                del run['samples'][{'first': 0, 'middle': 20, 'last': -1}[change]]
            elif change == 'clock':
                run['samples'][8]['absolute_physics_step'] += 1
            else:
                del run['initial_observation']
            self.assertFalse(p.evaluate(run, spec, case)['passed'], change)

    def test_aggregate_first_contact_cannot_replace_missing_per_step_contact(self):
        run, spec, case, _ = fixture()
        run['samples'][9]['contact_pairs'] = []
        run['contact_counts'] = {'tile_a|/World/tile_b|': {'count': 50, 'first_physics_step': 1, 'last_physics_step': 50}}
        report = p.evaluate(run, spec, case)
        self.assertFalse(report['passed'])
        self.assertFalse(report['handoffs']['hit_b']['passed'])

    def test_unknown_actors_forged_colliders_and_callback_times_are_not_invented(self):
        for change in ('actor', 'collider', 'unknown', 'counter', 'count', 'nan'):
            run, spec, case, _ = fixture()
            contact = run['samples'][9]['contact_pairs'][0]
            if change == 'actor':
                contact['actor_paths'][0] = '/World/book'
            elif change == 'collider':
                contact['collider_paths'][0] = '/World/book/Shape'
            elif change == 'unknown':
                contact['body_ids'][0] = None
            elif change == 'counter':
                contact['first_callback_absolute_physics_step'] = contact['last_callback_absolute_physics_step'] = 99
            elif change == 'count':
                contact['count'] = 0
            else:
                contact['minimum_separation_m'] = float('nan')
            report = p.evaluate(run, spec, case)
            self.assertFalse(report['checks']['per_step_contact_provenance_valid'], change)

    def test_contact_before_source_motion_does_not_prove_the_handoff(self):
        run, spec, case, _ = fixture()
        contact = run['samples'][9]['contact_pairs'].pop()
        contact['first_callback_absolute_physics_step'] = contact['last_callback_absolute_physics_step'] = 8
        run['samples'][5]['contact_pairs'].append(contact)
        report = p.evaluate(run, spec, case)
        self.assertTrue(report['checks']['per_step_contact_provenance_valid'])
        self.assertFalse(report['handoffs']['hit_b']['passed'])

    def test_raw_callback_counter_is_preserved_as_a_boundary(self):
        run, spec, case, _ = fixture()
        report = p.evaluate(run, spec, case)
        witness = report['handoffs']['hit_a']['links'][0]['callback_records'][0]
        self.assertEqual(witness['observation_step'], 8)
        self.assertEqual(witness['observation_absolute_step'], 11)
        self.assertEqual(witness['first_callback_absolute_physics_step'], 10)

    def test_actual_tile_tilt_excludes_yaw_and_tipped_books(self):
        run, spec, case, _ = fixture()
        for sample in run['samples']:
            if sample['physics_steps'] >= 8:
                sample['orientations_wxyz']['/World/tile_a'] = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
            if sample['physics_steps'] >= 10:
                sample['orientations_wxyz']['/World/tile_b'] = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
                sample['orientations_wxyz']['/World/book'] = [math.sqrt(.5), 0, math.sqrt(.5), 0]
        report = p.evaluate(run, spec, case)
        self.assertEqual(report['actual_tipped_tile_count'], 0)
        self.assertFalse(report['checks']['actual_named_tile_count_met'])

    def test_books_cannot_be_reclassified_as_tiles_by_their_names(self):
        run, spec, case, _ = fixture()
        spec['objects']['tile_a']['class_label'] = 'book'
        with self.assertRaisesRegex(ValueError, 'tile must'):
            p.evaluate(run, spec, case)

    def test_signed_vertical_motion_is_measured_in_three_dimensions(self):
        run, spec, case, _ = fixture()
        self.assertEqual(p.evaluate(run, spec, case)['events']['weight_falls']['onset_step'], 12)
        for sample in run['samples'][11:]:
            sample['positions']['/World/weight'][2] = .5
            sample['positions']['/World/weight'][0] -= .1
        self.assertFalse(p.evaluate(run, spec, case)['passed'])

    def test_unloaded_or_disabled_constraint_is_not_a_transmission_witness(self):
        run, spec, case, _ = fixture()
        run['samples'][13]['joints']['rope_drawer']['anchor_error_m'] = .02
        report = p.evaluate(run, spec, case)
        self.assertFalse(report['handoffs']['pull_drawer']['passed'])
        self.assertFalse(report['passed'])

    def test_guard_order_is_measured_not_assumed_from_the_declared_graph(self):
        run, spec, case, _ = fixture()
        case['events']['weight_later'] = {'conditions': [{'kind': 'body_displacement', 'body_id': 'weight', 'direction_world': [0, 0, -1], 'minimum_m': .08}]}
        case['events']['drawer_early'] = {'conditions': [{'kind': 'joint_coordinate', 'joint_id': 'drawer_slide', 'coordinate': 'position_m', 'relative_to_initial': True, 'minimum': .01}]}
        handoff = next(h for h in case['handoffs'] if h['id'] == 'pull_drawer')
        handoff['guard_events'] = ['drawer_early', 'weight_later']
        report = p.evaluate(run, spec, case)
        self.assertEqual(report['handoffs']['pull_drawer']['guard_steps'], [15, 12])
        self.assertFalse(report['handoffs']['pull_drawer']['passed'])

    def test_household_categories_need_distinct_real_transmitting_roots(self):
        for change in ('duplicate', 'label_alias', 'wrong_event', 'visual_only'):
            run, spec, case, _ = fixture()
            if change == 'duplicate':
                case['household_categories']['second_book'] = copy.deepcopy(case['household_categories']['book'])
            elif change == 'label_alias':
                case['household_categories']['door']['class_labels'] = ['book']
            elif change == 'wrong_event':
                case['household_categories']['book']['activation_events'] = ['weight_falls']
            else:
                spec['objects']['book'].update(kind='asset', dynamic=False, asset_physics='visual_only')
            with self.assertRaises(ValueError):
                p.evaluate(run, spec, case)

    def test_body_id_alias_cannot_manufacture_an_extra_tile(self):
        run, spec, case, _ = fixture()
        spec['objects']['tile-a'] = copy.deepcopy(spec['objects']['tile_a'])
        with self.assertRaisesRegex(ValueError, 'alias'):
            p.evaluate(run, spec, case)

    def test_whole_sugar_corners_and_continued_containment_are_required(self):
        for location in ([1.095, 0, .1], [1, 0, -.005]):
            run, spec, case, _ = fixture()
            for sample in run['samples'][29:]:
                sample['positions']['/World/sugar'] = list(location)
            report = p.evaluate(run, spec, case)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['whole_sugar_received_and_kept_stable'])
        run, spec, case, _ = fixture()
        run['samples'][-1]['positions']['/World/sugar'][0] = 2
        self.assertFalse(p.evaluate(run, spec, case)['terminal']['contained_after_first_entry'])

    def test_moving_support_separation_and_phase_gates_use_original_observations(self):
        run, spec, case, _ = support_fixture()
        original = copy.deepcopy((run, spec, case))
        report = p.evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        self.assertEqual(report['events']['sugar_leaves']['onset_step'], 30)
        self.assertTrue(report['moving_support_separations']['sugar_leaves:0']['initial_support_passed'])
        self.assertTrue(report['activity']['network_spatial_event_gates_applied'])
        self.assertLessEqual(report['activity']['metrics']['net_effective_action_s'], report['activity']['base_helper_upper_bound_metrics']['net_effective_action_s'])
        self.assertEqual((run, spec, case), original)
        for mode in p.MODES[1:]:
            run, spec, case, reference = support_fixture(mode)
            self.assertTrue(p.evaluate(run, spec, case, mode, reference)['passed'], mode)

    def test_world_translation_and_carried_rotation_do_not_mean_sugar_left_support(self):
        run, spec, case, _ = support_fixture()
        condition = case['events']['sugar_leaves']['conditions'][0]
        sample = copy.deepcopy(run['initial_observation'])
        angle = math.radians(70)
        rotation = [math.cos(angle/2), 0, math.sin(angle/2), 0]
        sample['orientations_wxyz']['/World/spoon'] = rotation
        sample['orientations_wxyz']['/World/sugar'] = rotation
        sample['positions']['/World/spoon'][0] += .3
        offset = p.m.rotate(rotation, [0, 0, .06])
        sample['positions']['/World/sugar'] = [a+b for a, b in zip(sample['positions']['/World/spoon'], offset)]
        self.assertGreater(math.dist(sample['positions']['/World/sugar'], run['initial_observation']['positions']['/World/sugar']), .2)
        geometry = p.moving_support_geometry(condition, sample, run['initial_observation'], spec)
        self.assertLess(geometry['relative_travel_m'], 1e-12)
        self.assertFalse(geometry['whole_box_disjoint'])
        self.assertFalse(geometry['passed'])

    def test_support_separation_requires_all_corners_clearance_and_relative_travel(self):
        run, spec, case, _ = support_fixture()
        condition = case['events']['sugar_leaves']['conditions'][0]
        for offset, clearance, floor, expected in [(.025, .001, .02, False), (.0305, .001, .02, False), (.04, .001, .05, False), (.04, .001, .02, True)]:
            sample = copy.deepcopy(run['initial_observation'])
            sample['positions']['/World/sugar'][0] += offset
            changed = {**condition, 'minimum_relative_travel_m': floor, 'clearance_m': clearance}
            self.assertEqual(p.moving_support_geometry(changed, sample, run['initial_observation'], spec)['passed'], expected)

    def test_support_initial_contact_and_whole_initial_containment_are_required(self):
        for change in ('contact', 'bounds', 'unrelated_support', 'clearance', 'travel'):
            run, spec, case, _ = support_fixture()
            condition = case['events']['sugar_leaves']['conditions'][0]
            if change == 'contact':
                run['samples'][0]['contact_pairs'] = []
            elif change == 'bounds':
                condition['support_region_local']['max'][2] = .065
            elif change == 'unrelated_support':
                condition['support_id'] = 'door'
            else:
                condition['clearance_m' if change == 'clearance' else 'minimum_relative_travel_m'] = 0
            if change in ('unrelated_support', 'clearance', 'travel'):
                with self.assertRaises(ValueError):
                    p.evaluate(run, spec, case)
            else:
                report = p.evaluate(run, spec, case)
                self.assertFalse(report['passed'])
                self.assertFalse(report['checks']['moving_supports_initially_hold_box'])

    def test_early_support_loss_cannot_hide_behind_later_spoon_event(self):
        run, spec, case, _ = support_fixture()
        run['samples'][14]['positions']['/World/sugar'][0] += .05
        report = p.evaluate(run, spec, case)
        self.assertEqual(report['events']['sugar_leaves']['onset_step'], 15)
        self.assertFalse(report['handoffs']['receive_sugar']['passed'])
        self.assertFalse(report['passed'])

    def test_stability_excursion_cannot_hide_between_equal_first_and_last_pose(self):
        run, spec, case, _ = fixture()
        case['terminal']['hold_steps'] = 21
        run['samples'][39]['positions']['/World/sugar'][0] += .01
        self.assertFalse(p.evaluate(run, spec, case)['checks']['whole_sugar_received_and_kept_stable'])

    def test_parallel_motion_counts_once_and_residual_book_motion_is_excluded(self):
        run, spec, case, _ = fixture()
        original = p.evaluate(run, spec, case)['activity']['metrics']
        self.assertLessEqual(original['net_effective_action_s'], original['chain_duration_s'])
        for sample in run['samples'][20:]:
            sample['positions']['/World/book'][2] += .1*math.sin(sample['physics_steps'])
        current = p.evaluate(run, spec, case)['activity']['metrics']
        self.assertEqual(current, original)

    def test_signed_progress_excludes_vertical_jitter_and_backward_travel(self):
        for change in ('vertical', 'backward'):
            run, spec, case, _ = fixture()
            source = next(s for s in case['activity']['stages'] if s['id'] == 'book_phase')['bodies'][0]
            source.pop('minimum_angular_speed_degrees_s')
            source['direction_world'] = [1, 0, 0]
            for sample in run['samples'][18:20]:
                step = sample['physics_steps']
                sample['positions']['/World/book'][2] += .02*(step-18) if change == 'vertical' else 0
                sample['positions']['/World/book'][0] -= .004*(step-18) if change == 'backward' else 0
            report = p.evaluate(run, spec, case)['activity']
            flags = {s['physics_step']: s for s in report['per_step_motion_flags']}
            self.assertNotIn('book', flags[19]['body_ids'])
            self.assertLess(report['metrics']['net_effective_action_s'], report['base_3d_metrics']['net_effective_action_s'])
            details = next(s for s in flags[19]['linear_progress_details'] if s['body_id'] == 'book')
            self.assertFalse(details['linear_active'])
            self.assertLessEqual(details['signed_speed_m_s'], 0)
            self.assertIn('door', flags[20]['body_ids'])  # parallel valid source still counts once

    def test_direction_requires_unit_vector_and_its_own_linear_floor(self):
        for direction, floor in [([0, 2, 0], .01), ([1, 1, 0], .01), ([0, 0, 0], .01), ([1, 0, 0], None)]:
            run, spec, case, _ = fixture()
            source = case['activity']['stages'][0]['bodies'][0]
            source['direction_world'] = direction
            if floor is None:
                source.pop('minimum_speed_m_s')
            with self.assertRaisesRegex(ValueError, 'unit vector'):
                p.evaluate(run, spec, case)

    def test_embedded_wrapped_pulley_is_structural_and_original_full_run_is_unchanged(self):
        run, spec, case, _ = wrapped_fixture()
        original = copy.deepcopy((run, spec, case))
        binding = p.bind_case(p.validate_case(case), spec)
        self.assertEqual(binding['structural_components'], {'pulley'})
        self.assertNotIn('pulley', binding['path_bodies'])
        report = p.evaluate(run, spec, case)
        self.assertTrue(report['passed'], report['checks'])
        nested = report['mechanism_cases']['wrapped_cable']
        self.assertTrue(nested['report']['passed'], nested['report']['checks'])
        self.assertTrue(nested['per_step_pulley_contact_witnesses'])
        self.assertEqual((run, spec, case), original)

    def test_embedded_matching_cut_uses_detached_contract_and_other_controls_explicitly_stop(self):
        for mode in p.MODES[1:]:
            run, spec, case, reference = wrapped_fixture(mode)
            report = p.evaluate(run, spec, case, mode, reference)
            self.assertTrue(report['passed'], (mode, report['checks']))
            assertion = report['mechanism_cases']['wrapped_cable']
            if mode == 'broken_rope':
                self.assertEqual(assertion['report']['mode'], 'detached_drawer')
                self.assertTrue(assertion['report']['passed'])
            else:
                self.assertEqual(assertion['status'], 'skipped_stopping_control')
                self.assertFalse(assertion['required'])

    def test_embedded_case_cannot_hide_unwrapped_geometry_missing_callback_or_failed_anchor(self):
        for change in ('geometry', 'callback', 'anchor'):
            run, spec, case, _ = wrapped_fixture()
            if change == 'geometry':
                case['mechanism_cases']['wrapped_cable']['rope']['minimum_wrap_degrees'] = 170
            elif change == 'callback':
                for sample in run['samples']:
                    sample['contact_pairs'] = [v for v in sample['contact_pairs'] if 'pulley' not in v['body_ids']]
            else:
                run['samples'][30]['joints']['rope_joint_3']['anchor_error_m'] = .01
            report = p.evaluate(run, spec, case)
            self.assertFalse(report['passed'], change)
            self.assertFalse(report['checks']['embedded_wrapped_cable_actual_pulley_contact_during_pull'] if change == 'callback' else report['checks']['required_embedded_mechanisms_pass'])

    def test_embedded_cases_cannot_inflate_roles_activity_or_change_trigger_context(self):
        for change in ('extra_role', 'extra_joint', 'trigger', 'pulley_activity', 'unconnected', 'no_trigger_coverage'):
            run, spec, case, _ = wrapped_fixture()
            nested = case['mechanism_cases']['wrapped_cable']
            if change == 'extra_role':
                nested['roles']['decoration'] = 'book'
            elif change == 'extra_joint':
                nested['joints']['decoration'] = 'door_hinge'
            elif change == 'trigger':
                nested['trigger_id'] = 'weight';nested['release_step'] = 0
            elif change == 'pulley_activity':
                case['activity']['stages'][0]['bodies'][0]['id'] = 'pulley'
            elif change == 'unconnected':
                spec['objects']['decorative_pulley'] = copy.deepcopy(spec['objects']['pulley'])
            else:
                case['controls']['no_trigger']['downstream_body_ids'].remove('pulley')
            with self.assertRaises(ValueError, msg=change):
                p.bind_case(p.validate_case(case), spec)

    def test_embedded_suite_requires_matching_drawer_end_control_and_pins_nested_case_bytes(self):
        from simscene.evidence_integrity import seal
        for matching in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory);controls = {};positive = root/'positive'
                for mode in p.MODES:
                    path = root/mode;path.mkdir()
                    run, spec, case, reference = wrapped_fixture(mode)
                    if not matching:
                        case['controls']['broken_rope']['joint_id'] = 'rope_joint_1'
                        case['controls']['broken_rope']['downstream_body_ids'].append('segment_0')
                        if mode == 'broken_rope':
                            spec['objects']['rope_joint_0']['joint']['enabled'] = True
                            spec['objects']['rope_joint_1']['joint']['enabled'] = False
                            for sample in [run['initial_observation'], *run['samples']]:
                                sample['joints']['rope_joint_0'].update(enabled=True, anchor_error_m=0.)
                                sample['joints']['rope_joint_1'].update(enabled=False, anchor_error_m=.5)
                            run['initial_joint_states'] = copy.deepcopy(run['initial_observation']['joints'])
                            from test_mechanism_check import loaded_configuration
                            run['mechanism_configuration'] = loaded_configuration(spec)
                    seal_fixture(path, run, spec, case, None if mode == 'positive' else positive/'python.sh')
                    if mode != 'positive':
                        controls[mode] = path
                report = p.verify_suite(positive, controls)
                self.assertEqual(report['passed'], matching, report)
                self.assertEqual(report['embedded_mechanism_controls_complete'], matching)
                self.assertTrue(all(c['passed'] for c in report['controls'].values()))
                if matching:
                    # A separately sealed changed nested threshold still fails
                    # the same frozen-case requirement, even though both pass.
                    path = controls['broken_rope'];case_path = path/'acceptance-case.json'
                    changed = json.loads(case_path.read_text())
                    changed['mechanism_cases']['wrapped_cable']['thresholds']['weight_min_drop_m'] = .19
                    case_path.write_text(json.dumps(changed))
                    lock_path = path/'run-lock.json';lock = json.loads(lock_path.read_text())
                    lock['acceptance_case_sha256'] = hashlib.sha256(case_path.read_bytes()).hexdigest()
                    lock_path.write_text(json.dumps(lock));seal(path)
                    altered = p.verify_run(path, mode='broken_rope', reference_run=positive)
                    self.assertTrue(altered['checks']['required_embedded_mechanisms_pass'])
                    self.assertFalse(altered['same_frozen_case_as_reference'])
                    self.assertFalse(altered['passed'])

    def test_activity_cannot_extend_to_residual_motion_or_count_rope_jitter(self):
        for change in ('late_end', 'rope', 'confirmation'):
            run, spec, case, _ = fixture()
            stage = next(s for s in case['activity']['stages'] if s['id'] == 'book_phase')
            if change == 'late_end':
                stage['end_event'] = 'terminal_entered'
            elif change == 'rope':
                stage['bodies'][0]['id'] = 'rope'
            else:
                stage['end_time'] = 'confirmation'
            with self.assertRaises(ValueError):
                p.evaluate(run, spec, case)

    def test_roi_and_camera_motion_do_not_create_task_activity(self):
        run, spec, case, _ = fixture()
        for stage in case['activity']['stages']:
            stage['roi_world'] = {'min': [10]*3, 'max': [11]*3}
        for sample in run['samples']:
            sample['cameras'] = {'cinematic': {'position': [sample['physics_steps'], 0, 0]}}
        report = p.evaluate(run, spec, case)
        self.assertEqual(report['activity']['metrics']['net_effective_action_s'], 0)
        self.assertFalse(report['passed'])

    def test_no_after_or_time_gate_can_hide_premature_activation(self):
        for field, value in [('after_event', 'b_moves'), ('not_before_step', 20)]:
            run, spec, case, _ = fixture()
            case['events']['a_moves'][field] = value
            with self.assertRaisesRegex(ValueError, 'hide early'):
                p.evaluate(run, spec, case)

    def test_unknown_or_null_thresholds_are_rejected_before_a_formal_run(self):
        for change in ('unknown', 'null_body', 'null_joint'):
            _, _, case, _ = fixture()
            if change == 'unknown':
                case['automatically_release_cart'] = True
            elif change == 'null_body':
                case['events']['a_moves']['conditions'][0]['maximum_m'] = None
            else:
                case['events']['drawer_opens']['conditions'][0]['maximum'] = None
            with self.assertRaises(ValueError):
                p.validate_case(case)

    def test_quiet_tolerances_cannot_hide_a_task_activation_before_release(self):
        run, spec, case, _ = fixture()
        case['quiet_limits']['book']['maximum_motion_m'] = .02
        with self.assertRaisesRegex(ValueError, 'smaller than'):
            p.evaluate(run, spec, case)

    def test_every_control_rejects_additional_scene_edits(self):
        for mode in p.MODES[1:]:
            run, spec, case, reference = fixture(mode)
            spec['objects']['book']['mass_kg'] = .2
            report = p.evaluate(run, spec, case, mode, reference)
            self.assertFalse(report['checks']['only_frozen_isolated_scene_change'])
            self.assertFalse(report['passed'])

    def test_control_cannot_omit_upstream_motion_or_allow_downstream_z_drift(self):
        run, spec, case, reference = fixture('broken_rope')
        run['samples'][-1]['positions']['/World/drawer'][2] += .01
        self.assertFalse(p.evaluate(run, spec, case, 'broken_rope', reference)['checks']['control_downstream_remains_quiet'])
        run, spec, case, reference = fixture('broken_rope')
        for sample in run['samples']:
            sample['positions']['/World/weight'] = reference['objects']['weight']['position'][:]
        self.assertFalse(p.evaluate(run, spec, case, 'broken_rope', reference)['checks']['control_upstream_still_moves'])

    def test_control_quiet_coverage_and_door_initial_lock_are_not_optional(self):
        run, spec, case, reference = fixture('locked_door')
        case['controls']['locked_door']['locked_angle_degrees'] = 5
        with self.assertRaisesRegex(ValueError, 'initial angle'):
            p.evaluate(run, spec, case, 'locked_door', reference)
        run, spec, case, _ = fixture()
        case['controls']['broken_rope']['downstream_body_ids'].remove('sugar')
        with self.assertRaisesRegex(ValueError, 'omits required'):
            p.evaluate(run, spec, case)

    def test_stage_floors_cannot_be_lowered_by_declaring_a_p3_profile(self):
        case = formal_case()
        p.validate_case(case)
        for field, value in [('minimum_chain_duration_s', 49), ('minimum_net_effective_action_s', 44), ('minimum_motion_occupancy', .84), ('maximum_idle_s', 2.1)]:
            changed = copy.deepcopy(case)
            changed['activity']['limits'][field] = value
            with self.assertRaisesRegex(ValueError, 'P3 timing floor'):
                p.validate_case(changed)
        changed = copy.deepcopy(case)
        changed['tiles']['minimum_tipped'] = 199
        with self.assertRaisesRegex(ValueError, '200'):
            p.validate_case(changed)
        changed = copy.deepcopy(case)
        changed['minimum_household_categories'] = 5
        with self.assertRaisesRegex(ValueError, 'six'):
            p.validate_case(changed)

    def test_formal_terminal_stability_cannot_be_a_two_frame_pause(self):
        case = formal_case()
        for field, value in [('hold_steps', 119), ('maximum_motion_m', .003), ('maximum_rotation_degrees', 3)]:
            changed = copy.deepcopy(case)
            changed['terminal'][field] = value
            with self.assertRaisesRegex(ValueError, 'formal terminal'):
                p.validate_case(changed)

    def test_sealed_suite_requires_same_case_runtime_and_exact_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);positive = root/'positive';positive.mkdir()
            run, spec, case, _ = fixture()
            seal_fixture(positive, run, spec, case)
            controls = {}
            for mode in p.MODES[1:]:
                path = root/mode;path.mkdir()
                run, spec, case, _ = fixture(mode)
                seal_fixture(path, run, spec, case, positive/'python.sh')
                controls[mode] = path
            report = p.verify_suite(positive, controls)
            self.assertTrue(report['passed'], report)
            self.assertFalse(report['formal_stage_accepted'])
            missing = p.verify_suite(positive, {'no_trigger': controls['no_trigger']})
            self.assertFalse(missing['required_controls_complete'])
            self.assertFalse(missing['passed'])
            path = controls['broken_rope']/'run-lock.json'
            lock = json.loads(path.read_text());lock['physics_device'] = 'gpu';path.write_text(json.dumps(lock))
            mismatched = p.verify_run(controls['broken_rope'], mode='broken_rope', reference_run=positive)
            self.assertTrue(mismatched['checks']['only_frozen_isolated_scene_change'])
            self.assertFalse(mismatched['paired_runtime_configuration_matches'])
            self.assertFalse(mismatched['passed'])

    def test_hash_tampering_or_unsealed_runs_fail_before_telemetry_acceptance(self):
        for changed in ('spec.json', 'result.json', 'acceptance-case.json', 'evidence-lock.json'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run, spec, case, _ = fixture()
                seal_fixture(root, run, spec, case)
                if changed == 'evidence-lock.json':
                    (root/changed).unlink()
                    with self.assertRaisesRegex(ValueError, 'evidence-lock'):
                        p.verify_run(root)
                else:
                    with (root/changed).open('a') as stream:stream.write(' ')
                    self.assertFalse(p.verify_run(root)['passed'])

    def test_failed_positive_does_not_falsify_the_structural_control_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            positive, control = Path(directory)/'positive', Path(directory)/'control'
            positive.mkdir();control.mkdir()
            run, spec, case, _ = fixture()
            run['samples'][9]['contact_pairs'] = []
            seal_fixture(positive, run, spec, case)
            run, spec, case, _ = fixture('broken_rope')
            seal_fixture(control, run, spec, case, positive/'python.sh')
            report = p.verify_run(control, mode='broken_rope', reference_run=positive)
            self.assertFalse(report['reference_positive_passed'])
            self.assertTrue(report['checks']['only_frozen_isolated_scene_change'])
            self.assertFalse(report['passed'])

    def test_recorded_sdk_geometry_policy_must_match_without_rewriting_legacy_scope(self):
        from simscene.evidence_integrity import seal
        with tempfile.TemporaryDirectory() as directory:
            positive, control = Path(directory)/'positive', Path(directory)/'control'
            positive.mkdir();control.mkdir()
            policy = {'cylinder_setting_available': True, 'approximate_cylinders_with_convex_meshes': True, 'setting_path': '/synthetic/read-only-policy'}
            run, spec, case, _ = fixture()
            run['mechanism_configuration']['geometry_settings'] = policy
            seal_fixture(positive, run, spec, case)
            run, spec, case, _ = fixture('broken_rope')
            run['mechanism_configuration']['geometry_settings'] = copy.deepcopy(policy)
            seal_fixture(control, run, spec, case, positive/'python.sh')
            self.assertTrue(p.verify_run(control, mode='broken_rope', reference_run=positive)['passed'])
            raw = json.loads((control/'result.json').read_text())
            raw['mechanism_configuration']['geometry_settings']['approximate_cylinders_with_convex_meshes'] = False
            (control/'result.json').write_text(json.dumps(raw));seal(control)
            report = p.verify_run(control, mode='broken_rope', reference_run=positive)
            self.assertTrue(report['paired_runtime_configuration_matches'])
            self.assertFalse(report['paired_geometry_settings_match'])
            self.assertFalse(report['passed'])
            del raw['mechanism_configuration']['geometry_settings']
            (control/'result.json').write_text(json.dumps(raw));seal(control)
            self.assertFalse(p.verify_run(control, mode='broken_rope', reference_run=positive)['paired_geometry_settings_match'])


if __name__ == '__main__':
    unittest.main()
