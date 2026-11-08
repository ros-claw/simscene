"""Frozen imported single-DOF diagnostics; commands are never measurements."""
import json
import math
from pathlib import Path

SCHEMA='simscene.articulated_asset_smoke.v1'


def _number(value):
    return type(value) in (int,float) and math.isfinite(value)


def validate_case(case):
    from ..worker.mechanism import _path
    if not isinstance(case,dict) or case.get('schema')!=SCHEMA or case.get('schema_version')!=1:
        raise ValueError('unsupported articulated asset smoke case')
    if case.get('mode') not in ('driven','passive'):
        raise ValueError('articulated smoke must distinguish driven and passive modes')
    objects=case.get('objects')
    if not isinstance(objects,dict) or not 0<len(objects)<=16:
        raise ValueError('articulated smoke requires frozen objects')
    paths=set()
    for name,item in objects.items():
        if not isinstance(name,str) or not isinstance(item,dict) or not isinstance(item.get('joint_id'),str):
            raise ValueError('invalid frozen articulated object')
        if not _path(item.get('joint_path')) or not _path(item.get('child_body')) or item.get('parent_body') is not None and not _path(item['parent_body']):
            raise ValueError('articulated smoke requires exact joint/link paths')
        if item['joint_path'] in paths:raise ValueError('duplicate articulated joint path')
        paths.add(item['joint_path'])
        limits=item.get('limits')
        if not isinstance(limits,list) or len(limits)!=2 or not all(_number(x) for x in limits) or limits[0]>=limits[1]:
            raise ValueError('articulated case requires finite ordered limits')
        if item.get('position_unit') not in ('rad','m'):
            raise ValueError('articulated smoke units must be rad or m')
        for key in ('initial_position','min_travel','limit_tolerance','anchor_tolerance_m'):
            if not _number(item.get(key)) or key!='initial_position' and item[key]<=0:
                raise ValueError('invalid articulated smoke displacement/tolerance')
        if not limits[0]<=item['initial_position']<=limits[1] or item['min_travel']>limits[1]-limits[0]:
            raise ValueError('articulated smoke initial position/travel outside limits')
        waypoints=item.get('waypoints',[])
        if not isinstance(waypoints,list) or case['mode']=='driven' and len(waypoints)<2 or case['mode']=='passive' and waypoints:
            raise ValueError('driven smoke requires forward/reverse waypoints; passive smoke forbids commands')
        last=-1
        for point in waypoints:
            if (not isinstance(point,dict) or set(point)!={'command_step','target_position','by_step','tolerance'}
                    or type(point['command_step']) is not int or type(point['by_step']) is not int
                    or not 0<=point['command_step']<point['by_step'] or point['command_step']<=last
                    or not _number(point['target_position']) or not limits[0]<=point['target_position']<=limits[1]
                    or not _number(point['tolerance']) or point['tolerance']<=0):
                raise ValueError('invalid frozen articulated waypoint')
            last=point['command_step']
        if case['mode']=='driven' and abs(waypoints[0]['target_position']-waypoints[-1]['target_position'])<item['min_travel']:
            raise ValueError('driven smoke requires distinct forward and reverse targets')
        actors=item.get('required_contact_actors',[])
        if not isinstance(actors,list) or any(not _path(p) or p==item['child_body'] for p in actors) or len(actors)!=len(set(actors)):
            raise ValueError('invalid articulated contact actors')
    return case


def evaluate(run,case):
    validate_case(case)
    try:return _evaluate(run,case)
    except (KeyError,TypeError,ValueError,AttributeError) as error:
        return {'schema_version':1,'passed':False,'checks':{'valid_measurements':False},'errors':[str(error)]}


