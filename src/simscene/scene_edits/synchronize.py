"""Suggest an interleaved stream from measured pickup timing, not a safety proof."""
import hashlib
import json
import math

from ..scene import SceneError
from .interleave import interleave


def synchronize(scene, run, case, ids):
    digest = hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if case.get('source_scene_sha256') != digest:
        raise SceneError('observed case must match the current scene; rerun after edits')
    if run.get('actual_physics_steps') != run.get('requested_physics_steps') or not run.get('actual_physics_steps'):
        raise SceneError('a complete observed run is required')
    if (not isinstance(ids, list) or len(ids) < 2 or
            not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids))):
        raise SceneError('select distinct scheduled item IDs')
    items = case.get('objects', [])
    if (not isinstance(items, list) or len(items) != len(ids) or
            not all(isinstance(i, dict) and isinstance(i.get('part_id'), str) for i in items) or
            {i['part_id'] for i in items} != set(ids)):
        raise SceneError('selected IDs must exactly match the observed stream case')
    events = run.get('spawn_events', [])
    if (not isinstance(events, list) or not all(isinstance(e, dict) for e in events) or
            [e.get('id') for e in events] != case.get('expected_spawn_order') or
            len(events) != len(ids) or {e.get('id') for e in events} != set(ids)):
        raise SceneError('observed spawn order must match the pinned case')
    event_by_id = {e['id']: e for e in events}
    observed = {}
    for item in items:
        part, label, robot = item.get('part_id'), item.get('class_label'), item.get('robot_id')
        obj = scene.get('objects', {}).get(part, {})
        event = event_by_id.get(part, {})
        if (not isinstance(label, str) or not label or not isinstance(robot, str) or not robot or
                type(event.get('physics_step')) is not int or obj.get('class_label') != label or
                event.get('class_label') != label or event.get('physics_step') != obj.get('spawn_step')):
            raise SceneError('observed item, class and spawn time must match the scene')
        transitions = run.get('followers', {}).get(robot, {}).get('transitions', [])
        steps = {t.get('index'): t.get('physics_step') for t in transitions if isinstance(t, dict)}
        start = steps.get(item.get('tracking_phase'))
        end_index = item.get('release_phase')
        end = steps.get(end_index + 1) if type(end_index) is int else None
        if type(start) is not int or type(end) is not int or start < event['physics_step'] or end <= start:
            raise SceneError('each selected item needs an observed complete pickup cycle')
        # The first item is least affected by a previous cycle occupying the arm.
        if label in observed and observed[label]['robot_id'] != robot:
            raise SceneError('each class must be handled by one robot')
        if label not in observed or event['physics_step'] < observed[label]['spawn_step']:
            observed[label] = {'spawn_step': event['physics_step'], 'tracking_step': start,
                               'delay_steps': start-event['physics_step'], 'active_steps': end-start,
                               'robot_id': robot}
    if len(observed) < 2 or len({x['robot_id'] for x in observed.values()}) != len(observed):
        raise SceneError('synchronization requires at least two distinct class routes and robots')
    order = sorted(observed, key=lambda label: (-observed[label]['delay_steps'], label))
    spread = observed[order[0]]['delay_steps'] - observed[order[-1]]['delay_steps']
    spacing = max(1, math.ceil(spread / (len(order)-1)),
                  math.ceil(max(x['active_steps'] for x in observed.values()) / len(order)))
    proposal = interleave(scene, ids, order, spacing)
    proposal.update({'class_order': order, 'interval_steps': spacing, 'observed_first_cycles': observed,
                     'scope': 'timing proposal from one completed run; regenerate the case and rerun physics to verify overlap, throughput and safety'})
    return proposal
