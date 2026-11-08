"""Generic CPU-only evidence counterexamples; no simulator/candidate data."""
import copy
import math
import unittest

from simscene.verification import structural_loads as s


def gravity_pad_fixture(withdraw=True):
    """Return an independent small full-clock pad/tray fixture for integrations."""
    spec = {'objects': {
        'pad': {'kind': 'box', 'dynamic': True, 'collision': True, 'size': [.1]*3,
                'position': [0, 0, .1], 'orientation_wxyz': [1, 0, 0, 0], 'mass_kg': .2},
        'tray': {'kind': 'compound', 'dynamic': True, 'position': [0, 0, 0],
                 'orientation_wxyz': [1, 0, 0, 0], 'mass_kg': 1.,
                 'parts': [{'kind': 'box', 'size': [.8, .4, .1]}]},
        'pad_slide': {'kind': 'joint', 'joint': {'type': 'prismatic', 'body0': None,
            'body1': 'pad', 'axis': 'Z', 'local_pos0': [0, 0, .1],
            'lower_limit': -.2, 'upper_limit': .2}}},
        'observation': {'sample_interval_steps': 1, 'strict_start': True, 'record_contact_pairs': True}}
    declarations = {'pad': {'kind': s.KIND, 'guide_joint_id': 'pad_slide', 'support_body_id': 'tray',
        'support_motion_event': 'tray_moves', 'pad_part_index': None, 'support_part_index': 0,
        'gravity_direction_world': [0, 0, -1], 'thresholds': {'seating_steps': 2,
            'contact_tolerance_m': .002, 'maximum_penetration_m': .001,
            'guide_limit_margin_m': .01, 'guide_frame_tolerance_m': .0001,
            'maximum_support_tilt_degrees': 2}}}
    quiet = {'pad': {'maximum_motion_m': .005, 'maximum_rotation_degrees': 2},
             'tray': {'maximum_motion_m': .003, 'maximum_rotation_degrees': 2}}
    def joint(position):
        return {'pad_slide': {'type': 'prismatic', 'enabled': True, 'drive_present': False,
            'position_m': position[2]-.1, 'anchor_error_m': math.hypot(*position[:2]),
            'anchor0_world_m': [0, 0, .1], 'anchor1_world_m': position[:]}}
    def observation(step, pad, tray):
        positions = {'/World/pad': pad[:], '/World/tray': tray[:]}
        return {'physics_steps': step, 'simulation_time_s': step/60,
            'absolute_physics_step': step+3, 'absolute_simulation_time_s': .05+step/60,
            'positions': positions, 'orientations_wxyz': {n: [1, 0, 0, 0] for n in positions},
            'linear_velocities_m_s': {n: [0, 0, 0] for n in positions},
            'angular_velocities_rad_s': {n: [0, 0, 0] for n in positions},
            'joints': joint(pad), 'followers': {}, 'contact_pairs': []}
    initial = observation(0, [0, 0, .1], [0, 0, 0])
    samples = []
    for step in range(1, 13):
        x = ({5: .1, 6: .2, 7: .35}.get(step, .5 if step >= 8 else 0.)) if withdraw else 0.
        z = ({9: .05, 10: 0.}.get(step, -.1 if step >= 11 else .1)) if withdraw else .1
        sample = observation(step, [0, 0, z], [x, 0, 0])
        if not withdraw or step < 8:
            sample['contact_pairs'] = [support_contact(step)]
        samples.append(sample)
    reset = {'applied': True, 'phase': 'before_task_start', 'reset_count': 1,
        'body_ids': ['pad', 'tray'], 'body_paths': ['/World/pad', '/World/tray'],
        'authored_pose_readback_max_error_m': 0., 'authored_orientation_readback_max_error_degrees': 0.,
        'max_quaternion_error': 0., 'max_linear_speed_m_s': 0., 'max_angular_speed_rad_s': 0.,
        'setters_during_task': False, 'absolute_physics_step': 3, 'absolute_simulation_time_s': .05,
        'before_warmup_absolute_physics_step': 0, 'before_warmup_absolute_simulation_time_s': 0.,
        'after_warmup_absolute_physics_step': 3, 'after_warmup_absolute_simulation_time_s': .05}
    mass = lambda value: {'mass_kg': value, 'center_of_mass_local_m': [0, 0, 0],
        'principal_axes_local_wxyz': [1, 0, 0, 0], 'inertia_at_com_in_prim_axes_kg_m2': [[.001, 0, 0], [0, .001, 0], [0, 0, .001]],
        'observed_at_physics_step': 0, 'source': 'PhysX tensor readback synthetic CPU fixture'}
    run = {'requested_physics_steps': 12, 'actual_physics_steps': 12, 'simulation_time_s': .2,
        'observation_interval_steps': 1, 'contacts_truncated': False, 'samples': samples,
        'initial_observation': initial, 'initial_joint_states': copy.deepcopy(initial['joints']),
        'initialization_reset': reset, 'run_zero_absolute_physics_step': 3,
        'run_zero_absolute_simulation_time_s': .05, 'followers': {},
        'mechanism_configuration': {'joints': [{'path': '/World/pad_slide', 'type': 'PhysicsPrismaticJoint',
            'enabled': True, 'body0': [], 'body1': ['/World/pad'], 'drives': [], 'drive_attributes': []}],
            'body_settings': {}, 'mass_properties_by_prim_path': {'/World/pad': mass(.2), '/World/tray': mass(1.)}}}
    events = {'tray_moves': {'onset_step': 5 if withdraw else None}}
    return {'spec': spec, 'declarations': declarations, 'path_bodies': {'tray'}, 'quiet_limits': quiet,
            'run': run, 'events': events, 'journal': journal_for(run), 'dt': 1/60}


