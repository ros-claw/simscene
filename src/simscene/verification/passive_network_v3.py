"""Explicit v3 D6 rope admission with retained passive-network numerics.

Public schemas: simscene.passive_network.v1/v2 and explicit v3 D6 ropes. See
docs/passive-network-verification.md for the contract and control methods.
This module never starts physics, edits a scene, releases a body or applies a
force. In-memory evaluate() checks observations; verify_run()/verify_suite()
also require immutable input/output locks and the identical frozen case.

The original passive_network.py and mechanism.py remain byte-identical. The
new mechanism_v2 admits a named D6 model while retaining numerical tests. No P1
mechanism case is silently rebound to a different trigger or timing origin.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from . import mechanism_v2 as m

SCHEMA = 'simscene.passive_network.v1'
SCHEMA_V2 = 'simscene.passive_network.v2'
SCHEMA_V3 = 'simscene.passive_network.v3'
SUPPORTED_SCHEMAS = (SCHEMA, SCHEMA_V2, SCHEMA_V3)
LEGACY_NUMERICAL_SOURCE_SHA256 = '0ed9160f0225bcba3e621c2b22ce0a36720ca67203cb29330883abfd99a1adc1'
MODES = ('positive', 'no_trigger', 'broken_rope', 'locked_door')
RESERVED_EVENTS = ('trigger_release', 'terminal_entered', 'terminal_stable')


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _names(value, what, allow_empty=False):
    _require(isinstance(value, list) and (bool(value) or allow_empty) and all(isinstance(n, str) and n for n in value) and len(set(value)) == len(value), 'invalid '+what)
    return value


def _finite_positive(value):
    return m.finite(value) and value > 0


def _edges(case):
    edges = set()
    for handoff in case['handoffs']:
        chain = [handoff['source_event'], *handoff.get('guard_events', []), handoff['target_event']]
        edges.update(zip(chain, chain[1:]))
        if len(handoff['body_path']) > 2:
            for link in handoff['links']:
                if link['kind'] == 'contact':
                    edges.add((link['source_event'], link['target_event']))
                    edges.add((handoff['source_event'], link['source_event']))
                    edges.add((link['target_event'], handoff['target_event']))
    edges.add(('terminal_entered', 'terminal_stable'))
    return {(a, b) for a, b in edges if a != b}


def _reachable(start, edges):
    reached = set(start)
    while True:
        more = reached | {b for a, b in edges if a in reached}
        if more == reached:
            return reached
        reached = more


def _event_body_ids(definition, spec):
    result = set()
    if definition.get('kind') == 'spawn':
        return {definition['body_id']}
    for condition in definition.get('conditions', []):
        if condition['kind'] in ('body_displacement', 'contained_box', 'box_leaves_support'):
            result.add(condition['body_id'])
        elif condition['kind'] == 'joint_coordinate':
            cfg = spec['objects'].get(condition['joint_id'], {}).get('joint', {})
            if cfg.get('body1'):
                result.add(cfg['body1'])
    return result


def event_definitions(case):
    """Derive terminal rules only from frozen geometry, never from a run."""
    terminal = case['terminal']
    condition = {'kind': 'contained_box', 'body_id': terminal['body_id'], 'receiver_id': terminal['receiver_id'],
                 'inner_min_m': terminal['interior_local']['min'], 'inner_max_m': terminal['interior_local']['max']}
    return {**copy.deepcopy(case['events']),
            'trigger_release': {'kind': 'spawn', 'body_id': case['trigger_id'], 'physics_step': case['release_step']},
            'terminal_entered': {'conditions': [condition]},
            'terminal_stable': {'conditions': [condition], 'hold_steps': terminal['hold_steps'],
                                'stability': {'body_id': terminal['body_id'], 'max_motion_m': terminal['maximum_motion_m'], 'max_rotation_degrees': terminal['maximum_rotation_degrees']}}}


def validate_case(case):
    _require(isinstance(case, dict) and case.get('schema') in SUPPORTED_SCHEMAS, 'expected one of '+', '.join(SUPPORTED_SCHEMAS))
    allowed = {'schema', 'profile', 'require_strict_initial_state', 'trigger_id', 'release_step', 'events', 'handoffs', 'tiles',
               'household_categories', 'minimum_household_categories', 'quiet_limits', 'initial_hold_steps', 'terminal', 'activity',
               'maximum_joint_anchor_error_m', 'contact_window_tolerance_steps', 'controls', 'required_controls', 'rope_body_ids', 'description', 'mechanism_cases'}
    if case['schema'] in (SCHEMA_V2,SCHEMA_V3):
        allowed.add('structural_loads')
    _require(not set(case)-allowed, 'unknown network case fields: '+', '.join(sorted(set(case)-allowed)))
    _require(case.get('profile') in ('pilot', 'P2', 'P3'), 'profile must be pilot, P2 or P3')
    _require(case.get('require_strict_initial_state') is True, 'network acceptance requires strict initial state')
    _require(isinstance(case.get('trigger_id'), str) and case['trigger_id'] and type(case.get('release_step')) is int and case['release_step'] >= 2, 'freeze one scheduled initial sphere and release_step >= 2')
    _require(type(case.get('initial_hold_steps')) is int and 2 <= case['initial_hold_steps'] <= case['release_step'], 'invalid initial_hold_steps')
    _require(_finite_positive(case.get('maximum_joint_anchor_error_m')), 'freeze maximum_joint_anchor_error_m')
    _require(type(case.get('contact_window_tolerance_steps')) is int and case['contact_window_tolerance_steps'] >= 0, 'freeze contact_window_tolerance_steps')
    definitions = case.get('events')
    _require(isinstance(definitions, dict) and definitions and not set(definitions) & set(RESERVED_EVENTS), 'events must be distinct from reserved trigger/terminal events')
    for name, definition in definitions.items():
        _require(isinstance(name, str) and name and isinstance(definition, dict), 'invalid event definition')
        _require(not set(definition)-{'conditions', 'hold_steps', 'stability'}, 'events cannot hide early motion behind a time or after-event gate')
        _require(type(definition.get('hold_steps', 1)) is int and definition.get('hold_steps', 1) >= 1, 'invalid event hold_steps')
        conditions = definition.get('conditions')
        _require(isinstance(conditions, list) and conditions, 'event requires measured motion conditions')
        for condition in conditions:
            _require(isinstance(condition, dict), 'invalid event condition')
            if condition.get('kind') == 'body_displacement':
                _require(not set(condition)-{'kind', 'body_id', 'direction_world', 'minimum_m', 'maximum_m'}, 'unsupported body condition fields')
                _require(isinstance(condition.get('body_id'), str), 'body event requires body_id')
                direction = condition.get('direction_world')
                _require(direction is None or m.unit(direction), 'direction_world must be normalized XYZ')
                minimum, maximum = condition.get('minimum_m'), condition.get('maximum_m')
                _require((minimum is not None and _finite_positive(minimum)) or (direction is not None and maximum is not None and m.finite(maximum) and maximum < 0), 'body event must require nonzero displacement')
                _require(all(m.finite(condition[k]) for k in ('minimum_m', 'maximum_m') if k in condition), 'nonfinite or null displacement threshold')
                _require(minimum is None or maximum is None or minimum <= maximum, 'unordered displacement bounds')
            elif condition.get('kind') == 'joint_coordinate':
                _require(not set(condition)-{'kind', 'joint_id', 'coordinate', 'relative_to_initial', 'minimum', 'maximum'}, 'unsupported joint condition fields')
                _require(isinstance(condition.get('joint_id'), str) and condition.get('coordinate') in ('position_m', 'angle_degrees') and condition.get('relative_to_initial') is True, 'joint event requires a signed coordinate relative to t0')
                minimum, maximum = condition.get('minimum'), condition.get('maximum')
                _require((minimum is not None and _finite_positive(minimum)) or (maximum is not None and m.finite(maximum) and maximum < 0), 'joint event must require signed nonzero travel')
                _require(all(m.finite(condition[k]) for k in ('minimum', 'maximum') if k in condition), 'nonfinite or null joint threshold')
                _require(minimum is None or maximum is None or minimum <= maximum, 'unordered joint bounds')
            elif condition.get('kind') == 'box_leaves_support':
                _require(set(condition) == {'kind', 'body_id', 'support_id', 'support_region_local', 'minimum_relative_travel_m', 'clearance_m'}, 'freeze complete moving-support separation geometry')
                _require(isinstance(condition['body_id'], str) and isinstance(condition['support_id'], str) and condition['body_id'] != condition['support_id'] and m.valid_bounds(condition['support_region_local']), 'invalid moving-support body or local region')
                _require(_finite_positive(condition['minimum_relative_travel_m']) and _finite_positive(condition['clearance_m']), 'freeze positive relative travel and separation clearance')
            else:
                raise ValueError('unknown motion condition; contacts never substitute for an activation')
    tiles = case.get('tiles', {})
    ids = _names(tiles.get('ids'), 'named tile IDs')
    tile_fields = {'ids', 'class_label', 'up_axis_local', 'initial_upright_max_degrees', 'tipped_min_degrees', 'minimum_tipped', 'activation_events'}
    _require(tile_fields <= set(tiles) <= tile_fields | {'require_final_tilt'}, 'invalid tile counting contract')
    _require(type(tiles.get('require_final_tilt', False)) is bool, 'require_final_tilt must be a boolean')
    _require(isinstance(tiles['class_label'], str) and tiles['class_label'] and tiles['up_axis_local'] in ('X', 'Y', 'Z'), 'freeze tile label and actual long axis')
    _require(_finite_positive(tiles['initial_upright_max_degrees']) and _finite_positive(tiles['tipped_min_degrees']) and tiles['initial_upright_max_degrees'] < tiles['tipped_min_degrees'] <= 180, 'invalid tile tilt thresholds')
    _require(type(tiles['minimum_tipped']) is int and 1 <= tiles['minimum_tipped'] <= len(ids), 'invalid minimum actual tipped count')
    _require(isinstance(tiles['activation_events'], dict) and set(tiles['activation_events']) == set(ids) and all(isinstance(n, str) and n in definitions for n in tiles['activation_events'].values()), 'every tile needs its own named motion event')
    if case['profile'] in ('P2', 'P3'):
        _require(tiles['tipped_min_degrees'] >= 60, 'formal stages require at least 60 degrees of actual tile tilt')
    if case['profile'] == 'P2':
        _require(tiles['minimum_tipped'] >= 50, 'P2 requires at least 50 actually tipped named tiles')
    if case['profile'] == 'P3':
        _require(tiles['minimum_tipped'] >= 200, 'P3 requires at least 200 actually tipped named tiles')
        _require(tiles.get('require_final_tilt') is True, 'P3 requires explicit require_final_tilt=true')
        _require(tiles['minimum_tipped'] == len(ids), 'P3 requires every declared tile ID, not a smaller minimum subset')
    categories = case.get('household_categories')
    _require(isinstance(categories, dict), 'household_categories must be a mapping')
    seen_bodies, seen_labels = set(), set()
    for name, category in categories.items():
        _require(isinstance(name, str) and name and isinstance(category, dict) and set(category) == {'description', 'body_ids', 'class_labels', 'activation_events'}, 'invalid household category')
        _require(isinstance(category['description'], str) and category['description'], 'household identity requires a meaningful description')
        body_ids = set(_names(category['body_ids'], 'household body IDs'))
        labels = set(_names(category['class_labels'], 'household class labels'))
        _names(category['activation_events'], 'household activation events')
        _require(not body_ids & (seen_bodies | set(ids) | {case['trigger_id']}), 'a body cannot count as multiple categories, trigger or tile')
        _require(not labels & seen_labels and tiles['class_label'] not in labels, 'semantic class labels cannot be renamed to inflate category count')
        _require(all(event in definitions for event in category['activation_events']), 'unknown household activation event')
        seen_bodies |= body_ids
        seen_labels |= labels
    minimum = case.get('minimum_household_categories')
    _require(type(minimum) is int and 0 <= minimum <= len(categories), 'invalid minimum_household_categories')
    _require(case['profile'] != 'P3' or minimum >= 6, 'P3 requires six meaningful household categories')
    quiet = case.get('quiet_limits')
    _require(isinstance(quiet, dict) and quiet, 'freeze body-specific quiet limits')
    for name, limits in quiet.items():
        _require(isinstance(name, str) and isinstance(limits, dict) and set(limits) == {'maximum_motion_m', 'maximum_rotation_degrees'} and all(_finite_positive(v) for v in limits.values()), 'invalid quiet body limits')
    terminal = case.get('terminal', {})
    _require(isinstance(terminal, dict) and set(terminal) == {'body_id', 'receiver_id', 'size_m', 'interior_local', 'hold_steps', 'maximum_motion_m', 'maximum_rotation_degrees'}, 'invalid terminal sugar contract')
    _require(isinstance(terminal['body_id'], str) and isinstance(terminal['receiver_id'], str) and terminal['body_id'] != terminal['receiver_id'] and m.vector(terminal['size_m']) and min(terminal['size_m']) > 0 and m.valid_bounds(terminal['interior_local']), 'freeze actual sugar dimensions and receiver interior')
    _require(type(terminal['hold_steps']) is int and terminal['hold_steps'] >= 2 and _finite_positive(terminal['maximum_motion_m']) and _finite_positive(terminal['maximum_rotation_degrees']), 'invalid terminal stability limits')
    if case['profile'] in ('P2', 'P3'):
        _require(terminal['hold_steps'] >= 120 and terminal['maximum_motion_m'] <= .002 and terminal['maximum_rotation_degrees'] <= 2, 'formal terminal stability requires 120 steps, <=2mm motion and <=2 degrees rotation')
    _require(not seen_bodies & {terminal['body_id'], terminal['receiver_id']}, 'terminal sugar/cup cannot inflate transmitting household categories')
    handoffs = case.get('handoffs')
    _require(isinstance(handoffs, list) and handoffs and all(isinstance(h, dict) and isinstance(h.get('id'), str) and h['id'] for h in handoffs), 'freeze named physical handoffs')
    _require(len({h['id'] for h in handoffs}) == len(handoffs), 'freeze distinct physical handoffs')
    names = set(definitions) | set(RESERVED_EVENTS)
    for handoff in handoffs:
        _require(not set(handoff)-{'id', 'source_event', 'target_event', 'body_path', 'links', 'guard_events', 'maximum_lag_steps'}, 'unsupported handoff fields')
        _require(all(handoff.get(k) in names for k in ('source_event', 'target_event')) and handoff['source_event'] != handoff['target_event'], 'invalid handoff events')
        path = _names(handoff.get('body_path'), 'physical body path')
        _require(len(path) >= 2 and isinstance(handoff.get('links'), list) and len(handoff['links']) == len(path)-1, 'every path hop needs physical evidence')
        _require(type(handoff.get('maximum_lag_steps')) is int and handoff['maximum_lag_steps'] >= 0, 'freeze maximum handoff lag')
        guards = _names(handoff.get('guard_events', []), 'guard events', True)
        _require(all(n in names for n in guards), 'unknown guard event')
        for link in handoff['links']:
            _require(isinstance(link, dict) and link.get('kind') in ('contact', 'constraint'), 'unknown physical path hop')
            if link['kind'] == 'constraint':
                _require(set(link) == {'kind', 'joint_id', 'maximum_anchor_error_m'} and isinstance(link['joint_id'], str) and _finite_positive(link['maximum_anchor_error_m']) and link['maximum_anchor_error_m'] <= case['maximum_joint_anchor_error_m'], 'invalid constraint witness')
            else:
                allowed_link = {'kind'} if len(path) == 2 else {'kind', 'source_event', 'target_event'}
                _require(set(link) == allowed_link and (len(path) == 2 or link['source_event'] in names and link['target_event'] in names), 'intermediate contact hops need their own body activation events')
    edges = _edges(case)
    _require(_reachable({'trigger_release'}, edges) == names, 'every task event must be causally reachable from the trigger')
    pending = set(names)
    while pending:
        roots = {n for n in pending if not any(b == n and a in pending for a, b in edges)}
        _require(bool(roots), 'cyclic event handoffs cannot establish an ordered chain')
        pending -= roots
    activity = case.get('activity', {})
    _require(set(activity) == {'stages', 'limits'}, 'activity reuses the central event table and fixed release-to-entry window')
    limits = activity['limits']
    _require(set(limits) == {'minimum_chain_duration_s', 'minimum_net_effective_action_s', 'minimum_motion_occupancy', 'maximum_idle_s'} and all(m.finite(v) for v in limits.values()), 'freeze all activity limits')
    _require(limits['minimum_chain_duration_s'] >= 0 and limits['minimum_net_effective_action_s'] >= 0 and 0 <= limits['minimum_motion_occupancy'] <= 1 and limits['maximum_idle_s'] >= 0, 'invalid activity limits')
    if case['profile'] == 'P3':
        _require(limits['minimum_chain_duration_s'] >= 50 and limits['minimum_net_effective_action_s'] >= 45 and limits['minimum_motion_occupancy'] >= .85 and limits['maximum_idle_s'] <= 2, 'P3 timing floor is 50s span / 45s action / .85 occupancy / 2s maximum idle')
    if case['profile'] == 'P2':
        _require(limits['minimum_chain_duration_s'] >= 20 and limits['minimum_net_effective_action_s'] >= 20, 'P2 requires at least 20 seconds of span and measured task action')
    _require(isinstance(activity['stages'], list) and activity['stages'], 'freeze task stages and activity ROIs')
    _names(case.get('rope_body_ids', []), 'rope body IDs', True)
    controls = case.get('controls', {})
    _require(isinstance(controls, dict) and not set(controls)-set(MODES[1:]), 'unknown control mode')
    required = _names(case.get('required_controls', []), 'required controls', True)
    _require(set(required) <= set(controls), 'required control definitions missing')
    _require(case['profile'] != 'P3' or set(required) == set(MODES[1:]), 'P3 requires no-trigger, broken-rope and locked-door controls')
    _require(case['profile'] != 'P2' or 'no_trigger' in required and (not case.get('rope_body_ids') or 'broken_rope' in required), 'P2 requires its no-trigger and applicable broken-rope controls')
    for mode, control in controls.items():
        common = {'downstream_body_ids', 'upstream_event_ids'}
        extra = set() if mode == 'no_trigger' else {'joint_id', 'cut_handoff_id'} if mode == 'broken_rope' else {'joint_id', 'door_body_id', 'locked_angle_degrees', 'cut_event_id'}
        _require(isinstance(control, dict) and set(control) == common | extra, 'invalid isolated '+mode+' definition')
        _names(control['downstream_body_ids'], 'control downstream bodies')
        _names(control['upstream_event_ids'], 'control upstream events', mode == 'no_trigger')
        _require(all(e in names and e not in RESERVED_EVENTS for e in control['upstream_event_ids']), 'upstream controls require measured motion, not spawn alone')
        _require(all(n in quiet for n in control['downstream_body_ids']), 'control downstream bodies require explicit quiet limits')
        if mode == 'broken_rope':
            _require(bool(case.get('rope_body_ids')) and any(h['id'] == control['cut_handoff_id'] for h in handoffs), 'broken rope must cut a named physical constraint handoff')
        elif mode == 'locked_door':
            _require(control['cut_event_id'] in definitions and m.finite(control['locked_angle_degrees']), 'locked door needs its signed initial angle and cut event')
    mechanism_cases = case.get('mechanism_cases', {})
    _require(isinstance(mechanism_cases, dict), 'mechanism_cases must map names to complete frozen mechanism cases')
    for name, nested in mechanism_cases.items():
        _require(isinstance(name, str) and name and isinstance(nested, dict), 'invalid embedded mechanism name or case')
        m.validate_case(nested)
        _require(nested['trigger_id'] == case['trigger_id'] and nested['release_step'] == case['release_step'], 'embedded mechanism must preserve the network trigger and timing origin; no rebinding is performed')
        kind = nested['mechanism']
        wrapped = kind == 'rope_drawer' and nested['rope_model'] == 'segmented_over_free_pulley'
        role_keys = {'weight', 'drawer'} | ({'pulley'} if wrapped else set()) if kind == 'rope_drawer' else {'lasttile', 'stopper', 'spoon', 'sugar', 'cup'} if kind == 'spoon_sugar' else {'wheel', 'latch', 'door', 'seat', 'rollingpin', 'retainer'}
        joint_keys = {'drawer', 'drawer_end'} | ({'pulley'} if wrapped else set()) if kind == 'rope_drawer' else {'stopper', 'spoon'} if kind == 'spoon_sugar' else {'wheel', 'latch', 'door'}
        _require(set(nested['roles']) == role_keys and set(nested['joints']) == joint_keys, 'extra embedded roles/joints cannot admit unrelated dynamics')
    d6_ropes = [v for v in mechanism_cases.values() if v.get('schema') == m.SCHEMA_D6]
    if case['schema'] == SCHEMA_V3:
        _require(len(d6_ropes)==1 and all(v['mechanism']!='rope_drawer' or v in d6_ropes for v in mechanism_cases.values()), 'v3 requires exactly one explicitly versioned D6 rope assertion')
    else:
        _require(not d6_ropes, 'D6 rope assertions require the explicit v3 network schema')
    if case['schema'] in (SCHEMA_V2,SCHEMA_V3):
        from . import structural_loads
        declarations = case.get('structural_loads')
        structural_loads.validate_declarations(declarations)
        _require(all(value['thresholds']['seating_steps']+2 <= case['initial_hold_steps'] for value in declarations.values()),
                 'structural load seating must leave two supported steps inside the frozen initial hold')
    return case


def bind_case(case, spec):
    """Bind frozen semantic IDs to actual physical roots, never visual assets."""
    objects = spec.get('objects', {})
    d6_ids={n for n,o in objects.items() if o.get('kind')=='joint' and o.get('joint',{}).get('type')=='d6'}
    if case['schema']==SCHEMA_V3:
        from .d6_admission import rope_source
        declarations=[v for v in case.get('mechanism_cases',{}).values() if v.get('schema')==m.SCHEMA_D6]
        declared={n for value in declarations for n in value['rope']['joint_ids'][1:-1]}
        _require(bool(declarations) and d6_ids==declared, 'every D6 must belong to an explicitly declared internal rope chain')
        _require(all(rope_source(spec,value)['passed'] for value in declarations), 'D6 rope source topology, frames or passive DOF declarations are invalid')
    else:
        _require(not d6_ids, 'D6 source joints require the explicit v3 network schema')
    _require(len({m.path(n) for n in objects}) == len(objects), 'distinct object IDs alias one exported prim path')
    trigger = objects.get(case['trigger_id'], {})
    _require(trigger.get('kind') == 'sphere' and trigger.get('dynamic') is True and trigger.get('collision') is True and m.vector(trigger.get('size')) and min(trigger['size']) > 0 and max(trigger['size'])-min(trigger['size']) <= 1e-9, 'initial trigger must be one physical sphere')
    _require(trigger.get('spawn_step') == case['release_step'], 'trigger release differs from frozen case')
    _require(all(n == case['trigger_id'] or not obj.get('spawn_step', 0) for n, obj in objects.items()), 'all downstream bodies must be initially present')
    _require(all(obj.get('asset_physics') == 'visual_only' and not obj.get('dynamic') for obj in objects.values() if obj.get('kind') == 'asset'), 'visual attachments may not supply hidden imported physics')
    definitions = event_definitions(case)
    event_bodies = {name: _event_body_ids(definition, spec) for name, definition in definitions.items()}
    for name, definition in case['events'].items():
        _require(event_bodies[name] and all(objects.get(body, {}).get('dynamic') is True for body in event_bodies[name]), 'events must measure named dynamic physical bodies')
        for condition in definition['conditions']:
            if condition['kind'] == 'joint_coordinate':
                cfg = objects.get(condition['joint_id'], {}).get('joint', {})
                expected = 'prismatic' if condition['coordinate'] == 'position_m' else 'revolute'
                _require(cfg.get('type') == expected and cfg.get('enabled', True) is True, 'signed joint event coordinate/type/enable mismatch')
            elif condition['kind'] == 'box_leaves_support':
                box, support = objects.get(condition['body_id'], {}), objects.get(condition['support_id'], {})
                _require(box.get('kind') == 'box' and box.get('dynamic') is True and box.get('collision') is True and not box.get('spawn_step') and m.vector(box.get('size')) and min(box['size']) > 0, 'moving-support separation requires an initially present colliding physical box')
                _require(support.get('kind') in ('box', 'compound', 'cylinder') and support.get('dynamic') is True and support.get('collision') is True and not support.get('spawn_step'), 'moving support must be an initially present dynamic colliding root')
        if 'stability' in definition:
            stable = definition['stability']
            _require(set(stable) <= {'body_id', 'max_motion_m', 'max_rotation_degrees'} and stable.get('body_id') in event_bodies[name] and _finite_positive(stable.get('max_motion_m')) and ('max_rotation_degrees' not in stable or _finite_positive(stable['max_rotation_degrees'])), 'invalid event stability body or limits')
    body_edges, path_bodies = set(), set()
    for handoff in case['handoffs']:
        path = handoff['body_path']
        _require(all(objects.get(n, {}).get('dynamic') is True and objects[n].get('kind') in ('box', 'sphere', 'cylinder', 'capsule', 'compound') for n in path), 'handoffs use physical dynamic roots, not static supports or decorative meshes')
        _require(path[0] in event_bodies[handoff['source_event']] and path[-1] in event_bodies[handoff['target_event']], 'handoff endpoint event does not measure its actual endpoint body')
        _require(all(event_bodies[g] <= set(path) for g in handoff.get('guard_events', [])), 'guard event is not local to the physical handoff')
        path_bodies.update(path)
        body_edges.update(zip(path, path[1:]))
        for i, link in enumerate(handoff['links']):
            a, b = path[i:i+2]
            if link['kind'] == 'constraint':
                cfg = objects.get(link['joint_id'], {}).get('joint', {})
                kinds=('fixed','spherical','d6') if case['schema']==SCHEMA_V3 else ('fixed','spherical')
                _require(cfg.get('type') in kinds and cfg.get('enabled', True) is True and {cfg.get('body0'), cfg.get('body1')} == {a, b}, 'constraint transmission requires a declared actual passive connection; D6 requires v3')
            elif len(path) > 2:
                _require(a in event_bodies[link['source_event']] and b in event_bodies[link['target_event']], 'intermediate contact event/body mismatch')
    to_terminal = _reachable({case['terminal']['body_id']}, {(b, a) for a, b in body_edges})
    from_trigger = _reachable({case['trigger_id']}, body_edges)
    _require(path_bodies <= to_terminal & from_trigger, 'dangling physical branches cannot inflate a causal network')
    for definition in case['events'].values():
        for condition in definition['conditions']:
            if condition['kind'] == 'box_leaves_support':
                _require((condition['support_id'], condition['body_id']) in body_edges, 'moving support must be the actual incoming physical handoff body')
    tiles = case['tiles']
    _require(len(set(tiles['activation_events'].values())) == len(tiles['ids']), 'each named tile must have a distinct activation event')
    axis = 'XYZ'.index(tiles['up_axis_local'])
    for name in tiles['ids']:
        obj = objects.get(name, {})
        _require(name in path_bodies and obj.get('kind') == 'box' and obj.get('dynamic') is True and obj.get('collision') is True and obj.get('class_label') == tiles['class_label'] and m.vector(obj.get('size')) and min(obj['size']) > 0 and all(obj['size'][axis] > obj['size'][i] for i in range(3) if i != axis), 'tile must be a distinct labeled physical box with its actual long axis declared')
        _require(event_bodies[tiles['activation_events'][name]] == {name}, 'tile activation event must measure exactly that named tile')
    category_bodies = set()
    for category in case['household_categories'].values():
        for name in category['body_ids']:
            _require(name in path_bodies and objects.get(name, {}).get('dynamic') is True and objects[name].get('class_label') in category['class_labels'], 'household category requires its real labeled transmitting physics root')
            _require(any(name in event_bodies[e] for e in category['activation_events']), 'household body lacks a measured activation event')
            category_bodies.add(name)
    required_quiet = set(tiles['ids']) | category_bodies | {case['terminal']['body_id']}
    required_quiet |= set().union(*(event_bodies[n] for n in case['events'])) - {case['trigger_id']}
    _require(required_quiet <= set(case['quiet_limits']), 'quiet limits omit downstream task bodies')
    _require(all(objects.get(n, {}).get('dynamic') is True and n != case['trigger_id'] for n in case['quiet_limits']), 'quiet limits must name initially present physical downstream bodies')
    for definition in case['events'].values():
        for condition in definition['conditions']:
            if condition['kind'] == 'body_displacement':
                body = condition['body_id'];minimum, maximum = condition.get('minimum_m'), condition.get('maximum_m')
                quiet_key = 'maximum_motion_m'
            elif condition['kind'] == 'joint_coordinate':
                body = objects[condition['joint_id']]['joint']['body1'];minimum, maximum = condition.get('minimum'), condition.get('maximum')
                quiet_key = 'maximum_motion_m' if condition['coordinate'] == 'position_m' else 'maximum_rotation_degrees'
            else:
                # Relative travel and complete support separation are checked
                # independently below; they are not world-motion aliases.
                continue
            threshold = minimum if minimum is not None and minimum > 0 else abs(maximum)
            _require(body == case['trigger_id'] or case['quiet_limits'][body][quiet_key] < threshold, 'quiet tolerance must be smaller than the declared task activation')
    terminal = case['terminal']
    sugar, receiver = objects.get(terminal['body_id'], {}), objects.get(terminal['receiver_id'], {})
    _require(sugar.get('kind') == 'box' and sugar.get('dynamic') is True and m.vector(sugar.get('size')) and all(abs(a-b) <= 1e-9 for a, b in zip(sugar['size'], terminal['size_m'])), 'terminal sugar must have its frozen actual box dimensions')
    _require(receiver.get('kind') in ('box', 'cylinder', 'compound') and not receiver.get('dynamic') and receiver.get('collision') is True, 'receiver must be a real static colliding container')
    rope_ids = set(case.get('rope_body_ids', []))
    _require(rope_ids <= path_bodies and all(objects.get(n, {}).get('kind') == 'capsule' for n in rope_ids), 'rope_body_ids must identify actual named capsule links')
    outgoing_targets = {n: set() for n in path_bodies}
    for h in case['handoffs']:
        for n in h['body_path']:
            outgoing_targets[n].update([h['target_event'], *h.get('guard_events', [])])
    stage_names = set()
    for stage in case['activity']['stages']:
        _require(isinstance(stage, dict) and set(stage) <= {'id', 'purpose', 'start_event', 'end_event', 'start_time', 'end_time', 'roi_world', 'bodies'} and isinstance(stage.get('id'), str) and stage['id'] and stage['id'] not in stage_names and isinstance(stage.get('purpose'), str) and stage['purpose'], 'invalid or duplicate task activity stage')
        stage_names.add(stage['id'])
        _require(stage.get('start_event') in definitions and stage.get('end_event') in definitions and stage.get('end_time', 'onset') == 'onset' and stage.get('start_time', 'onset') in ('onset', 'confirmation') and m.valid_bounds(stage.get('roi_world')), 'task stage needs measured event gates and a frozen world ROI')
        _require(isinstance(stage.get('bodies'), list) and stage['bodies'], 'task stage needs explicit motion sources')
        for source in stage['bodies']:
            _require(isinstance(source, dict) and set(source) <= {'id', 'minimum_speed_m_s', 'minimum_angular_speed_degrees_s', 'direction_world'} and source.get('id') in path_bodies and source['id'] not in rope_ids, 'rope jitter and decorative/component motion cannot supply task activity')
            _require(stage['end_event'] in outgoing_targets[source['id']], 'activity must end at that body\'s frozen physical handoff, not residual spin')
            floors = [source.get(k) for k in ('minimum_speed_m_s', 'minimum_angular_speed_degrees_s')]
            _require(any(_finite_positive(v) for v in floors) and all(v is None or _finite_positive(v) for v in floors), 'freeze positive motion floors')
            if 'direction_world' in source:
                _require(m.unit(source['direction_world']) and _finite_positive(source.get('minimum_speed_m_s')), 'direction_world requires a unit vector and a positive linear floor')
    structural = set()
    for nested in case.get('mechanism_cases', {}).values():
        roles = nested['roles']
        if nested['mechanism'] == 'rope_drawer':
            _require({roles['weight'], roles['drawer']} <= path_bodies and set(nested['rope']['segment_ids']) <= rope_ids, 'embedded cable endpoints and every segment must belong to the actual network force path')
            if nested['rope_model'] == 'segmented_over_free_pulley':
                pulley = roles['pulley']
                axle = objects.get(nested['joints']['pulley'], {}).get('joint', {})
                _require(pulley not in path_bodies and objects.get(pulley, {}).get('dynamic') is True and axle.get('type') == 'revolute' and axle.get('body0') is None and axle.get('body1') == pulley and axle.get('enabled', True) is True, 'embedded free pulley must be a grounded passive revolute structural body')
                structural.add(pulley)
        _require(all(name in path_bodies | structural for name in roles.values() if objects.get(name, {}).get('dynamic')), 'embedded assertions cannot whitelist unrelated dynamic roles')
        _require(all(name in objects for name in roles.values()), 'unknown embedded physical role')
    _require(structural <= set(case['quiet_limits']), 'embedded structural bodies require initial/control quiet limits')
    # Dynamic structural parts (such as free cart wheels) may be joint-connected
    # components; they cannot silently become extra categories or motion sources.
    component_edges = set(body_edges) | {(b, a) for a, b in body_edges}
    for obj in objects.values():
        cfg = obj.get('joint', {})
        if obj.get('kind') == 'joint' and cfg.get('enabled', True) and cfg.get('body0') and cfg.get('body1'):
            component_edges.update(((cfg['body0'], cfg['body1']), (cfg['body1'], cfg['body0'])))
    components = _reachable(path_bodies | structural, component_edges)
    load_binding = None
    if case['schema'] in (SCHEMA_V2,SCHEMA_V3):
        from . import structural_loads
        for declaration in case['structural_loads'].values():
            event = declaration['support_motion_event']
            _require(event in case['events'] and event_bodies[event] == {declaration['support_body_id']},
                     'structural load retirement requires the actual support body motion event')
        load_binding = structural_loads.bind(spec, case['structural_loads'], path_bodies, case['quiet_limits'])
        load_ids = set(load_binding['body_ids'])
        _require(load_ids == set(case['structural_loads']) and not load_ids & path_bodies,
                 'typed structural loads must bind exactly their declared non-task bodies')
        _require(load_ids <= set(case['quiet_limits']), 'typed structural loads require frozen quiet limits')
        # Only independently typed/proven gravity loads extend this boundary.
        # They never become task-path/category/activity bodies or admit other
        # unrelated dynamic bodies through a new component graph traversal.
        components |= load_ids
        structural |= load_ids
    _require({n for n, obj in objects.items() if obj.get('dynamic')} <= components, 'unconnected dynamic decorations are outside the frozen task network')
    _require({n for n, obj in objects.items() if obj.get('dynamic') and n != case['trigger_id']} <= set(case['quiet_limits']), 'quiet limits omit dynamic structural components')
    binding = {'definitions': definitions, 'event_bodies': event_bodies, 'body_edges': body_edges, 'path_bodies': path_bodies,
               'structural_components': structural, 'task_bodies': {n for n, obj in objects.items() if obj.get('dynamic')}}
    if load_binding is not None:
        binding['typed_structural_loads'] = load_binding
    for mode, control in case['controls'].items():
        _control_downstream(case, binding, mode)
        if mode == 'locked_door':
            cfg = objects.get(control['joint_id'], {}).get('joint', {})
            _require(cfg.get('type') == 'revolute' and cfg.get('body1') == control['door_body_id'] and cfg.get('enabled', True) is True, 'locked-door control does not name the active door hinge')
            frames = []
            for i in (0, 1):
                body = cfg.get('body'+str(i))
                rotation = objects[body].get('orientation_wxyz', [1, 0, 0, 0]) if body else [1, 0, 0, 0]
                frames.append(m.multiply_quaternions(rotation, cfg.get('local_rot'+str(i)+'_wxyz', [1, 0, 0, 0])))
            relative = m.multiply_quaternions([frames[0][0], *[-v for v in frames[0][1:]]], frames[1])
            axis = 'XYZ'.index(cfg.get('axis', 'X'))
            angle = (math.degrees(2*math.atan2(relative[axis+1], relative[0]))+180)%360-180
            _require(abs((angle-control['locked_angle_degrees']+180)%360-180) <= 1e-4, 'door control limit would move it away from its authored initial angle')
    return binding


def contact_journal(run, spec):
    """Index actual callback intervals without relabeling their raw counters."""
    records, errors = [], []
    known = {n for n, obj in spec['objects'].items() if obj.get('kind') in ('box', 'sphere', 'cylinder', 'capsule', 'compound') and (obj.get('dynamic') or obj.get('collision'))}
    for sample in run.get('samples', []):
        pairs = sample.get('contact_pairs')
        if not isinstance(pairs, list):
            errors.append({'step': sample.get('physics_steps'), 'error': 'contact_pairs missing'})
            continue
        for value in pairs:
            if not isinstance(value, dict):
                errors.append({'step': sample.get('physics_steps'), 'error': 'invalid contact record'})
                continue
            actors, colliders, ids = value.get('actor_paths'), value.get('collider_paths'), value.get('body_ids')
            absolute = sample.get('absolute_physics_step')
            first, last = value.get('first_callback_absolute_physics_step'), value.get('last_callback_absolute_physics_step')
            valid = isinstance(actors, list) and len(actors) == 2 and isinstance(colliders, list) and len(colliders) == 2 and isinstance(ids, list) and len(ids) == 2 and all(isinstance(n, str) and n in known for n in ids)
            if valid:
                valid = all(isinstance(actor, str) and (actor == m.path(n) or actor.startswith(m.path(n)+'/')) and (collider is None or isinstance(collider, str) and (collider == m.path(n) or collider.startswith(m.path(n)+'/'))) for actor, collider, n in zip(actors, colliders, ids))
            valid = valid and type(value.get('count')) is int and value['count'] > 0 and type(absolute) is int and type(first) is int and type(last) is int and absolute-1 <= first <= last <= absolute
            valid = valid and ('minimum_separation_m' not in value or m.finite(value['minimum_separation_m']))
            if not valid:
                errors.append({'step': sample.get('physics_steps'), 'error': 'unknown or inconsistent actor/collider/callback boundary'})
                continue
            records.append({'observation_step': sample['physics_steps'], 'observation_absolute_step': absolute, **copy.deepcopy(value)})
    return {'passed': not errors, 'records': records, 'errors': errors, 'scope': 'Nonempty callback data received during one app update. Raw callback counters are retained; no middle instant or persistence is synthesized.'}


def contact_witness(journal, first, second, start_step, end_step, zero_step, tolerance):
    witnesses = []
    if start_step is not None and end_step is not None and start_step <= end_step:
        for record in journal['records']:
            if set(record['body_ids']) != {first, second}:
                continue
            relative_first = record['first_callback_absolute_physics_step']-zero_step
            relative_last = record['last_callback_absolute_physics_step']-zero_step
            if start_step-tolerance <= relative_first <= relative_last <= end_step+tolerance:
                witnesses.append(record)
    return {'passed': bool(witnesses), 'body_ids': [first, second], 'window_steps': [start_step, end_step], 'callback_records': witnesses, 'scope': 'Raw callback boundary witness within frozen event window/tolerance; it is not an activation timestamp.'}


def moving_support_geometry(condition, sample, initial, spec):
    """Measure an actual box in the measured support's current local frame."""
    body, support = condition['body_id'], condition['support_id']
    corners = m.local_points(m.box_corners(sample, spec, body), *m.pose(sample, spec, support))
    center = m.local_points([m.pose(sample, spec, body)[0]], *m.pose(sample, spec, support))[0]
    initial_center = m.local_points([m.pose(initial, spec, body)[0]], *m.pose(initial, spec, support))[0]
    travel = math.dist(center, initial_center)
    disjoint = m.points_disjoint(corners, condition['support_region_local'], condition['clearance_m'])
    return {'relative_center_local_m': center, 'relative_travel_m': travel, 'box_corners_local_m': corners,
            'whole_box_disjoint': disjoint, 'passed': travel >= condition['minimum_relative_travel_m'] and disjoint}


