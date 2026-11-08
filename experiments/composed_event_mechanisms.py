"""Narrow read-only composition of ce05 event pilots into an original network.

The complete, unmodified P1 result is retained. Only its direct global incoming
contact can be replaced by a frozen real local network edge. This is a distinct
composed assertion, never a statement that the original P1 pilot passed.
"""
import hashlib
import json
from pathlib import Path

from simscene.verification import mechanism as m, passive_network as p

SCHEMA = 'simscene.composed_event_mechanisms.v1'
KERNELS = {'mechanism': 'ce05b85cd11af946901f77249e6d16208434d5764056c5ba704a97beb4c9f4e8',
           'passive_network': '0ed9160f0225bcba3e621c2b22ce0a36720ca67203cb29330883abfd99a1adc1'}
BASE_CHECKS = frozenset('''all_dynamic_body_poses_complete all_dynamic_mass_kg_valid
all_joint_observations_passive all_mechanism_joint_coordinates_finite
all_roles_are_physical_bodies complete_run contacts_complete
enabled_joint_anchors_remain_bounded every_physics_step_present
initial_joint_observations_complete loaded_joint_inventory_matches_spec
loaded_passive_body_settings_match_spec loaded_scene_ccd_enabled_when_required
no_active_body_motion no_authored_joint_drives no_pending_or_archived_bodies
only_frozen_initial_release original_simulation_clock per_step_observation_requested
role_joints_match_physical_bodies spawn_events_match strict_initial_absolute_zero_declared
strict_initial_body_paths_are_unique strict_initial_every_task_absolute_boundary_consistent
strict_initial_every_task_joint_frame_complete strict_initial_every_task_tensor_state_complete
strict_initial_flags_are_boolean strict_initial_joint_frames_complete
strict_initial_joints_match_same_zero strict_initial_measured_state_matches_authored_zero_velocity
strict_initial_mode_enabled strict_initial_no_followers
strict_initial_paused_warmup_did_not_advance_after_restore strict_initial_relative_zero
strict_initial_reset_covers_all_initial_bodies strict_initial_reset_readback_errors_bounded
strict_initial_restore_matches_task_zero strict_initial_single_restore_before_task
strict_initial_snapshot_and_reset_present strict_initial_snapshot_matches_task_zero
strict_initial_tensor_maps_complete strict_initial_tensor_values_finite
strict_initial_warmup_boundary_recorded'''.split())
AGGREGATE = 'all_physical_handoff_contacts_witnessed'
PHYSICAL_CHECKS = {
    'spoon_sugar': frozenset('''actual_sugar_dimensions_match_frozen_case
all_physical_handoff_contacts_witnessed first_cup_contact_is_new_and_observed
initial_joint_coordinates_quiet initial_mechanism_is_quiet physical_events_in_required_order
stopper_follows_frozen_xyz_axis sufficient_initial_observation_window
sugar_initially_supported_and_inside_spoon_region sugar_remains_contained_after_stability
whole_sugar_received_and_stable'''.split()),
    'wheel_door_bridge': frozenset('''actual_wheel_paddle_reaches_latch
all_physical_handoff_contacts_witnessed door_is_bridge_before_physical_pin_release
door_remains_a_bridge_during_crossing downstream_initially_quiet
initial_pin_is_physically_restrained_by_actual_retainer latch_follows_frozen_xyz_axis
latch_initial_joint_coordinate_quiet pin_crosses_regions_in_order
sufficient_initial_observation_window wheel_latch_door_events_ordered'''.split())}
CONTACT_ROLES = {
    'spoon_sugar': {'trigger_to_lasttile': ('@trigger', 'lasttile'),
                    'lasttile_to_stopper': ('lasttile', 'stopper'),
                    'stopper_withdraws_spoon_support': ('stopper', 'spoon'),
                    'spoon_to_sugar': ('spoon', 'sugar')},
    'wheel_door_bridge': {'trigger_to_wheel': ('@trigger', 'wheel'),
                          'wheel_paddle_to_latch': ('wheel', 'latch'),
                          'latch_releases_door': ('latch', 'door'),
                          'door_reaches_seat': ('door', 'seat'),
                          'rollingpin_travels_on_bridge': ('rollingpin', 'door')}}
INCOMING = {'spoon_sugar': ('trigger_to_lasttile', 'lasttile', 'lasttile_activation'),
            'wheel_door_bridge': ('trigger_to_wheel', 'wheel', 'wheel_activation')}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def assert_kernel():
    require(sha(m.__file__) == KERNELS['mechanism'] and sha(p.__file__) == KERNELS['passive_network'], 'frozen composition kernels changed')


