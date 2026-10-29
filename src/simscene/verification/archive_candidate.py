"""Conservative, independent-case checks before reclaiming a placed object."""
import math
from .contact_pick import evaluate as contact_pick
from .suction_pick import evaluate as suction_pick
from .archive_evidence import matches_observation

def validate_case(scene,case):
    if not isinstance(case,dict) or not isinstance(case.get('objects'),list) or not case['objects'] or not isinstance(case.get('common'),dict):
        raise ValueError('archiving requires a pinned stream case')
    common=case['common']
    required={'belt_path','forbidden_environment_paths','retract_distance_m','minimum_lift_m','minimum_belt_displacement_m'}
    if not required.issubset(common):raise ValueError('archive case is missing physical evidence requirements')
    forbidden=common.get('forbidden_environment_paths');belt=common.get('belt_path')
    if not isinstance(belt,str) or not belt.startswith('/World/') or not isinstance(forbidden,list) or belt not in forbidden or not all(isinstance(x,str) and x.startswith('/World/') for x in forbidden):
        raise ValueError('archive case must monitor the belt and forbidden environment paths')
    for key in ('retract_distance_m','minimum_lift_m','minimum_belt_displacement_m'):
        value=common[key]
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0:raise ValueError('archive case requires positive '+key)
    for key,limit in [('max_linear_velocity_m_s',.05),('max_angular_velocity_rad_s',.5),('stable_displacement_m',.003),('tolerance_m',.002)]:
        value=common.get(key)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not 0<value<=limit:
            raise ValueError('archiving requires conservative finite '+key)
    duration=common.get('stable_duration_s')
    if not isinstance(duration,(int,float)) or isinstance(duration,bool) or not math.isfinite(duration) or duration<1:raise ValueError('archiving requires at least one second of stability')
    scene_objects=scene.get('objects',{});items=case['objects'];ids=[]
    for item in items:
        if not isinstance(item,dict) or item.get('type') not in ('parallel','suction') or item.get('evidence_per_item') is not True:
            raise ValueError('archiving requires per-item parallel or suction evidence')
        required_item={'part_id','part_path','robot_id','class_label','tracking_phase','release_phase','pass_x','bin_min','bin_max'}
        required_item|=({'grip_phase','lift_phase','transfer_phase','left_finger','right_finger','contact_fraction','open_direction','open_threshold'} if item['type']=='parallel' else {'held_phases'})
        if not required_item.issubset(item):raise ValueError('archive item is missing physical evidence requirements')
        def numbers(value,n):return isinstance(value,list) and len(value)==n and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value)
        if not numbers(item['bin_min'],3) or not numbers(item['bin_max'],3) or any(a>=b for a,b in zip(item['bin_min'],item['bin_max'])) or not isinstance(item['pass_x'],list) or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in item['pass_x']):
            raise ValueError('archive case has invalid bin bounds or station coordinates')
        if item['type']=='parallel':
            fraction=item['contact_fraction'];threshold=item['open_threshold']
            if not isinstance(fraction,(int,float)) or isinstance(fraction,bool) or not math.isfinite(fraction) or not .8<=fraction<=1 or item['open_direction'] not in ('less','greater') or not isinstance(threshold,(int,float)) or isinstance(threshold,bool) or not math.isfinite(threshold):
                raise ValueError('archive case requires sustained contacts and a valid open-gripper threshold')
        elif not isinstance(item['held_phases'],list) or not item['held_phases']:
            raise ValueError('archive suction case requires retained phases')
        part=item.get('part_id');robot=item.get('robot_id');obj=scene_objects.get(part,{})
        follower=scene_objects.get(robot,{}).get('pose_follower',{})
        release=item.get('release_phase');track=item.get('tracking_phase')
        if not isinstance(part,str) or not isinstance(robot,str) or not isinstance(item.get('class_label'),str) or not item['class_label'] or obj.get('kind') not in ('box','sphere') or not obj.get('dynamic') or not obj.get('spawn_step',0)>0:
            raise ValueError('archive items must name scheduled dynamic primitives')
        if item.get('part_path')!='/World/'+part.replace('-','_') or obj.get('class_label')!=item.get('class_label') or obj.get('position')!=case.get('upstream_position'):
            raise ValueError('archive case does not match item identity, class or origin')
        if not isinstance(follower,dict) or follower.get('monitor_collisions') is not True or type(release) is not int or type(track) is not int or track<0 or release<=track:
            raise ValueError('archive case requires monitored robot and valid phases')
        sequence=follower.get('sequence',[])
        if not isinstance(sequence,list) or release+2>len(sequence) or track>=len(sequence) or sequence[track].get('object')!=part:
            raise ValueError('archive phase does not match robot sequence')
        ids.append(part)
    expected=case.get('expected_spawn_order')
    scheduled=[name for name,obj in scene_objects.items() if isinstance(obj,dict) and obj.get('dynamic') and obj.get('spawn_step',0)>0]
    scheduled.sort(key=lambda name:scene_objects[name]['spawn_step'])
    steps=[scene_objects[name]['spawn_step'] for name in scheduled]
    if len(ids)!=len(set(ids)) or not isinstance(expected,list) or expected!=scheduled or set(ids)!=set(scheduled) or any(a>=b for a,b in zip(steps,steps[1:])):
        raise ValueError('archive case must cover every scheduled workpiece in spawn order')

def evaluate_item(run,spec,case,item,event):
    part=item['part_id'];robot=item['robot_id'];path=item['part_path'];single=dict(case['common'],**item)
    result=(contact_pick if item['type']=='parallel' else suction_pick)(run,single)
    obj=spec.get('objects',{}).get(part,{})
    result['checks']['class_and_origin_match']=obj.get('class_label')==item['class_label'] and obj.get('position')==case['upstream_position']
    follower=run.get('followers',{}).get(robot,{})
    transitions={x['index']:x['physics_step'] for x in follower.get('transitions',[])}
    track=item['tracking_phase']
    before=[s['positions'][path][0] for s in run.get('samples',[]) if track in transitions and s['physics_steps']<=transitions[track] and path in s.get('positions',{})]
    result['checks']['passed_earlier_stations']=bool(before) and all(min(before)<x and max(before)>=x for x in item['pass_x'])
    if item['type']=='suction':
        belt=case['common']['belt_path']
        result['checks']['belt_contact_during_tracking']=any(k.startswith(part+'|'+belt+'|') and robot+':'+str(track) in k.rsplit('|',1)[-1].split(',') and value.get('count',0)>0 for k,value in (run.get('contact_counts') or {}).items())
    robot_ids={x['robot_id'] for x in case['objects']}
    foreign=[]
    for key,value in (run.get('robot_contacts') or {}).items():
        actors=key.split('|')[:2]
        if value.get('count',0) and path in actors and any(r!=robot and any(a.startswith('/World/'+r+'/Asset') for a in actors) for r in robot_ids):foreign.append(key)
    result['checks']['no_wrong_robot_contact']=not foreign
    result['checks']['terminal_observation_matches_geometry']=matches_observation(run,part,obj,event)
    result['passed']=all(result['checks'].values())
    return result