def network_event_times(run, spec, definitions):
    """Reuse ordinary P1 predicates, extend only moving-support separation."""
    spatial = {name: rule for name, rule in definitions.items() if any(c.get('kind') == 'box_leaves_support' for c in rule.get('conditions', []))}
    ordinary = {name: rule for name, rule in definitions.items() if name not in spatial}
    result = m.event_times(run['samples'], spec, ordinary, run) if ordinary else {}
    initial, samples = run['initial_observation'], run['samples']
    for name, rule in spatial.items():
        # Network cases deliberately have no after/time gates. A premature
        # loss of support is visible and cannot be hidden by another event.
        _require(not {'after_event', 'not_before_step'} & set(rule), 'spatial events cannot hide early separation')
        flags = [all(moving_support_geometry(c, sample, initial, spec)['passed'] if c['kind'] == 'box_leaves_support' else m.condition_matches(c, sample, initial, spec) for c in rule['conditions']) for sample in samples]
        hold, found = rule.get('hold_steps', 1), None
        for i in range(len(flags)-hold+1):
            if not all(flags[i:i+hold]):
                continue
            stable = rule.get('stability')
            if stable and not m.stable_poses(samples[i:i+hold], spec, stable['body_id'], stable['max_motion_m'], stable.get('max_rotation_degrees', math.inf)):
                continue
            found = i
            break
        result[name] = {'onset_step': samples[found]['physics_steps'] if found is not None else None,
                        'confirmation_step': samples[found+hold-1]['physics_steps'] if found is not None else None}
    return result


