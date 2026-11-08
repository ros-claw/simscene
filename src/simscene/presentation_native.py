"""Bounded camera proposals from frozen native measurements; never runtime control.

These are evidence locators, not physical success or necessary-causality verdicts.
"""
import hashlib
import json
import math
from pathlib import Path

ARTICULATED='simscene.articulated_asset_smoke.v1'
HANDOFF='simscene.handoff_chain.v1'
GALLERY='simscene.asset_gallery.v1'
SCOPE='camera proposal from recorded evidence only; no runtime action or physical pass claim'


def _finite(value):return type(value) in (int,float) and math.isfinite(value)


def _pointer(value):return str(value).replace('~','~0').replace('/','~1')


def _components(case):
    if not isinstance(case,dict):return []
    schema=case.get('schema')
    if schema==GALLERY:
        from .verification.asset_gallery import validate_case
        validate_case(case)
        return [(item['id'],item['case'],'/components/'+str(i)+'/case') for i,item in enumerate(case['components']) if item['case']['schema'] in (ARTICULATED,HANDOFF)]
    if schema==ARTICULATED:
        from .verification.articulated_asset_smoke import validate_case
        validate_case(case)
    elif schema==HANDOFF:
        from .verification.handoff_chain import validate_case
        validate_case(case)
    else:return []
    return [(None,case,'')]


def _frames(run):
    steps=run.get('actual_physics_steps');duration=run.get('simulation_time_s')
    if (type(steps) is not int or not 0<steps<=60000 or steps!=run.get('requested_physics_steps')
            or not _finite(duration) or duration<=0 or run.get('partial') is not False
            or run.get('samples_truncated') is not False or run.get('observation_interval_steps')!=1):return []
    samples=run.get('samples',[])
    if not isinstance(samples,list):return []
    frames=[run.get('initial_observation')]+samples
    if len(frames)!=steps+1:return []
    dt=duration/steps
    if not _finite(dt) or dt<=0:return []
    if any(not isinstance(f,dict) or type(f.get('physics_steps')) is not int or f['physics_steps']!=i
           or not _finite(f.get('simulation_time_s')) or abs(f['simulation_time_s']-i*dt)>1e-6 for i,f in enumerate(frames)):return []
    return [(frame,'/initial_observation' if i==0 else '/samples/'+str(i-1)) for i,frame in enumerate(frames)]


def _event(kind,frame,evidence,case_pointer,component,**fields):
    return dict(kind=kind,physics_step=frame['physics_steps'],sim_time_s=frame['simulation_time_s'],
                evidence_ref='result.json#'+evidence,case_ref='acceptance-case.json#'+case_pointer,
                component_id=component,scope=SCOPE,**fields)


def _joint_events(run,frames,case,prefix,component):
    events=[]
    for owner,item in case['objects'].items():
        joint_id=item['joint_id'];base='/objects/'+_pointer(owner)
        case_base=prefix+base;joint_pointer='/mechanisms/'+_pointer(owner)+'/joints/'+_pointer(joint_id)
        frozen=(run.get('body_bindings',{}).get(owner,{}) or {}).get('joints',{}).get(joint_id,{})
        if any(frozen.get(k)!=item[k] for k in ('joint_path','parent_body','child_body','limits','position_unit')):continue
        from .worker.mechanism import measure_joint
        actual=[];previous=None
        dt=frames[-1][0]['simulation_time_s']/run['actual_physics_steps']
        for frame,path in frames:
            record=frame.get('mechanisms',{}).get(owner,{}).get('joints',{}).get(joint_id,{})
            if (not _finite(record.get('position')) or record.get('joint_path')!=item['joint_path']
                    or record.get('position_unit')!=item['position_unit']
                    or record.get('measurement_source')!='same_sample_PhysX_body_poses_joint_frame_reconstruction'):
                actual=[];break
            if record.get('native_position') is not None and (not _finite(record['native_position'])
                    or record.get('native_measurement_source')!='PhysX_articulation_tensor_DOF_readback_SI'
                    or abs(record['position']-record['native_position'])>item['limit_tolerance']):
                actual=[];break
            try:
                measured=measure_joint(frozen,frame,previous,physics_step=frame['physics_steps'],physics_dt_s=dt)
            except (ValueError,KeyError,TypeError,AttributeError):
                actual=[];break
            if abs(measured['position']-record['position'])>1e-6:
                actual=[];break
            previous=measured
            actual.append((frame,path,record))
        if not actual:continue
        commands=frames[-1][0].get('mechanisms',{}).get(owner,{}).get('command_events',[])
        if not isinstance(commands,list):commands=[]
        points=item.get('waypoints',[]);expected={(p['command_step'],p['target_position']):p for p in points}
        matching=[];seen=set()
        for index,command in enumerate(commands):
            if not isinstance(command,dict):continue
            step=command.get('physics_step');target=command.get('target_position')
            if type(step) is not int or not _finite(target):continue
            key=(step,target)
            if (command.get('joint_id')==joint_id and key in expected and key not in seen and 0<=step<len(frames)
                    and command.get('position_unit')==item['position_unit'] and command.get('cause')=='declared_at_step_schedule'
                    and command.get('trigger')=={'type':'at_step','physics_step':step} and isinstance(command.get('drive_readback'),dict)):
                seen.add(key);matching.append((index,command))
        matching.sort(key=lambda value:value[1]['physics_step'])
        ends=[('first',matching[0]),('last',matching[-1])] if len(matching)>1 else [('first',matching[0])] if matching else []
        for endpoint,(index,command) in ends:
            point_index=next(i for i,p in enumerate(points) if p['command_step']==command['physics_step'] and p['target_position']==command['target_position'])
            events.append(_event('declared_joint_command',frames[command['physics_step']][0],
                frames[-1][1]+'/mechanisms/'+_pointer(owner)+'/command_events/'+str(index),case_base+'/waypoints/'+str(point_index),component,
                owner_id=owner,joint_id=joint_id,joint_path=item['joint_path'],endpoint=endpoint,
                declared_command_count=len(points),recorded_matching_command_count=len(matching),target_position=command['target_position'],
                position_unit=item['position_unit'],interpretation='recorded scheduled command; not measured motion'))
        initial=actual[0][2]['position'];tolerance=item['limit_tolerance']
        moved=next((row for row in actual[1:] if abs(row[2]['position']-initial)>tolerance),None)
        if moved:
            frame,path,record=moved
            events.append(_event('joint_motion_started',frame,path+joint_pointer+'/position',case_base+'/limit_tolerance',component,
                owner_id=owner,joint_id=joint_id,joint_path=item['joint_path'],actual_position=record['position'],
                initial_actual_position=initial,motion_threshold=tolerance,position_unit=item['position_unit'],measurement_source=record['measurement_source']))
        endpoints=[('first',0),('last',len(points)-1)] if len(points)>1 else [('first',0)] if points else []
        for endpoint,index in endpoints:
            point=points[index]
            if point['by_step']>=len(frames):continue
            found=next((row for row in actual[point['command_step']+1:point['by_step']+1]
                if abs(row[2]['position']-point['target_position'])<=point['tolerance']),None)
            if found:
                frame,path,record=found
                events.append(_event('waypoint_observed',frame,path+joint_pointer+'/position',case_base+'/waypoints/'+str(index),component,
                    owner_id=owner,joint_id=joint_id,joint_path=item['joint_path'],endpoint=endpoint,
                    declared_waypoint_count=len(points),target_position=point['target_position'],actual_position=record['position'],
                    tolerance=point['tolerance'],position_unit=item['position_unit'],measurement_source=record['measurement_source'],
                    interpretation='actual coordinate within frozen tolerance; not evidence of command causality'))
    return events


