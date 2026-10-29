"""Propose a class-aware schedule without mutating a scene."""
from ..scene import SceneError, _id


def interleave(scene, ids, class_order, interval_steps, first_step=None):
    if (not isinstance(ids,list) or not 2<=len(ids)<=1000 or
            not all(isinstance(name,str) for name in ids) or len(set(ids))!=len(ids)):
        raise SceneError('ids must contain 2–1000 distinct scheduled object IDs')
    if (not isinstance(class_order,list) or not class_order or
            not all(isinstance(label,str) and label for label in class_order) or
            len(set(class_order))!=len(class_order)):
        raise SceneError('class_order must contain distinct nonempty class labels')
    if type(interval_steps) is not int or not 1<=interval_steps<=72000:
        raise SceneError('interval_steps must be an integer between 1 and 72000')
    if first_step is not None and (type(first_step) is not int or not 1<=first_step<=72000):
        raise SceneError('first_step must be an integer between 1 and 72000')
    objects=scene.get('objects',{});groups={};previous={}
    for name in ids:
        _id(name);obj=objects.get(name,{})
        step=obj.get('spawn_step');label=obj.get('class_label')
        if obj.get('kind') not in ('box','sphere') or not obj.get('dynamic') or type(step) is not int or step<1 or not isinstance(label,str) or not label:
            raise SceneError('each selected object must be a labeled scheduled dynamic primitive')
        previous[name]=step;groups.setdefault(label,[]).append((step,name))
    if set(groups)!=set(class_order):raise SceneError('class_order must cover exactly the selected classes')
    if len(set(previous.values()))!=len(previous):raise SceneError('selected objects must have distinct original spawn times')
    ordered_groups={label:[name for _,name in sorted(groups[label])] for label in class_order}
    ordered=[]
    for index in range(max(len(group) for group in ordered_groups.values())):
        for label in class_order:
            if index<len(ordered_groups[label]):ordered.append(ordered_groups[label][index])
    origin=min(previous.values()) if first_step is None else first_step
    schedule=[(origin+i*interval_steps,name) for i,name in enumerate(ordered)]
    if schedule[-1][0]>72000:raise SceneError('proposed schedule exceeds the maximum duration of one simulation job')
    selected=set(ids);other_steps={obj.get('spawn_step') for name,obj in objects.items()
        if name not in selected and isinstance(obj,dict) and obj.get('dynamic') and type(obj.get('spawn_step')) is int and obj['spawn_step']>0}
    if any(step in other_steps for step,_ in schedule):raise SceneError('proposed schedule collides with an unselected object spawn')
    return {'operations':[{'op':'update','id':name,'changes':{'spawn_step':step}} for step,name in schedule],
            'schedule':[{'id':name,'class_label':objects[name]['class_label'],'previous_step':previous[name],'spawn_step':step} for step,name in schedule],
            'scope':'class-aware schedule proposal only; regenerate the case and run physics to verify timing and safety'}