def _events(run, spec, case, mode):
    definitions = event_definitions(case)
    excluded = set()
    if mode == 'no_trigger':
        excluded = {n for n, rule in definitions.items() if case['trigger_id'] in _event_body_ids(rule, spec)}
    active = {n: d for n, d in definitions.items() if n not in excluded}
    result = network_event_times(run, spec, active)
    result.update({n: {'onset_step': None, 'confirmation_step': None} for n in excluded})
    return result


def _tilt_degrees(q, local_axis):
    length = math.sqrt(m.dot(q, q))
    up = m.rotate([v/length for v in q], local_axis)
    return math.degrees(math.acos(max(-1., min(1., up[2]/math.sqrt(m.dot(up, up))))))


def tile_measurements(run, case):
    config = case['tiles'];axis = [float(i == 'XYZ'.index(config['up_axis_local'])) for i in range(3)]
    result = {}
    for name in config['ids']:
        values = [(s['physics_steps'], _tilt_degrees(s['orientations_wxyz'][m.path(name)], axis)) for s in run['samples']]
        first = next((step for step, angle in values if angle >= config['tipped_min_degrees']), None)
        initial = _tilt_degrees(run['initial_observation']['orientations_wxyz'][m.path(name)], axis)
        result[name] = {'initial_tilt_degrees': initial, 'initially_upright': initial <= config['initial_upright_max_degrees'], 'first_tipped_step': first,
                        'maximum_tilt_degrees': max(angle for _, angle in values), 'final_tilt_degrees': values[-1][1],
                        'counted': first is not None and first > case['release_step'] and initial <= config['initial_upright_max_degrees']}
        if config.get('require_final_tilt', False):
            result[name]['final_tilt_passed'] = values[-1][1] >= config['tipped_min_degrees']
    return result


