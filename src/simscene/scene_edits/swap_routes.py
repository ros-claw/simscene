"""Propose swapping two single-class scheduled robot routes, without editing."""
import copy
from ..scene import SceneError, _id, validate


def swap_routes(scene, first_robot, second_robot):
    if first_robot == second_robot:
        raise SceneError('robots must be distinct')
    objects = scene.get('objects', {})
    configs = []
    schedules = []
    labels = []
    for name in (first_robot, second_robot):
        _id(name)
        cfg = objects.get(name, {}).get('pose_follower')
        if not isinstance(cfg, dict) or not isinstance(cfg.get('sequence'), list):
            raise SceneError('each robot must have a pose follower sequence')
        items = [phase.get('object') for phase in cfg['sequence'] if phase.get('type') == 'wait_object']
        if not items or not all(isinstance(item, str) for item in items) or len(items) != len(set(items)):
            raise SceneError('each route must wait for distinct scheduled items')
        for item in items:
            obj = objects.get(item, {})
            if not isinstance(item, str) or not obj.get('dynamic') or type(obj.get('spawn_step')) is not int or not isinstance(obj.get('class_label'), str):
                raise SceneError('each route item must be a class-labelled scheduled dynamic object')
        items.sort(key=lambda item: objects[item]['spawn_step'])
        class_labels = {objects[item]['class_label'] for item in items}
        if len(class_labels) != 1:
            raise SceneError('each selected route must currently handle exactly one class')
        configs.append(cfg); schedules.append(items); labels.append(next(iter(class_labels)))
    if labels[0] == labels[1] or len(schedules[0]) != len(schedules[1]) or set(schedules[0]) & set(schedules[1]):
        raise SceneError('routes need different classes and equal, disjoint item counts')
    selected = set(schedules[0]+schedules[1])
    for name, obj in objects.items():
        if name in (first_robot, second_robot):
            continue
        follower = obj.get('pose_follower') if isinstance(obj, dict) else None
        if isinstance(follower, dict) and any(isinstance(phase, dict) and
                any(isinstance(phase.get(key), str) and phase[key] in selected for key in ('object', 'required_object'))
                for phase in follower.get('sequence', [])):
            raise SceneError('a selected item is also referenced by another robot')
    result = []
    for robot, config, old, new in zip((first_robot, second_robot), configs, schedules, schedules[::-1]):
        mapping = dict(zip(old, new)); updated = copy.deepcopy(config)
        for phase in updated['sequence']:
            for key in ('object', 'required_object'):
                value = phase.get(key)
                if isinstance(value, str) and value in mapping:
                    phase[key] = mapping[value]
                elif isinstance(value, str) and value in set(old+new):
                    raise SceneError('route already references items assigned to the other robot')
        result.append({'op': 'update', 'id': robot, 'changes': {'pose_follower': updated}})
    candidate = copy.deepcopy(scene)
    for operation in result:
        candidate['objects'][operation['id']].update(operation['changes'])
    issues = validate(candidate)
    if issues:
        raise SceneError(f'route swap produces an invalid scene: {issues}')
    return {'operations': result,
            'assignments': {first_robot: {'before': labels[0], 'after': labels[1]},
                            second_robot: {'before': labels[1], 'after': labels[0]}},
            'scope': 'route proposal only; review bin labels and validate reachability, collision clearance and physical sorting'}