def validate_declarations(declarations, case):
    require(isinstance(declarations, dict) and declarations and all(isinstance(k, str) and k for k in declarations), 'freeze named composed definitions')
    kinds = []
    for value in declarations.values():
        require(isinstance(value, dict) and set(value) == {'mechanism_case', 'incoming_handoff_id', 'local_input_body_id'}, 'freeze exact composition fields')
        nested = value['mechanism_case']
        require(isinstance(nested, dict) and nested.get('mechanism') in INCOMING, 'only wheel and spoon event pilots compose')
        spoon = nested['mechanism'] == 'spoon_sugar'
        fields = {'schema', 'mechanism', 'trigger_id', 'release_step', 'roles', 'joints', 'axes', 'thresholds', 'require_strict_initial_state'}
        fields |= {'support_region_local', 'receiver'} if spoon else {'geometry', 'bridge_regions_world'}
        require(set(nested) == fields and nested.get('schema') == 'simscene.mechanism.v1', 'complete exact ce05 event definition required; no optional activity or unknown fields')
        require(set(nested['roles']) == ({'lasttile', 'stopper', 'spoon', 'sugar', 'cup'} if spoon else {'wheel', 'latch', 'door', 'seat', 'rollingpin', 'retainer'}), 'exact physical role inventory required')
        require(set(nested['joints']) == ({'stopper', 'spoon'} if spoon else {'wheel', 'latch', 'door'}), 'exact physical joint inventory required')
        require(set(nested['axes']) == ({'stopper_world', 'spoon_joint_sign'} if spoon else {'latch_world', 'rollingpin_world', 'wheel_joint_sign', 'door_joint_sign'}), 'exact physical axis inventory required')
        common = {'initial_hold_steps', 'initial_max_motion_m', 'initial_max_rotation_degrees', 'max_anchor_error_m', 'max_off_axis_m', 'contact_window_tolerance_steps'}
        thresholds = {'lasttile_activation_degrees', 'stopper_min_travel_m', 'stopper_initial_max_m', 'spoon_activation_degrees', 'spoon_initial_max_degrees', 'sugar_leave_min_distance_m', 'sugar_leave_clearance_m', 'terminal_hold_steps', 'terminal_max_motion_m', 'terminal_max_rotation_degrees'} if spoon else {'wheel_activation_degrees', 'latch_min_travel_m', 'latch_initial_max_m', 'door_activation_degrees', 'door_bridge_angle_degrees', 'door_bridge_angle_tolerance_degrees', 'rollingpin_release_travel_m', 'bridge_hold_steps', 'part_contact_tolerance_m', 'retainer_release_clearance_m'}
        require(set(nested['thresholds']) == common | thresholds, 'exact physical threshold inventory required')
        require(set(nested['receiver']) == {'interior_world', 'sugar_size_m'} if spoon else set(nested['geometry']) == {'wheel_paddle_part_index', 'retainer_part_index'}, 'exact geometric declaration required')
        m.validate_event_case(nested)
        require('activity' not in nested, 'local activity is forbidden; original global masks own time')
        require(nested.get('require_strict_initial_state') is True and case.get('require_strict_initial_state') is True, 'strict original t0 required')
        require(nested['trigger_id'] == case['trigger_id'] and nested['release_step'] == case['release_step'] and nested['release_step'] > 0, 'never rebind global trigger or release')
        require(all(isinstance(value[k], str) and value[k] for k in ('incoming_handoff_id', 'local_input_body_id')), 'freeze exact local edge and source body')
        require(value['local_input_body_id'] != case['trigger_id'], 'composition requires a distinct local incoming body')
        kinds.append(nested['mechanism'])
    require(len(kinds) == 2 and set(kinds) == set(INCOMING), 'exactly one composed wheel and one composed spoon required')
    require(len({v['incoming_handoff_id'] for v in declarations.values()}) == len(declarations), 'local edge cannot be reused')
    return True


def bind(spec, case, declarations):
    """Bind exact local edges; the caller must also run complete stock validation."""
    validate_declarations(declarations, case)
    definitions, edges = p.event_definitions(case), p._edges(case)
    event_bodies = {n: p._event_body_ids(v, spec) for n, v in definitions.items()}
    context = {}
    for name, value in declarations.items():
        nested = value['mechanism_case'];kind = nested['mechanism']
        _, role, _ = INCOMING[kind];target = nested['roles'][role];source = value['local_input_body_id']
        handoffs = [h for h in case['handoffs'] if h['id'] == value['incoming_handoff_id']]
        require(len(handoffs) == 1, 'composition must name one existing required contact edge')
        edge = handoffs[0]
        require(edge['body_path'] == [source, target] and edge['links'] == [{'kind': 'contact'}] and not edge.get('guard_events'), 'incoming composition is one exact two-body contact edge')
        require(event_bodies.get(edge['source_event']) == {source} and event_bodies.get(edge['target_event']) == {target}, 'local endpoint events must measure exact endpoint bodies')
        require(edge['source_event'] in p._reachable({'trigger_release'}, edges) and 'terminal_entered' in p._reachable({edge['target_event']}, edges), 'local edge must lie on global trigger-to-terminal DAG')
        require(source != target and source not in set(nested['roles'].values()), 'local input cannot alias a mechanism role')
        require(all(spec['objects'].get(n, {}).get('dynamic') is True and spec['objects'][n].get('collision') is True and not spec['objects'][n].get('spawn_step') for n in (source, target)), 'local endpoints must be initially present dynamic colliders')
        context[name] = {'handoff': edge, 'source_body_id': source, 'target_body_id': target,
                         'mechanism_case_sha256': canonical_sha(nested)}
    return context