def _quiet(run, spec, case, ids, initial_only=False):
    samples = [run['initial_observation']] + [s for s in run['samples'] if not initial_only or s['physics_steps'] <= case['release_step']]
    result = {}
    for name in ids:
        p0, q0 = m.pose(run['initial_observation'], spec, name)
        limits = case['quiet_limits'][name]
        result[name] = all(math.dist(m.pose(s, spec, name)[0], p0) <= limits['maximum_motion_m'] and m.angle_degrees(m.pose(s, spec, name)[1], q0) <= limits['maximum_rotation_degrees'] for s in samples)
    return result


def isolated_control_spec(spec, reference_spec, case, mode):
    expected, current = copy.deepcopy(reference_spec), copy.deepcopy(spec)
    for document in (expected, current):
        for key in ('scene_id', 'revision', 'requests'):
            document.pop(key, None)
    control = case['controls'][mode]
    if mode == 'no_trigger':
        _require(case['trigger_id'] in expected['objects'], 'reference trigger missing')
        expected['objects'].pop(case['trigger_id'])
    elif mode == 'broken_rope':
        cfg = expected['objects'].get(control['joint_id'], {}).get('joint', {})
        _require(cfg.get('enabled', True) is True and {cfg.get('body0'), cfg.get('body1')} & set(case['rope_body_ids']), 'broken_rope must disable an enabled cable constraint')
        cfg['enabled'] = False
    else:
        cfg = expected['objects'].get(control['joint_id'], {}).get('joint', {})
        _require(cfg.get('type') == 'revolute' and cfg.get('body1') == control['door_body_id'] and cfg.get('enabled', True) is True, 'locked door must retain its enabled passive revolute joint')
        _require(cfg.get('lower_limit') != cfg.get('upper_limit') or 'lower_limit' not in cfg, 'reference door is already locked')
        cfg['lower_limit'] = cfg['upper_limit'] = control['locked_angle_degrees']
    return current == expected


