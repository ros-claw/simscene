"""Expand a class-routed primitive stream into ordinary scene operations."""
import copy
import math
from .scene import SceneError, _id

def plan_stream(scene, prefix, labels, routes, position, size, interval_steps=240, first_step=1, mass_kg=.1, spawn_steps=None):
    _id(prefix)
    if not isinstance(labels,list) or not labels or len(labels)>100 or not all(isinstance(x,str) and x for x in labels):
        raise SceneError('labels must contain 1–100 nonempty class labels')
    if not isinstance(routes,dict) or any(label not in routes for label in labels):raise SceneError('every class needs a route')
    if spawn_steps is None:
        if type(interval_steps) is not int or interval_steps<1 or type(first_step) is not int or first_step<1 or first_step+(len(labels)-1)*interval_steps>360000:
            raise SceneError('invalid spawn timing')
        times=[first_step+i*interval_steps for i in range(len(labels))]
    else:
        if not isinstance(spawn_steps,list) or len(spawn_steps)!=len(labels) or not all(type(x) is int and 1<=x<=360000 for x in spawn_steps) or any(a>=b for a,b in zip(spawn_steps,spawn_steps[1:])):
            raise SceneError('spawn_steps must be a strictly increasing step for each label')
        times=spawn_steps
    for vector in (position,size):
        if not isinstance(vector,list) or len(vector)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in vector):raise SceneError('position and size must be finite three-vectors')
    if any(x<=0 for x in size) or not isinstance(mass_kg,(int,float)) or isinstance(mass_kg,bool) or not math.isfinite(mass_kg) or mass_kg<=0:
        raise SceneError('size and mass must be positive')
    sequences={};ops=[];assignments=[];class_counts={}
    for index,label in enumerate(labels):
        route=routes[label]
        if not isinstance(route,dict):raise SceneError('route must be a mapping')
        robot=_id(route.get('robot_id'));obj=scene['objects'].get(robot,{})
        config=obj.get('pose_follower')
        if obj.get('kind')!='asset' or not isinstance(config,dict):raise SceneError(f'route robot lacks pose follower: {robot}')
        wait=route.get('wait');cycle=route.get('cycle')
        wait_required={'axis','minimum','maximum','max_steps'}
        if not isinstance(wait,dict) or not wait_required.issubset(wait) or set(wait)-(wait_required|{'workspace_min','workspace_max'}) or not isinstance(cycle,list) or not cycle:
            raise SceneError('route requires wait={"axis":"x","minimum":0.4,"maximum":0.5,"max_steps":12000} and a nonempty cycle array; workspace_min/workspace_max may be added to wait')
        if robot not in sequences:
            if config.get('sequence'):raise SceneError(f'route robot already has a sequence: {robot}')
            sequences[robot]=[]
        item=_id(prefix+str(index).zfill(4))
        if item in scene['objects']:raise SceneError(f'object already exists: {item}')
        spawn_step=times[index]
        class_index=class_counts.get(label,0);class_counts[label]=class_index+1
        workpiece={'kind':'box','position':list(position),'size':list(size),'dynamic':True,'mass_kg':mass_kg,'spawn_step':spawn_step,'class_label':label}
        if 'color' in route:workpiece['color']=copy.deepcopy(route['color'])
        ops.append({'op':'add','id':item,'object':workpiece})
        sequences[robot].append(dict(type='wait_object',object=item,**wait))
        for phase in cycle:
            if not isinstance(phase,dict):raise SceneError('cycle phases must be mappings')
            expanded=copy.deepcopy(phase)
            for key in ('object','required_object'):
                if expanded.get(key)=='$item':expanded[key]=item
            if expanded.get('position')=='$slot':
                slots=route.get('slots')
                if not isinstance(slots,list) or class_index>=len(slots):raise SceneError(f'route {label} has too few placement slots')
                slot=slots[class_index];offset=expanded.pop('slot_offset',[0,0,0])
                if not all(isinstance(v,list) and len(v)==3 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in v) for v in (slot,offset)):
                    raise SceneError('placement slot and offset must be finite three-vectors')
                expanded['position']=[a+b for a,b in zip(slot,offset)]
            elif 'slot_offset' in expanded:
                raise SceneError('slot_offset requires a $slot position')
            sequences[robot].append(expanded)
        assignments.append({'id':item,'class_label':label,'robot_id':robot,'spawn_step':spawn_step})
    for robot,sequence in sequences.items():
        config=copy.deepcopy(scene['objects'][robot]['pose_follower']);config['sequence']=sequence
        ops.append({'op':'update','id':robot,'changes':{'pose_follower':config}})
    from .scene import validate
    candidate=copy.deepcopy(scene)
    for op in ops:
        if op['op']=='add':candidate['objects'][op['id']]=op['object']
        else:candidate['objects'][op['id']].update(op['changes'])
    issues=validate(candidate)
    if issues:raise SceneError(f'planned stream is invalid: {issues}')
    return {'operations':ops,'assignments':assignments,'scope':'schedule proposal; no reachability, collision, throughput or task-success guarantee'}
