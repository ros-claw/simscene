"""Propose a non-mutating, general scheduled-object retiming operation."""
import math
from ..scene import SceneError, _id


def retime(scene, ids, spacing_factor):
    if (not isinstance(ids, list) or len(ids) < 2 or len(ids) > 1000
            or not all(isinstance(name, str) for name in ids) or len(set(ids)) != len(ids)):
        raise SceneError('ids must contain 2–1000 distinct scheduled object IDs')
    if (isinstance(spacing_factor, bool) or not isinstance(spacing_factor, (int, float))
            or not math.isfinite(spacing_factor) or not 0 < spacing_factor <= 100):
        raise SceneError('spacing_factor must be finite and in (0, 100]')
    schedule = []
    for name in ids:
        _id(name)
        obj = scene.get('objects', {}).get(name, {})
        step = obj.get('spawn_step')
        if obj.get('kind') not in ('box', 'sphere') or not obj.get('dynamic') or type(step) is not int or step < 1:
            raise SceneError('every selected object must be a scheduled dynamic primitive')
        schedule.append((step, name))
    schedule.sort()
    if len({step for step, _ in schedule}) != len(schedule):
        raise SceneError('selected objects must have distinct original spawn times')
    origin = schedule[0][0]
    adjusted = [(origin + round((step-origin)*spacing_factor), name) for step, name in schedule]
    if any(step > 72000 for step, _ in adjusted) or len({step for step, _ in adjusted}) != len(adjusted):
        raise SceneError('retimed steps collide or exceed the maximum duration of one simulation job')
    return {'operations': [{'op': 'update', 'id': name, 'changes': {'spawn_step': step}}
                           for step, name in adjusted],
            'schedule': [{'id': name, 'previous_step': old, 'spawn_step': new}
                         for (old, _), (new, name) in zip(schedule, adjusted)],
            'scope': 'schedule proposal only; rerun to check the actual conveyor and robot behavior'}