def _control_downstream(case, binding, mode):
    control = case['controls'][mode]
    if mode == 'no_trigger':
        expected = binding['task_bodies']-{case['trigger_id']}
        _require(not control['upstream_event_ids'], 'no-trigger has no moving upstream task')
    elif mode == 'broken_rope':
        handoff = next(h for h in case['handoffs'] if h['id'] == control['cut_handoff_id'])
        indices = [i for i, link in enumerate(handoff['links']) if link.get('joint_id') == control['joint_id']]
        _require(len(indices) == 1, 'broken rope joint is not an unambiguous hop of the cut handoff')
        expected = _reachable(set(handoff['body_path'][indices[0]+1:]), binding['body_edges'])
        _require(handoff['source_event'] in control['upstream_event_ids'], 'broken rope must show its real upstream source still activates')
    else:
        cut = control['cut_event_id']
        _require(control['door_body_id'] in binding['event_bodies'][cut], 'door cut event does not measure that door')
        descendants = _reachable({cut}, _edges(case))
        expected = set().union(*(binding['event_bodies'][e] for e in descendants))
        expected |= {control['door_body_id']}
        incoming = {h['source_event'] for h in case['handoffs'] if h['target_event'] == cut}
        _require(bool(incoming) and incoming <= set(control['upstream_event_ids']), 'locked door must show all measured incoming sources still move')
    _require(expected <= set(control['downstream_body_ids']), 'control omits required downstream bodies')
    _require(set(control['downstream_body_ids']) <= binding['task_bodies']-{case['trigger_id']}, 'control quiet bodies must belong to the task')
    _require(all(not binding['event_bodies'][e] & set(control['downstream_body_ids']) for e in control['upstream_event_ids']), 'control upstream motion cannot be supplied by a supposedly quiet downstream body')
    return expected