def _evaluate(run,case):
    from ..worker.mechanism import measure_joint,validate_binding
    frames=[run.get('initial_observation')]+run.get('samples',[])
    steps=run.get('actual_physics_steps');dt=case.get('physics_dt_s',1/60)
    if not _number(dt) or dt<=0:raise ValueError('invalid frozen physics step duration')
    checks={'full_physics_steps':type(steps) is int and steps>0 and steps==run.get('requested_physics_steps'),
            'complete_per_step_timeline':False,'not_partial':run.get('partial') is False,
            'samples_not_truncated':run.get('samples_truncated') is False,
            'contacts_not_truncated':run.get('contacts_truncated') is False,
            'contact_geometry_complete':run.get('contact_geometry_incomplete') is False,
            'no_followers':not run.get('followers')}
    checks['complete_per_step_timeline']=(checks['full_physics_steps'] and run.get('observation_interval_steps')==1
        and len(frames)==steps+1 and all(isinstance(f,dict) and f.get('physics_steps')==i
            and _number(f.get('simulation_time_s')) and abs(f['simulation_time_s']-i*dt)<1e-6 for i,f in enumerate(frames))
        and _number(run.get('simulation_time_s')) and abs(run['simulation_time_s']-steps*dt)<1e-6)
    outcomes={}
    if not checks['complete_per_step_timeline']:
        return {'schema_version':1,'passed':False,'checks':checks,'objects':outcomes}
    for name,item in case['objects'].items():
        binding=run.get('body_bindings',{}).get(name,{})
        validate_binding(binding);joint=binding['joints'].get(item['joint_id'])
        matching=joint is not None and all(joint.get(k)==item[k] for k in ('joint_path','parent_body','child_body','limits','position_unit'))
        obj={'frozen_joint_binding_matches':matching,'full_actual_measurements':False,'measured_travel':False,
             'actual_limits_respected':False,'actual_anchors_consistent':False,'initial_coordinate_matches':False,
             'command_mode_matches':False,'forward_reverse_actual_targets':False,'specified_contacts':False}
        if not matching:
            outcomes[name]={'checks':obj,'passed':False};continue
        previous=None;actual=[];anchor=[];native_consistent=True
        for frame in frames:
            record=frame['mechanisms'][name]['joints'][item['joint_id']]
            reconstructed=measure_joint(joint,frame,previous,physics_step=frame['physics_steps'],physics_dt_s=dt)
            if (not _number(record.get('position')) or abs(record['position']-reconstructed['position'])>1e-6
                    or record.get('joint_path')!=item['joint_path'] or record.get('position_unit')!=item['position_unit']
                    or record.get('measurement_source')!='same_sample_PhysX_body_poses_joint_frame_reconstruction'):
                raise ValueError('articulated measurement differs from actual frozen link frames')
            if reconstructed['velocity'] is not None and (not _number(record.get('velocity')) or abs(record['velocity']-reconstructed['velocity'])>1e-5):
                raise ValueError('articulated velocity differs from measured step-to-step motion')
            if record.get('native_position') is not None:
                native_consistent &= (_number(record.get('native_position')) and _number(record.get('native_velocity'))
                    and record.get('native_measurement_source')=='PhysX_articulation_tensor_DOF_readback_SI'
                    and abs(record['native_position']-record['position'])<=item['limit_tolerance'])
            previous=reconstructed;actual.append(record['position']);anchor.append(reconstructed['anchor_error_m'])
        obj['full_actual_measurements']=native_consistent
        obj['measured_travel']=max(actual)-min(actual)>=item['min_travel']
        obj['initial_coordinate_matches']=abs(actual[0]-item['initial_position'])<=item['limit_tolerance']
        obj['actual_limits_respected']=all(item['limits'][0]-item['limit_tolerance']<=v<=item['limits'][1]+item['limit_tolerance'] for v in actual)
        obj['actual_anchors_consistent']=max(anchor)<=item['anchor_tolerance_m']
        final=frames[-1]['mechanisms'][name];events=final.get('command_events',[])
        if case['mode']=='passive':
            obj['command_mode_matches']=not events and not final.get('runtime_targets') and (joint['drive'] is None or joint['drive']['stiffness']==0 and joint['drive'].get('target_velocity',0)==0)
            obj['forward_reverse_actual_targets']=True
        else:
            points=item['waypoints'];obj['command_mode_matches']=len(events)==len(points)
            hits=[]
            for event,point in zip(events,points):
                obj['command_mode_matches'] &= (event.get('joint_id')==item['joint_id'] and event.get('physics_step')==point['command_step']
                    and event.get('target_position')==point['target_position'] and event.get('position_unit')==item['position_unit']
                    and event.get('cause')=='declared_at_step_schedule'
                    and event.get('trigger')=={'type':'at_step','physics_step':point['command_step']}
                    and isinstance(event.get('drive_readback'),dict))
                stop=point['by_step']
                hits.append(stop<len(actual) and abs(actual[stop]-point['target_position'])<=point['tolerance'])
            obj['forward_reverse_actual_targets']=len(hits)==len(points) and all(hits)
        contacts=set();zero=run.get('run_zero_absolute_physics_step')
        for frame in frames:
            for pair in frame.get('contact_pairs',[]):
                actors=pair.get('actor_paths');first=pair.get('first_callback_absolute_physics_step');last=pair.get('last_callback_absolute_physics_step')
                if (isinstance(actors,list) and len(actors)==2 and type(pair.get('count')) is int and pair['count']>0
                        and all(type(s) is int for s in (zero,first,last)) and zero<first<=last<=zero+steps):
                    contacts.add(frozenset(actors))
        obj['specified_contacts']=all(frozenset((item['child_body'],p)) in contacts for p in item.get('required_contact_actors',[]))
        outcomes[name]={'checks':obj,'passed':all(obj.values()),'observed_range':[min(actual),max(actual)],
                        'max_anchor_error_m':max(anchor),'final_position':actual[-1]}
    checks['all_objects_passed']=bool(outcomes) and all(o['passed'] for o in outcomes.values())
    return {'schema_version':1,'passed':all(checks.values()),'checks':checks,'objects':outcomes,
            'scope':'frozen imported single-DOF '+case['mode']+' motion, limits and optional direct contacts; at_step commands do not establish contact causality'}