def support_contact(step):
    return {'actor_paths': ['/World/pad', '/World/tray'],
        'collider_paths': ['/World/pad', '/World/tray/part_0/Shape'], 'body_ids': ['pad', 'tray'],
        'count': 1, 'first_callback_absolute_physics_step': step+2,
        'last_callback_absolute_physics_step': step+2, 'minimum_separation_m': 0.}


def journal_for(run):
    return {'passed': True, 'records': [{'observation_step': sample['physics_steps'],
        'observation_absolute_step': sample['absolute_physics_step'], **copy.deepcopy(record)}
        for sample in run['samples'] for record in sample['contact_pairs']]}


def bind_fixture(f):
    return s.bind(f['spec'], f['declarations'], f['path_bodies'], f['quiet_limits'])


def evaluate_fixture(f, refresh_journal=True):
    if refresh_journal:
        f['journal'] = journal_for(f['run'])
    return s.evaluate(f['run'], f['spec'], f['declarations'], bind_fixture(f), f['events'], f['journal'], f['dt'])


def move_pad(f, step, xyz):
    sample = f['run']['samples'][step-1]
    sample['positions']['/World/pad'] = xyz[:]
    state = sample['joints']['pad_slide']
    state['position_m'] = xyz[2]-.1
    state['anchor1_world_m'] = xyz[:]
    state['anchor_error_m'] = math.hypot(*xyz[:2])