def handoff_measurements(run, spec, case, binding, events, journal):
    result = {}
    zero = run['initial_observation']['absolute_physics_step']
    for handoff in case['handoffs']:
        source, target = events[handoff['source_event']]['onset_step'], events[handoff['target_event']]['onset_step']
        guards = [events[g]['onset_step'] for g in handoff.get('guard_events', [])]
        chain = [source, *guards, target]
        ordered = all(value is not None for value in chain) and 0 <= target-source <= handoff['maximum_lag_steps'] and all(a <= b for a, b in zip(chain, chain[1:]))
        links = []
        for i, link in enumerate(handoff['links']):
            a, b = handoff['body_path'][i:i+2]
            if link['kind'] == 'contact':
                first = source if len(handoff['body_path']) == 2 else events[link['source_event']]['onset_step']
                last = target if len(handoff['body_path']) == 2 else events[link['target_event']]['onset_step']
                witness = contact_witness(journal, a, b, first, last, zero, case['contact_window_tolerance_steps'])
                witness['passed'] = witness['passed'] and ordered and first is not None and last is not None and source <= first <= last <= target
                links.append({'kind': 'contact', **witness})
            else:
                values = [s['joints'][link['joint_id']] for s in run['samples'] if source is not None and target is not None and source <= s['physics_steps'] <= target]
                maximum = max((v['anchor_error_m'] for v in values), default=None)
                enabled = bool(values) and all(v.get('enabled') is True and v.get('drive_present') is False for v in values)
                links.append({'kind': 'constraint', 'joint_id': link['joint_id'], 'maximum_anchor_error_m': maximum,
                              'passed': ordered and enabled and maximum is not None and maximum <= link['maximum_anchor_error_m']})
        result[handoff['id']] = {'passed': ordered and all(v['passed'] for v in links), 'source_step': source, 'target_step': target, 'guard_steps': guards, 'links': links}
    return result


def category_measurements(case, binding, events, handoffs):
    successful_edges = set()
    for handoff in case['handoffs']:
        if handoffs[handoff['id']]['passed']:
            successful_edges.update(zip(handoff['body_path'], handoff['body_path'][1:]))
    result = {}
    for name, category in case['household_categories'].items():
        qualified = []
        for body in category['body_ids']:
            incoming = {a for a, b in successful_edges if b == body}
            outgoing = {b for a, b in successful_edges if a == body}
            active = [e for e in category['activation_events'] if body in binding['event_bodies'][e] and events[e]['onset_step'] is not None]
            local_activation = any(handoffs[h['id']]['passed'] and body in h['body_path'] and any(handoffs[h['id']]['source_step'] <= events[e]['onset_step'] <= handoffs[h['id']]['target_step'] for e in active) for h in case['handoffs'])
            if any(a != b for a in incoming for b in outgoing) and active and local_activation:
                qualified.append({'body_id': body, 'incoming_bodies': sorted(incoming), 'outgoing_bodies': sorted(outgoing), 'activation_event_ids': active})
        result[name] = {'counted': bool(qualified), 'description': category['description'], 'qualified_bodies': qualified,
                        'scope': 'Actual frozen semantic identity and measured transmission; an independently reviewed identity is required. Pins/supports/decorative meshes are not separate household identities.'}
    return result


def terminal_measurements(run, spec, case, events, journal):
    terminal = case['terminal']
    entered, stable = events['terminal_entered']['onset_step'], events['terminal_stable']['onset_step']
    confirmation = events['terminal_stable']['confirmation_step']
    condition = event_definitions(case)['terminal_entered']['conditions'][0]
    flags = [m.condition_matches(condition, s, run['initial_observation'], spec) for s in run['samples']]
    after_entry = [s for s in run['samples'] if entered is not None and s['physics_steps'] >= entered]
    tail = [s for s in run['samples'] if stable is not None and s['physics_steps'] >= stable]
    contained_after_entry = bool(after_entry) and all(flags[s['physics_steps']-1] for s in after_entry)
    settled_tail = bool(tail) and m.stable_poses(tail, spec, terminal['body_id'], terminal['maximum_motion_m'], terminal['maximum_rotation_degrees'])
    contacts = [r for r in journal['records'] if set(r['body_ids']) == {terminal['body_id'], terminal['receiver_id']}]
    first = min(contacts, key=lambda r: (r['observation_step'], r['first_callback_absolute_physics_step'])) if contacts else None
    initial_inside = m.condition_matches(condition, run['initial_observation'], run['initial_observation'], spec)
    return {'initially_outside': not initial_inside, 'first_whole_entry_step': entered, 'stable_onset_step': stable, 'stable_confirmation_step': confirmation,
            'contained_after_first_entry': contained_after_entry, 'stable_through_remaining_run': settled_tail,
            'first_receiver_contact': first, 'first_receiver_contact_bracket_relative_steps': [first['first_callback_absolute_physics_step']-run['initial_observation']['absolute_physics_step'], first['observation_step']] if first else None,
            'passed': entered is not None and stable is not None and confirmation is not None and entered <= stable <= confirmation and contained_after_entry and settled_tail and first is not None and first['observation_step'] > case['release_step'],
            'whole_sugar_inside_per_step': flags}


def measure_task_activity(run, spec, activity, dt=1/60):
    """Filter base motion by frozen signed progress, without changing samples."""
    base_case = copy.deepcopy(activity)
    directional = any('direction_world' in source for stage in base_case['stages'] for source in stage['bodies'])
    spatial = any(c.get('kind') == 'box_leaves_support' for rule in activity.get('events', {}).values() for c in rule.get('conditions', []))
    if spatial:
        # The immutable helper provides only an upper bound on motion in the
        # real release-to-entry window. Independent network event gates are
        # then applied to the same observations below. No synthetic timestamp,
        # sample, body coordinate or callback is handed to the helper.
        base_case['events'] = {name: rule for name, rule in base_case['events'].items() if not any(c.get('kind') == 'box_leaves_support' for c in rule.get('conditions', []))}
        for stage in base_case['stages']:
            stage.update(start_event=activity['window']['start_event'], end_event=activity['window']['end_event'],
                         start_time=activity['window'].get('start_time', 'onset'), end_time=activity['window'].get('end_time', 'onset'))
    for stage in base_case['stages']:
        for source in stage['bodies']:
            if 'direction_world' in source:
                _require(m.unit(source['direction_world']) and _finite_positive(source.get('minimum_speed_m_s')), 'direction_world requires a unit vector and a positive linear floor')
            source.pop('direction_world', None)
    report = m.measure_activity(run, spec, base_case, dt)
    if not (directional or spatial) or 'per_step_motion_flags' not in report:
        return report
    if spatial:
        report['base_helper_upper_bound_metrics'] = dict(report['metrics'])
        report['events'] = network_event_times(run, spec, activity['events'])
    else:
        report['base_3d_metrics'] = dict(report['metrics'])
    events = report['events']
    samples = {s['physics_steps']: s for s in run['samples']}
    filtered = []
    norm_flags = []
    for original in report['per_step_motion_flags']:
        step = original['physics_step']
        previous, current = samples[step-1], samples[step]
        body_ids, stage_ids, details, norm_bodies = set(), set(), [], set()
        # Projection cannot create a candidate that failed the base norm/angle
        # test. Re-evaluate each candidate stage to preserve multi-stage unions.
        for stage in activity['stages']:
            if stage['id'] not in original['stage_ids']:
                continue
            start = events[stage['start_event']][stage.get('start_time', 'onset')+'_step']
            end = events[stage['end_event']]['onset_step']
            if start is None or end is None or not start < step <= end:
                continue
            for source in stage['bodies']:
                name = source['id'];path = m.path(name)
                if path not in previous.get('positions', {}) or path not in current.get('positions', {}):
                    continue
                p0, q0 = m.pose(previous, spec, name);p1, q1 = m.pose(current, spec, name)
                if not m.points_contained([p0, p1], stage['roi_world']):
                    continue
                direction = source.get('direction_world')
                if direction is not None:
                    length = math.sqrt(m.dot(direction, direction))
                    speed = m.dot(m.sub(p1, p0), [v/length for v in direction])/dt
                else:
                    speed = math.dist(p0, p1)/dt
                linear_floor, angular_floor = source.get('minimum_speed_m_s'), source.get('minimum_angular_speed_degrees_s')
                linear = linear_floor is not None and speed >= linear_floor
                angular = angular_floor is not None and m.angle_degrees(q0, q1)/dt >= angular_floor
                if linear_floor is not None and math.dist(p0, p1)/dt >= linear_floor or angular:
                    norm_bodies.add(name)
                if direction is not None:
                    details.append({'body_id': name, 'stage_id': stage['id'], 'signed_speed_m_s': speed, 'minimum_speed_m_s': linear_floor, 'linear_active': linear, 'angular_active': angular})
                if linear or angular:
                    body_ids.add(name);stage_ids.add(stage['id'])
        _require(body_ids <= set(original['body_ids']), 'progress projection unexpectedly created unmeasured base activity')
        filtered.append({**original, 'active': bool(body_ids), 'body_ids': sorted(body_ids), 'stage_ids': sorted(stage_ids), 'linear_progress_details': details})
        norm_flags.append(bool(norm_bodies))
    count = len(filtered)
    active = sum(flag['active'] for flag in filtered)
    idle = longest = 0
    for flag in filtered:
        idle = 0 if flag['active'] else idle+1
        longest = max(longest, idle)
    metrics = {**report['metrics'], 'net_effective_action_s': active*dt, 'motion_occupancy': active/count, 'maximum_idle_s': longest*dt}
    norm_idle = norm_longest = 0
    for flag in norm_flags:
        norm_idle = 0 if flag else norm_idle+1
        norm_longest = max(norm_longest, norm_idle)
    report['base_3d_metrics'] = {**report['metrics'], 'net_effective_action_s': sum(norm_flags)*dt, 'motion_occupancy': sum(norm_flags)/count, 'maximum_idle_s': norm_longest*dt}
    limits = activity['limits']
    checks = {'minimum_chain_duration': metrics['chain_duration_s'] >= limits['minimum_chain_duration_s'],
              'minimum_net_effective_action': metrics['net_effective_action_s'] >= limits['minimum_net_effective_action_s'],
              'minimum_motion_occupancy': metrics['motion_occupancy'] >= limits['minimum_motion_occupancy'],
              'maximum_idle': metrics['maximum_idle_s'] <= limits['maximum_idle_s']}
    report.update({'passed': bool(report['timeline']['passed'] and report['strict_initial_state']['passed'] and report['passive_sources'] and all(checks.values())),
                   'checks': checks, 'metrics': metrics, 'per_step_motion_flags': filtered,
                   'network_spatial_event_gates_applied': spatial,
                   'progress_scope': 'Original observations and base P1 helper are unchanged. Actual network event gates/ROIs filter eligible intervals; directional linear branches use signed displacement/dt, with optional independent angular branches.'})
    return report