def verify_run(directory,case_path=None):
    from ..cache import _sha256
    from ..run_integrity import verify as verify_inputs
    from ..evidence_integrity import verify as verify_evidence
    root=Path(directory);lock=json.loads((root/'run-lock.json').read_text())
    if lock.get('acceptance_case_file')!='acceptance-case.json':raise ValueError('articulated smoke requires its frozen JSON case')
    frozen=root/'acceptance-case.json';expected=lock.get('acceptance_case_sha256')
    if _sha256(frozen)!=expected or case_path is not None and _sha256(Path(case_path))!=expected:
        raise ValueError('articulated smoke acceptance case changed')
    run=json.loads((root/'result.json').read_text());case=json.loads(frozen.read_text());result=evaluate(run,case)
    result['checks']['bindings_pinned_to_run']=run.get('body_bindings')==lock.get('body_bindings') and isinstance(lock.get('body_bindings'),dict)
    from ..physics_binding import validate_asset_binding
    spec=json.loads((root/'spec.json').read_text())
    pinned=True
    try:
        for name,item in case['objects'].items():
            obj=spec['objects'][name];manifest=validate_asset_binding(obj['asset_binding'],require_dynamic=True,asset_path=obj['asset_path'])
            if manifest['profile_id']!='articulated_prop_v1':raise ValueError('wrong prepared profile')
            if item.get('prepared_manifest_sha256') is not None and item['prepared_manifest_sha256']!=obj['asset_binding']['manifest_sha256']:raise ValueError('prepared manifest differs from case')
            if item.get('source_ref') is not None and item['source_ref']!=manifest.get('source_ref'):raise ValueError('source selection differs from case')
    except (ValueError,KeyError,TypeError,OSError):pinned=False
    result['checks']['prepared_selection_pinned']=pinned
    inputs=verify_inputs(root);evidence=verify_evidence(root)
    result.update(input_integrity=inputs,evidence_integrity=evidence,case_pinned_to_run=True)
    result['passed']=bool(all(result['checks'].values()) and inputs['passed'] and evidence['passed'] and evidence['partial'] is False)
    return result