def _contact_events(run,frames,case,prefix,component):
    if run.get('contacts_truncated') is not False or run.get('contact_geometry_incomplete') is not False:return []
    from .verification.handoff_chain import _path
    zero=run.get('run_zero_absolute_physics_step')
    if type(zero) is not int or zero<0:return []
    tiles=case['tiles'];pairs=[(case['source_body'],tiles[0])]+list(zip(tiles,tiles[1:]))+[
        (tiles[-1],case['ball_body']),(case['ball_body'],case['guide_actor']),(case['ball_body'],case['receiver_floor_actor'])]
    wanted={frozenset(pair):pair for pair in pairs};found={};dt=frames[-1][0]['simulation_time_s']/run['actual_physics_steps']
    for frame,path in frames:
        for index,pair in enumerate(frame.get('contact_pairs',[])):
            if not isinstance(pair,dict):continue
            actors=pair.get('actor_paths');first=pair.get('first_callback_absolute_physics_step');last=pair.get('last_callback_absolute_physics_step')
            if (not isinstance(actors,list) or len(actors)!=2 or not all(_path(a) for a in actors) or actors[0]==actors[1]
                    or type(pair.get('count')) is not int or pair['count']<=0 or type(first) is not int or type(last) is not int
                    or not zero<first<=last<=zero+frame['physics_steps']):continue
            key=frozenset(actors)
            if key not in wanted or key in found and found[key]['physics_step']<=first-zero:continue
            event=_event('contact_observed',frame,path+'/contact_pairs/'+str(index),prefix,component,
                actor_paths=list(wanted[key]),callback_absolute_physics_step=first,observed_in_sample_physics_step=frame['physics_steps'],
                interpretation='recorded contact of a case-declared handoff pair; necessary causality untested')
            event.update(physics_step=first-zero,sim_time_s=(first-zero)*dt)
            found[key]=event
    return list(found.values())


def proposed_events(run,case,*,max_events=64):
    """Return at most 64 NEW proposals, including any truncation summary."""
    if type(max_events) is not int or not 2<=max_events<=64:raise ValueError('native event budget must be 2..64')
    components=_components(case)
    if not components:return []
    frames=_frames(run)
    if not frames:return []
    result=[]
    for component,embedded,prefix in components:
        result.extend(_joint_events(run,frames,embedded,prefix,component) if embedded['schema']==ARTICULATED else _contact_events(run,frames,embedded,prefix,component))
    result.sort(key=lambda event:(event['physics_step'],event['kind'],event.get('owner_id',''),str(event.get('component_id'))))
    if len(result)>max_events:
        omitted=len(result)-(max_events-1);result=result[:max_events-1]+[{
            'kind':'native_event_truncation','physics_step':frames[-1][0]['physics_steps'],'sim_time_s':frames[-1][0]['simulation_time_s'],
            'omitted_event_count':omitted,'total_candidate_event_count':len(result),'max_new_events':max_events,
            'scope':SCOPE,'interpretation':'camera proposal budget only; physical measurements remain in result.json'}]
    return result


def frozen_events(directory,run):
    """Read only the case whose exact hash is pinned by this run's lock."""
    root=Path(directory);lock_path=root/'run-lock.json'
    if not lock_path.is_file():return []
    lock=json.loads(lock_path.read_text())
    if lock.get('acceptance_case_file')!='acceptance-case.json':return []
    path=root/'acceptance-case.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>256*1024:return []
    data=path.read_bytes()
    try:case=json.loads(data)
    except (ValueError,UnicodeError):return []
    if not isinstance(case,dict) or case.get('schema') not in (ARTICULATED,HANDOFF,GALLERY):return []
    if hashlib.sha256(data).hexdigest()!=lock.get('acceptance_case_sha256'):raise ValueError('native presentation case hash changed')
    return proposed_events(run,case)