def inspect_raw(raw, nested):
    """Fail closed on any changed ce05 report inventory or aggregator semantics."""
    kind = nested['mechanism'];checks = raw.get('checks', {});contacts = raw.get('contacts', {})
    expected = BASE_CHECKS | PHYSICAL_CHECKS[kind]
    inventory = set(checks) == expected and all(type(v) is bool for v in checks.values())
    contact_inventory = set(contacts) == set(CONTACT_ROLES[kind])
    if contact_inventory:
        for name, roles in CONTACT_ROLES[kind].items():
            bodies = [nested['trigger_id'] if role == '@trigger' else nested['roles'][role] for role in roles]
            contact_inventory = contact_inventory and contacts[name].get('body_ids') == bodies and type(contacts[name].get('passed')) is bool
    incoming = INCOMING[kind][0]
    return {'check_inventory_exact': inventory, 'contact_inventory_exact': bool(contact_inventory),
            'safe_strict_base_passed': inventory and raw.get('strict_initial_state', {}).get('passed') is True and all(checks[k] is True for k in BASE_CHECKS),
            'raw_passed_aggregator_exact': inventory and type(raw.get('passed')) is bool and raw['passed'] == all(checks.values()) and 'activity' not in raw,
            'raw_contact_aggregator_exact': contact_inventory and checks.get(AGGREGATE) == all(c['passed'] for c in contacts.values()),
            'all_unchanged_physical_checks_pass': inventory and all(checks[k] is True for k in expected-{AGGREGATE}),
            'every_nonincoming_raw_contact_passes': contact_inventory and all(v['passed'] is True for k, v in contacts.items() if k != incoming)}


def evaluate(run, spec, case, declarations, stock, dt, _journal=None):
    """Original full telemetry only; no rebasing, sample replacement or retiming."""
    assert_kernel()
    context = bind(spec, case, declarations)
    journal = _journal if _journal is not None else p.contact_journal(run, spec)
    result = {'schema': SCHEMA, 'passed': False, 'formal_house_accepted': False,
              'source_kernels_sha256': dict(KERNELS), 'network_case_sha256': canonical_sha(case),
              'checks': {'original_stock_passed': stock.get('passed') is True, 'original_contact_journal_valid': journal.get('passed') is True},
              'mechanisms': {}, 'scope': 'Composed local-input assertions only. Raw complete P1 results remain unchanged; no full P1 pilot success is inferred.'}
    zero = run.get('initial_observation', {}).get('absolute_physics_step')
    require(type(zero) is int and m.finite(dt) and dt > 0, 'original strict clock required')
    for name, value in declarations.items():
        nested = value['mechanism_case'];kind = nested['mechanism'];binding = context[name]
        # This exact original call owns safe execution and final raw passed.
        raw = m.evaluate_event_mechanism(run, spec, nested, dt)
        checks = inspect_raw(raw, nested)
        incoming, _, activation = INCOMING[kind]
        edge = binding['handoff'];source = stock.get('events', {}).get(edge['source_event'], {}).get('onset_step')
        target = stock.get('events', {}).get(edge['target_event'], {}).get('onset_step')
        active = raw.get('events', {}).get(activation, {}).get('onset_step')
        ordered = all(type(n) is int for n in (source, target, active)) and case['release_step'] < source <= min(target, active) and target-source <= edge['maximum_lag_steps']
        tolerance = min(case['contact_window_tolerance_steps'], nested['thresholds']['contact_window_tolerance_steps'])
        witness = p.contact_witness(journal, binding['source_body_id'], binding['target_body_id'], source if ordered else None, min(target, active) if ordered else None, zero, tolerance)
        checks['bound_global_handoff_passed'] = stock.get('handoffs', {}).get(edge['id'], {}).get('passed') is True
        checks['local_activation_ordered_in_global_window'] = ordered
        checks['local_incoming_original_callback_witnessed'] = witness['passed']
        # Keep summary endpoints as ce05 wrote them; separately require actual
        # original callbacks for each unchanged non-incoming physical contact.
        callbacks = {}
        if checks['contact_inventory_exact']:
            for key, contact in raw['contacts'].items():
                if key == incoming: continue
                a, b = contact['body_ids']
                callbacks[key] = p.contact_witness(journal, a, b, contact['window_start_step'], contact['window_end_step'], zero, nested['thresholds']['contact_window_tolerance_steps'])
        checks['every_nonincoming_original_callback_witnessed'] = set(callbacks) == set(CONTACT_ROLES[kind])-{incoming} and all(v['passed'] for v in callbacks.values())
        result['mechanisms'][name] = {'passed': all(checks.values()), 'checks': checks, 'raw_p1_report': raw,
             'raw_p1_pilot_passed': raw.get('passed') is True, 'replaced_contact_key': incoming,
             'binding': binding, 'local_incoming_witness': witness, 'nonincoming_callback_witnesses': callbacks,
             'global_source_step': source, 'global_target_step': target, 'raw_first_activation_step': active}
    result['passed'] = all(result['checks'].values()) and all(v['passed'] for v in result['mechanisms'].values())
    return result