class StructuralLoadsTests(unittest.TestCase):
    def test_real_supported_phase_and_geometric_withdrawal(self):
        f = gravity_pad_fixture()
        b = bind_fixture(f)
        self.assertEqual(b['body_ids'], ['pad'])
        self.assertAlmostEqual(b['loads']['pad']['required_full_overlap_margin_m'], .0082)
        r = evaluate_fixture(f)
        self.assertTrue(r['passed'], r)
        self.assertEqual(r['loads']['pad']['geometric_support_loss_step'], 8)
        self.assertEqual(r['loads']['pad']['certified_support_steps'], 5)
        self.assertFalse(r['normal_force_measured'])
        self.assertFalse(r['activity_or_category_credit'])
        self.assertFalse(r['formal_stage_accepted'])
        # The retired pad may reach its own gravity guide limit, without load credit.
        self.assertEqual(r['loads']['pad']['per_step_geometry'][-1]['guide_position_m_from_measured_pose'], -.2)

    def test_full_horizon_stationary_load_requires_original_callbacks(self):
        f = gravity_pad_fixture(False)
        r = evaluate_fixture(f)
        self.assertTrue(r['passed'], r)
        self.assertEqual(r['loads']['pad']['certified_support_steps'], 10)
        self.assertIsNone(r['loads']['pad']['geometric_support_loss_step'])

    def test_declaration_shape_and_numeric_rejections(self):
        edits = [lambda c: c.update(kind='static_weight'), lambda c: c.update(extra=True),
                 lambda c: c.update(gravity_direction_world=[False, 0, -1]),
                 lambda c: c.update(pad_part_index=0), lambda c: c.update(support_part_index=None),
                 lambda c: c['thresholds'].update(seating_steps=True),
                 lambda c: c['thresholds'].update(contact_tolerance_m=float('nan')),
                 lambda c: c['thresholds'].update(maximum_penetration_m=.003),
                 lambda c: c['thresholds'].update(guide_limit_margin_m=.0002),
                 lambda c: c['thresholds'].update(maximum_support_tilt_degrees=6)]
        for edit in edits:
            with self.subTest(edit=edit):
                f = gravity_pad_fixture(); edit(f['declarations']['pad'])
                with self.assertRaises(ValueError): bind_fixture(f)

    def test_static_active_spawned_mass_and_geometry_rejected(self):
        edits = [lambda o: o['pad'].update(dynamic=False), lambda o: o['pad'].update(collision=False),
                 lambda o: o['pad'].update(spawn_step=1), lambda o: o['pad'].update(kinematic=True),
                 lambda o: o['pad'].update(kinematic_enabled=True), lambda o: o['pad'].update(pose_follower={'body': 'tray'}),
                 lambda o: o['pad'].update(conveyor={'speed': 1}), lambda o: o['pad'].update(mass_kg=0),
                 lambda o: o['tray'].update(mass_kg=-1), lambda o: o['pad'].update(physics={'motor': 1}),
                 lambda o: o['tray'].update(physics={'surface_velocity': 1}),
                 lambda o: o['pad'].update(external_forces=[1, 0, 0]),
                 lambda o: o['pad'].update(kind='sphere')]
        for edit in edits:
            with self.subTest(edit=edit):
                f = gravity_pad_fixture(); edit(f['spec']['objects'])
                with self.assertRaises(ValueError): bind_fixture(f)
        for field in ('drivers', 'followers'):
            f = gravity_pad_fixture(); f['spec'][field] = {'x': True}
            with self.assertRaises(ValueError): bind_fixture(f)

    def test_pad_not_admitted_as_category_activity_or_graph_connector(self):
        f = gravity_pad_fixture(); f['path_bodies'].add('pad')
        with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(); f['path_bodies'].clear()
        with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(); del f['quiet_limits']['pad']
        with self.assertRaises(ValueError): bind_fixture(f)

    def test_wrong_axis_fixed_clamped_disabled_extra_joint_and_drives_rejected(self):
        edits = [lambda g: g.update(type='fixed'), lambda g: g.update(axis='X'),
                 lambda g: g.update(lower_limit=0, upper_limit=0), lambda g: g.update(enabled=False),
                 lambda g: g.update(body0='tray'), lambda g: g.update(drive=1),
                 lambda g: g.update(local_pos0=[.01, 0, .1]),
                 lambda g: g.update(local_rot1_wxyz=[math.cos(.01), math.sin(.01), 0, 0])]
        for edit in edits:
            with self.subTest(edit=edit):
                f = gravity_pad_fixture(); edit(f['spec']['objects']['pad_slide']['joint'])
                with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(); f['spec']['objects']['bypass'] = copy.deepcopy(f['spec']['objects']['pad_slide'])
        f['spec']['objects']['bypass']['joint']['enabled'] = False
        with self.assertRaises(ValueError): bind_fixture(f)

    def test_full_footprint_quiet_margin_and_no_initial_gap_shortcut(self):
        for position in ([.36, 0, .1], [.345, 0, .1], [0, 0, .11], [0, 0, .098]):
            with self.subTest(position=position):
                f = gravity_pad_fixture()
                f['spec']['objects']['pad']['position'] = position
                f['spec']['objects']['pad_slide']['joint']['local_pos0'] = position[:]
                with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(); f['declarations']['pad']['thresholds']['contact_tolerance_m'] = .03
        with self.assertRaises(ValueError): bind_fixture(f)

    def test_compound_one_real_box_only_and_primitive_index_convention(self):
        f = gravity_pad_fixture()
        pad = f['spec']['objects']['pad']; pad.update(kind='compound', parts=[{'kind': 'box', 'size': [.1]*3}]); del pad['size']
        f['declarations']['pad']['pad_part_index'] = 0
        for sample in f['run']['samples']:
            for record in sample['contact_pairs']: record['collider_paths'][0] = '/World/pad/part_0/Shape'
        self.assertTrue(evaluate_fixture(f)['passed'])
        pad['parts'].append({'kind': 'box', 'size': [.1]*3, 'collision': False})
        self.assertTrue(evaluate_fixture(f)['passed'])
        pad['parts'][1]['collision'] = True
        with self.assertRaises(ValueError): bind_fixture(f)

    def test_missing_callbacks_aggregate_or_other_collider_do_not_prove_load(self):
        for mutation in ('missing', 'none', 'wrong_part', 'future', 'zero', 'nan'):
            with self.subTest(mutation=mutation):
                f = gravity_pad_fixture(False); sample = f['run']['samples'][3]; r = sample['contact_pairs'][0]
                if mutation == 'missing': sample['contact_pairs'] = []
                elif mutation == 'none': r['collider_paths'][1] = None
                elif mutation == 'wrong_part': r['collider_paths'][1] = '/World/tray/part_1/Shape'
                elif mutation == 'future': r['first_callback_absolute_physics_step'] += 2
                elif mutation == 'zero': r['count'] = 0
                else: r['minimum_separation_m'] = float('nan')
                self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False); f['run']['samples'][3]['contact_pairs'] = []
        self.assertFalse(evaluate_fixture(f, False)['passed'])
        f = gravity_pad_fixture(False); f['journal']['records'].pop()
        self.assertFalse(evaluate_fixture(f, False)['passed'])

    def test_unrelated_task_static_and_second_pad_contacts_rejected(self):
        for other in ('task_actor', 'hidden_static_support', 'second_pad'):
            f = gravity_pad_fixture(False); r = support_contact(5)
            r.update(body_ids=['pad', other], actor_paths=['/World/pad', '/World/'+other],
                     collider_paths=['/World/pad', '/World/'+other])
            f['run']['samples'][4]['contact_pairs'].append(r)
            result = evaluate_fixture(f)
            self.assertFalse(result['passed'])
            self.assertFalse(result['loads']['pad']['checks']['no_unrelated_contacts_or_hidden_load_path'])

    def test_limit_carrying_weight_faked_position_and_frame_rejected(self):
        for field, value in [('position_m', .1), ('anchor0_world_m', [0, 0, 0]),
                             ('anchor1_world_m', [0, 0, .2]), ('anchor_error_m', .1), ('drive_present', True)]:
            f = gravity_pad_fixture(False); f['run']['samples'][3]['joints']['pad_slide'][field] = value
            self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False); move_pad(f, 4, [0, 0, -.1])
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False); f['run']['initial_observation']['joints']['pad_slide']['position_m'] = .1
        f['run']['initial_joint_states'] = copy.deepcopy(f['run']['initial_observation']['joints'])
        r = evaluate_fixture(f)
        self.assertFalse(r['passed']); self.assertFalse(r['loads']['pad']['checks']['same_t0_guide_frame_identity'])

    def test_loaded_quiet_gap_tilt_and_prismatic_rotation_rejected(self):
        f = gravity_pad_fixture(False); move_pad(f, 4, [0, 0, .107])
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False); move_pad(f, 4, [0, 0, .103])
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False); f['run']['samples'][3]['positions']['/World/tray'][2] = -.004
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False)
        f['run']['samples'][3]['orientations_wxyz']['/World/pad'] = [math.cos(.002), math.sin(.002), 0, 0]
        self.assertFalse(evaluate_fixture(f)['passed'])

    def test_premature_loss_missing_event_and_reentry_rejected(self):
        f = gravity_pad_fixture(); f['events']['tray_moves']['onset_step'] = None
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(); f['events']['tray_moves']['onset_step'] = 9
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(); f['events'] = {}
        self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(); f['run']['samples'][9]['positions']['/World/tray'][0] = 0
        self.assertFalse(evaluate_fixture(f)['passed'])
        for onset in (-1, 0, 99, True):
            f = gravity_pad_fixture(); f['events']['tray_moves']['onset_step'] = onset
            self.assertFalse(evaluate_fixture(f)['passed'])

    def test_partial_clock_missing_t0_maps_and_contacts_truncated_rejected(self):
        edits = [lambda r: r['samples'].pop(3), lambda r: r['samples'][3].update(physics_steps=5),
                 lambda r: r['samples'][3].update(absolute_physics_step=99),
                 lambda r: r['samples'][3].update(simulation_time_s=0.),
                 lambda r: r['initial_observation']['linear_velocities_m_s'].pop('/World/pad'),
                 lambda r: r['initialization_reset'].update(setters_during_task=True),
                 lambda r: r.update(contacts_truncated=True), lambda r: r['samples'][3].pop('contact_pairs')]
        for edit in edits:
            with self.subTest(edit=edit):
                f = gravity_pad_fixture(False); edit(f['run'])
                # Use the old journal for malformed missing contact lists.
                self.assertFalse(evaluate_fixture(f, False)['passed'])

    def test_loaded_joint_mass_com_inertia_and_kinematic_evidence_rejected(self):
        edits = [lambda c: c['joints'][0].update(drives=['angular']),
                 lambda c: c['joints'][0].update(body0=['/World/tray']),
                 lambda c: c['joints'].append(copy.deepcopy(c['joints'][0])),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad'].update(mass_kg=0),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad'].update(mass_kg=.3),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad'].update(center_of_mass_local_m=[.1, 0, 0]),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad'].update(observed_at_physics_step=99),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad'].update(source='guessed inertia'),
                 lambda c: c['mass_properties_by_prim_path']['/World/pad']['inertia_at_com_in_prim_axes_kg_m2'][2].__setitem__(2, -.001),
                 lambda c: c['mass_properties_by_prim_path'].pop('/World/tray'),
                 lambda c: c['body_settings'].update(pad={'disable_gravity': True}),
                 lambda c: c['body_settings'].update(pad={'kinematic_enabled': True})]
        for edit in edits:
            with self.subTest(edit=edit):
                f = gravity_pad_fixture(False); edit(f['run']['mechanism_configuration'])
                self.assertFalse(evaluate_fixture(f)['passed'])

    def test_changed_declarations_fail_bound_context_and_no_empty_certification(self):
        f = gravity_pad_fixture(False); binding = bind_fixture(f)
        f['declarations']['pad']['thresholds']['seating_steps'] = 3
        r = s.evaluate(f['run'], f['spec'], f['declarations'], binding, f['events'], f['journal'], f['dt'])
        self.assertFalse(r['passed'])
        f = gravity_pad_fixture(); f['declarations']['pad']['thresholds']['seating_steps'] = 6
        self.assertFalse(evaluate_fixture(f)['passed'])

    def test_footprint_clipping_rejects_rotated_aabb_overlap_shortcut(self):
        # Two thin perpendicular rectangles have overlapping AABBs near a corner,
        # but no projected polygon intersection. A vertex/AABB shortcut is wrong.
        q = [math.cos(math.pi/8), 0, 0, math.sin(math.pi/8)]
        pad = {'kind': 'box', 'size': [.2, .02, .02]}
        support = {'kind': 'box', 'size': [.2, .02, .02]}
        g = s._geometry(([.13, -.13, .02], q), ([0, 0, 0], q), pad, support, [0, 0, 0], [0, 0, -1])
        self.assertFalse(g['overlap'])

    def test_rotated_body_and_offset_part_transforms(self):
        f = gravity_pad_fixture(False)
        q = [math.cos(math.pi/8), 0, 0, math.sin(math.pi/8)]
        for body in ('pad', 'tray'): f['spec']['objects'][body]['orientation_wxyz'] = q[:]
        f['spec']['objects']['pad_slide']['joint']['local_rot0_wxyz'] = q[:]
        for sample in [f['run']['initial_observation'], *f['run']['samples']]:
            for body in ('pad', 'tray'): sample['orientations_wxyz']['/World/'+body] = q[:]
        self.assertTrue(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False)
        f['spec']['objects']['tray']['parts'][0]['position'] = [.1, .05, .02]
        position = [.1, .05, .12]
        f['spec']['objects']['pad']['position'] = position[:]
        f['spec']['objects']['pad_slide']['joint']['local_pos0'] = position[:]
        for sample in [f['run']['initial_observation'], *f['run']['samples']]:
            sample['positions']['/World/pad'] = position[:]
            sample['joints']['pad_slide'].update(position_m=0., anchor0_world_m=position[:], anchor1_world_m=position[:])
        f['run']['initial_joint_states'] = copy.deepcopy(f['run']['initial_observation']['joints'])
        self.assertTrue(evaluate_fixture(f)['passed'])

    def test_gravity_axis_sign_does_not_require_a_driver(self):
        f = gravity_pad_fixture(False)
        guide = f['spec']['objects']['pad_slide']['joint']
        guide['local_rot0_wxyz'] = guide['local_rot1_wxyz'] = [0, 1, 0, 0]
        self.assertTrue(evaluate_fixture(f)['passed'])
        for sample in f['run']['samples']:
            for record in sample['contact_pairs']:
                for key in ('actor_paths', 'collider_paths', 'body_ids'): record[key].reverse()
        self.assertTrue(evaluate_fixture(f)['passed'])

    def test_after_retirement_contacts_still_cannot_hide_another_load_path(self):
        f = gravity_pad_fixture(); record = support_contact(10)
        record.update(body_ids=['pad', 'floor'], actor_paths=['/World/pad', '/World/floor'],
                      collider_paths=['/World/pad', '/World/floor'])
        f['run']['samples'][9]['contact_pairs'].append(record)
        self.assertFalse(evaluate_fixture(f)['passed'])

    def test_selected_patch_name_boundary_and_reported_penetration(self):
        for collider in ('/World/tray/part_0/Shape_fake', '/World/tray', '/World/tray/part_00/Shape'):
            f = gravity_pad_fixture(False)
            f['run']['samples'][3]['contact_pairs'][0]['collider_paths'][1] = collider
            self.assertFalse(evaluate_fixture(f)['passed'])
        f = gravity_pad_fixture(False)
        f['run']['samples'][3]['contact_pairs'][0]['minimum_separation_m'] = -.002
        self.assertFalse(evaluate_fixture(f)['passed'])

    def test_metric_frame_alias_and_nonpositive_inertia_rejected(self):
        for world in ({'up_axis': 'Y'}, {'units': 'cm'}):
            f = gravity_pad_fixture(); f['spec']['world'] = world
            with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(); f['spec']['objects']['pad-alias'] = copy.deepcopy(f['spec']['objects']['pad'])
        f['spec']['objects']['pad_alias'] = copy.deepcopy(f['spec']['objects']['pad'])
        with self.assertRaises(ValueError): bind_fixture(f)
        f = gravity_pad_fixture(False)
        f['run']['mechanism_configuration']['mass_properties_by_prim_path']['/World/pad']['inertia_at_com_in_prim_axes_kg_m2'] = [[1e-200, 2e-200, 0], [2e-200, 1e-200, 0], [0, 0, 1e-200]]
        self.assertFalse(evaluate_fixture(f)['passed'])
        # Exact minors do not overflow/underflow into accepting the indefinite tensor.
        f = gravity_pad_fixture(False)
        f['run']['mechanism_configuration']['mass_properties_by_prim_path']['/World/pad']['inertia_at_com_in_prim_axes_kg_m2'] = [[1e200, 2e200, 0], [2e200, 1e200, 0], [0, 0, 1e200]]
        self.assertFalse(evaluate_fixture(f)['passed'])


if __name__ == '__main__':
    unittest.main()