def embedded_mechanism_measurements(run, spec, case, mode='positive', reference_spec=None, dt=1/60):
    """Delegate complete, unchanged observations to the immutable P1 kernel.

    A stopping control does not need to finish a positive terminal mechanism.
    The drawer-end cut alone selects the P1 detached-drawer contract. Other
    controls keep the network's global upstream/quiet/terminal obligations.
    """
    result = {}
    for name, nested in case.get('mechanism_cases', {}).items():
        selected = 'positive' if mode == 'positive' else None
        if mode == 'broken_rope' and nested['mechanism'] == 'rope_drawer' and nested['joints']['drawer_end'] == case['controls'][mode]['joint_id']:
            selected = 'detached_drawer'
        digest = hashlib.sha256(json.dumps(nested, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if selected is None:
            result[name] = {'status': 'skipped_stopping_control', 'required': False, 'mechanism_case_sha256': digest,
                            'scope': 'Positive mechanism completion is intentionally stopped. Global isolated control checks remain required; no positive mechanism success is asserted for this run.'}
        else:
            report = m.evaluate(run, spec, nested, mode=selected, reference_spec=reference_spec if selected == 'detached_drawer' else None, dt=dt)
            result[name] = {'status': 'evaluated', 'required': True, 'mechanism_case_sha256': digest, 'report': report,
                            'scope': 'Complete original run/spec passed directly to the unchanged P1 kernel, with the frozen trigger and t0. No observation slicing or coordinate rebasing.'}
    return result


def evaluate(run, spec, case, mode='positive', reference_spec=None, dt=1/60):
    """Evaluate telemetry without mutating it; file locks are checked separately."""
    validate_case(case)
    _require(mode in MODES and (mode == 'positive' or mode in case['controls']), 'unsupported or undefined control mode')
    _require(mode == 'positive' or isinstance(reference_spec, dict), 'controls require the matching positive reference spec')
    binding = bind_case(case, spec if mode == 'positive' else reference_spec)
    clock = m.timeline(run, spec, dt)
    strict = m.strict_initial_state(run, spec, case, dt)
    passive = m.passive_checks(run, spec, case)
    if not any(o.get('kind') == 'joint' for o in spec['objects'].values()):
        passive['all_joint_observations_passive'] = run.get('mechanism_configuration', {}).get('joints') == [] and all(not s.get('joints') for s in run.get('samples', []))
    if mode == 'no_trigger':
        passive['only_frozen_initial_release'] = case['trigger_id'] not in spec['objects'] and not any(o.get('spawn_step', 0) for o in spec['objects'].values())
        passive['spawn_events_match'] = run.get('spawn_events') == []
    checks = {**clock['checks'], **strict['checks'], **passive}
    report = {'passed': False, 'mode': mode, 'profile': case['profile'], 'case_schema': case['schema'], 'checks': checks, 'timeline': clock, 'strict_initial_state': strict,
              'formal_stage_accepted': False, 'scope': 'Frozen passive-network telemetry. Formal stage acceptance additionally requires intact file locks and the required matched isolated controls. No counterfactual outside those controls is asserted.'}
    if mode != 'positive':
        checks['only_frozen_isolated_scene_change'] = isolated_control_spec(spec, reference_spec, case, mode)
        if not checks['only_frozen_isolated_scene_change']:
            return report
    if not clock['passed'] or not strict['passed'] or not all(passive.values()):
        return report
    checks['all_enabled_joint_anchors_bounded'] = all(value['anchor_error_m'] <= case['maximum_joint_anchor_error_m'] for sample in run['samples'] for value in sample.get('joints', {}).values() if value['enabled'])
    checks['per_step_contact_recording_requested'] = spec.get('observation', {}).get('record_contact_pairs') is True
    journal = contact_journal(run, spec)
    checks['per_step_contact_provenance_valid'] = journal['passed']
    report['contact_journal'] = {'passed': journal['passed'], 'record_count': len(journal['records']), 'errors': journal['errors'], 'scope': journal['scope']}
    if not journal['passed']:
        return report
    embedded = embedded_mechanism_measurements(run, spec, case, mode, reference_spec, dt)
    report['mechanism_cases'] = embedded
    checks['required_embedded_mechanisms_pass'] = all(value['report']['passed'] for value in embedded.values() if value['required'])
    # The legacy P1 kernel's contact summaries remain unchanged. A network
    # pulley role additionally needs an actual callback during the pull.
    for name, value in embedded.items():
        nested = case['mechanism_cases'][name]
        if mode == 'positive' and nested['mechanism'] == 'rope_drawer' and nested['rope_model'] == 'segmented_over_free_pulley':
            measured = value['report']
            witnesses = [contact_witness(journal, segment, nested['roles']['pulley'], measured.get('taut_onset_step'), measured.get('drawer_open_step'), run['initial_observation']['absolute_physics_step'], case['contact_window_tolerance_steps']) for segment in nested['rope']['segment_ids']]
            value['per_step_pulley_contact_witnesses'] = [w for w in witnesses if w['passed']]
            checks['embedded_'+name+'_actual_pulley_contact_during_pull'] = bool(value['per_step_pulley_contact_witnesses'])
    initial_quiet = _quiet(run, spec, case, case['quiet_limits'], True)
    checks['initial_quiet_window_complete'] = len([s for s in run['samples'] if s['physics_steps'] <= case['release_step']]) >= case['initial_hold_steps']
    checks['downstream_initially_quiet'] = all(initial_quiet.values())
    report['initial_quiet_bodies'] = initial_quiet
    spatial_supports = {}
    for name, definition in case['events'].items():
        for i, condition in enumerate(definition['conditions']):
            if condition['kind'] != 'box_leaves_support':
                continue
            initial_geometry = moving_support_geometry(condition, run['initial_observation'], run['initial_observation'], spec)
            contained = m.points_contained(initial_geometry['box_corners_local_m'], condition['support_region_local'])
            contact = contact_witness(journal, condition['support_id'], condition['body_id'], 0, case['release_step'], run['initial_observation']['absolute_physics_step'], 0)
            rows = []
            for sample in run['samples']:
                geometry = moving_support_geometry(condition, sample, run['initial_observation'], spec)
                rows.append({'physics_step': sample['physics_steps'], 'relative_center_local_m': geometry['relative_center_local_m'], 'relative_travel_m': geometry['relative_travel_m'], 'whole_box_disjoint': geometry['whole_box_disjoint'], 'passed': geometry['passed']})
            spatial_supports[name+':'+str(i)] = {'initial_box_corners_local_m': initial_geometry['box_corners_local_m'], 'initial_whole_box_in_support_region': contained,
                                                'initial_support_contact': contact, 'per_step': rows, 'initial_support_passed': contained and contact['passed']}
    report['moving_support_separations'] = spatial_supports
    checks['moving_supports_initially_hold_box'] = all(value['initial_support_passed'] for value in spatial_supports.values())
    events = _events(run, spec, case, mode)
    report['events'] = events
    terminal = terminal_measurements(run, spec, case, events, journal)
    report['terminal'] = terminal
    if case['schema'] in (SCHEMA_V2,SCHEMA_V3):
        from . import structural_loads
        loads = structural_loads.evaluate(run, spec, case['structural_loads'], binding['typed_structural_loads'], events, journal, dt)
        report['structural_loads'] = loads
        checks['typed_structural_loads_supported_and_quiet'] = loads.get('passed') is True
    if mode != 'positive':
        control = case['controls'][mode]
        _control_downstream(case, binding, mode)
        if mode == 'locked_door':
            initial_angle = run['initial_joint_states'][control['joint_id']]['angle_degrees']
            checks['door_locked_at_its_authored_initial_angle'] = abs(initial_angle-control['locked_angle_degrees']) <= 1e-4
        quiet = _quiet(run, spec, case, control['downstream_body_ids'])
        checks['control_downstream_remains_quiet'] = all(quiet.values())
        downstream = set(control['downstream_body_ids'])
        checks['control_downstream_events_absent'] = all(events[e]['onset_step'] is None for e in case['events'] if binding['event_bodies'][e] & downstream)
        checks['control_upstream_still_moves'] = all(events[e]['onset_step'] is not None and events[e]['onset_step'] > case['release_step'] for e in control['upstream_event_ids'])
        checks['control_terminal_not_reached'] = events['terminal_entered']['onset_step'] is None and events['terminal_stable']['onset_step'] is None
        report['control_quiet_bodies'] = quiet
    else:
        checks['all_task_events_observed_after_release'] = all(events[e]['onset_step'] is not None and events[e]['onset_step'] > case['release_step'] for e in case['events'])
        handoffs = handoff_measurements(run, spec, case, binding, events, journal)
        report['handoffs'] = handoffs
        checks['every_physical_handoff_witnessed_and_ordered'] = all(h['passed'] for h in handoffs.values())
        tiles = tile_measurements(run, case)
        report['tiles'] = tiles
        report['actual_tipped_tile_count'] = sum(t['counted'] for t in tiles.values())
        checks['all_named_tiles_initially_upright'] = all(t['initially_upright'] for t in tiles.values())
        checks['actual_named_tile_count_met'] = report['actual_tipped_tile_count'] >= case['tiles']['minimum_tipped']
        if case['tiles'].get('require_final_tilt', False):
            report['actual_final_tipped_tile_count'] = sum(t['counted'] and t['final_tilt_passed'] for t in tiles.values())
            report['final_tilt_requirement'] = {'required': True, 'minimum_degrees': case['tiles']['tipped_min_degrees'],
                                                 'sample_physics_step': run['samples'][-1]['physics_steps'], 'named_tile_count': len(tiles)}
            checks['every_named_tile_has_required_final_tilt'] = report['actual_final_tipped_tile_count'] == len(tiles)
        categories = category_measurements(case, binding, events, handoffs)
        report['household_categories'] = categories
        report['actual_transmitting_household_category_count'] = sum(c['counted'] for c in categories.values())
        checks['actual_household_category_count_met'] = report['actual_transmitting_household_category_count'] >= case['minimum_household_categories']
        checks['whole_sugar_received_and_kept_stable'] = terminal['passed'] and terminal['initially_outside']
        activity = {**copy.deepcopy(case['activity']), 'events': event_definitions(case), 'require_strict_initial_state': True,
                    'window': {'start_event': 'trigger_release', 'end_event': 'terminal_entered', 'start_time': 'onset', 'end_time': 'onset'}}
        report['activity'] = measure_task_activity(run, spec, activity, dt)
        checks['event_gated_union_activity_met'] = report['activity']['passed']
    report['passed'] = all(checks.values())
    return report


def _read_locked(directory, case_path=None, case_validator=None):
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_outputs
    root = Path(directory).expanduser().resolve()
    _require((root/'evidence-lock.json').is_file(), 'complete evidence-lock.json is required before verification')
    inputs, outputs = verify_inputs(root), verify_outputs(root)
    lock = json.loads((root/'run-lock.json').read_text())
    name = lock.get('acceptance_case_file')
    _require(name in ('acceptance-case.json', 'acceptance-case.yaml', 'acceptance-case.yml'), 'a snapshotted network case is required')
    pinned = root/name
    selected = Path(case_path).expanduser().resolve() if case_path else pinned
    data = selected.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    integrity = {'input_integrity': inputs, 'output_integrity': outputs,
                 'case_pinned_to_run': digest == lock.get('acceptance_case_sha256') and pinned.read_bytes() == data,
                 'worker_snapshot_pinned': bool(lock.get('worker_code_sha256')) and inputs.get('checks', {}).get('worker_code_snapshot') is True,
                 'case_sha256': digest, 'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 'reused_mechanism_sha256': hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
    valid = inputs['passed'] and outputs['passed'] and outputs.get('partial') is False and integrity['case_pinned_to_run'] and integrity['worker_snapshot_pinned']
    if not valid:
        return {'root': root, 'integrity': integrity, 'passed': False}
    if selected.suffix.lower() == '.json':
        case = json.loads(data)
    else:
        import yaml
        case = yaml.safe_load(data)
    (case_validator or validate_case)(case)
    run = json.loads((root/'result.json').read_text())
    spec = json.loads((root/'spec.json').read_text())
    integrity['requested_steps_match_run_lock'] = type(lock.get('requested_physics_steps')) is int and lock['requested_physics_steps'] == run.get('requested_physics_steps')
    integrity['result_seed_matches_run_lock'] = 'seed' in lock and 'seed' in run and (lock['seed'] is None or type(lock['seed']) is int) and type(lock['seed']) is type(run['seed']) and lock['seed'] == run['seed']
    valid = valid and integrity['requested_steps_match_run_lock'] and integrity['result_seed_matches_run_lock']
    return {'root': root, 'integrity': integrity, 'passed': bool(valid), 'lock': lock, 'run': run, 'spec': spec, 'case': case}


def verify_run(directory, case_path=None, mode='positive', reference_run=None):
    """Read one sealed run; a control requires a same-case positive reference."""
    _require(mode in MODES, 'unknown passive-network mode')
    data = _read_locked(directory, case_path)
    integrity = data['integrity']
    if not data['passed']:
        return {'passed': False, 'mode': mode, 'formal_stage_accepted': False, **integrity, 'scope': 'Input/output provenance failed; telemetry was not accepted.'}
    reference_spec = None
    if mode != 'positive':
        _require(reference_run is not None, 'negative control requires --reference-run')
        reference = _read_locked(reference_run, case_path)
        integrity['reference_integrity_passed'] = reference['passed']
        if not reference['passed']:
            return {'passed': False, 'mode': mode, 'formal_stage_accepted': False, **integrity, 'scope': 'Positive reference input/output provenance failed.'}
        integrity['same_frozen_case_as_reference'] = integrity['case_sha256'] == reference['integrity']['case_sha256']
        integrity['paired_manifest_fields_match'] = {key: key in data['lock'] and key in reference['lock'] and data['lock'][key] == reference['lock'][key] for key in m.PAIRED_MANIFEST_FIELDS}
        integrity['paired_runtime_configuration_matches'] = all(integrity['paired_manifest_fields_match'].values())
        current_cfg = data['run'].get('mechanism_configuration', {})
        reference_cfg = reference['run'].get('mechanism_configuration', {})
        geometry_present = 'geometry_settings' in current_cfg or 'geometry_settings' in reference_cfg
        integrity['paired_geometry_settings_match'] = not geometry_present or isinstance(current_cfg.get('geometry_settings'), dict) and isinstance(reference_cfg.get('geometry_settings'), dict) and current_cfg['geometry_settings'] == reference_cfg['geometry_settings']
        integrity['geometry_settings_scope'] = 'Recorded SDK geometry-policy metadata must match exactly; it does not identify a failure cause.' if geometry_present else 'Legacy runs did not record the SDK cylinder approximation policy.'
        positive = evaluate(reference['run'], reference['spec'], reference['case'], dt=reference['lock'].get('physics_dt_s', 1/60))
        integrity['reference_positive_passed'] = positive['passed']
        # Structural truth is reported independently of reference success.
        from .asset_snapshots import paired_reference
        reference_spec, integrity['paired_asset_snapshots'] = paired_reference(data, reference)
    report = evaluate(data['run'], data['spec'], data['case'], mode, reference_spec, data['lock'].get('physics_dt_s', 1/60))
    report.update(integrity)
    report['passed'] = bool(report['passed'] and integrity.get('same_frozen_case_as_reference', True) and integrity.get('paired_runtime_configuration_matches', True) and integrity.get('paired_geometry_settings_match', True) and integrity.get('reference_positive_passed', True) and integrity.get('paired_asset_snapshots', {}).get('passed', True))
    report['required_controls'] = data['case']['required_controls']
    return report


def verify_suite(positive_run, control_runs, case_path=None):
    """Accept a frozen stage only after every required isolated control passes."""
    positive = verify_run(positive_run, case_path)
    data = _read_locked(positive_run, case_path)
    if not data['passed']:
        return {'passed': False, 'formal_stage_accepted': False, 'positive': positive, 'controls': {}, 'scope': 'Positive run provenance failed.'}
    case = data['case']
    _require(isinstance(control_runs, dict) and not set(control_runs)-set(case['controls']), 'unknown suite control')
    directories = [Path(positive_run).resolve(), *[Path(p).resolve() for p in control_runs.values()]]
    _require(len(set(directories)) == len(directories), 'a positive/control run cannot be reused for another mode')
    controls = {mode: verify_run(directory, case_path, mode, positive_run) for mode, directory in control_runs.items()}
    complete = set(case['required_controls']) <= set(controls)
    rope_assertions = {name: nested for name, nested in case.get('mechanism_cases', {}).items() if nested['mechanism'] == 'rope_drawer'}
    detached = controls.get('broken_rope', {}).get('mechanism_cases', {})
    mechanism_controls_complete = all(name in detached and detached[name]['status'] == 'evaluated' and detached[name]['report']['mode'] == 'detached_drawer' and detached[name]['report']['passed'] for name in rope_assertions)
    passed = positive['passed'] and complete and mechanism_controls_complete and all(report['passed'] for report in controls.values())
    return {'passed': bool(passed), 'profile': case['profile'], 'formal_stage_accepted': bool(passed and case['profile'] in ('P2', 'P3')),
            'required_controls_complete': complete, 'embedded_mechanism_controls_complete': mechanism_controls_complete, 'positive': positive, 'controls': controls,
            'scope': 'One frozen passive network and its declared isolated controls only. Household identities require independent case review; visual/video delivery and separate P1 mechanism contracts are not certified here.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--case')
    parser.add_argument('--mode', choices=MODES, default='positive')
    parser.add_argument('--reference-run')
    parser.add_argument('--control', action='append', default=[], metavar='MODE=RUN')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        controls = {}
        for item in args.control:
            mode, separator, directory = item.partition('=')
            _require(separator and directory and mode not in controls and mode in MODES[1:], 'use distinct --control MODE=RUN values')
            controls[mode] = directory
        _require(not controls or args.mode == 'positive' and args.reference_run is None, '--control is a positive suite option')
        report = verify_suite(args.run, controls, args.case) if controls else verify_run(args.run, args.case, args.mode, args.reference_run)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        report = {'passed': False, 'formal_stage_accepted': False, 'error': str(error), 'scope': 'Unknown, invalid or incomplete physical evidence was rejected.'}
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        protected = [Path(p).expanduser().resolve() for p in [args.run, args.reference_run, *controls.values()] if p]
        _require(not any(output.is_relative_to(p) for p in protected) and (not args.case or output != Path(args.case).expanduser().resolve()), 'output must be outside immutable runs and cannot overwrite the frozen case')
        output.write_text(text+'\n')
    print(text)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
