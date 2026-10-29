"""Conservative single-object parallel-gripper physical evidence checks."""
import math

def evaluate(run,case):
    robot=case['robot_id'];part=case['part_path']; follower=run.get('followers',{}).get(robot,{})
    transitions={x['index']:x['physics_step'] for x in follower.get('transitions',[])}
    samples=run.get('samples',[]);contacts=run.get('contact_counts',{})
    def phase_samples(i):
        if i not in transitions or i+1 not in transitions:return []
        return [s for s in samples if transitions[i]<=s['physics_steps']<=transitions[i+1] and part in s.get('positions',{})]
    def contact(phase,body):
        return [v for k,v in contacts.items() if k.startswith(case['part_id']+'|') and body in k and robot+':'+str(phase) in k.rsplit('|',1)[-1].split(',')]
    def sustained(phase,body):
        if phase not in transitions or phase+1 not in transitions:return False
        duration=transitions[phase+1]-transitions[phase]
        return duration>0 and case['contact_fraction']>0 and sum(v['count'] for v in contact(phase,body)) >= duration*case['contact_fraction']
    lift=phase_samples(case['lift_phase']); initial=phase_samples(case['grip_phase'])
    archived=run.get('archived_objects',{}).get(case['part_id'])
    end_time=archived.get('simulation_time_s',-1) if isinstance(archived,dict) else run.get('simulation_time_s',0)
    if not isinstance(end_time,(int,float)) or isinstance(end_time,bool) or not math.isfinite(end_time):end_time=-1
    bounds=archived.get('bounds') if isinstance(archived,dict) else run.get('bounds',{}).get(case['part_id'])
    contained=bool(bounds and all(bounds['min'][i]>=case['bin_min'][i]-case['tolerance_m'] and bounds['max'][i]<=case['bin_max'][i]+case['tolerance_m'] for i in range(3)))
    tail=[s for s in samples if part in s.get('positions',{}) and end_time-case['stable_duration_s']<=s['simulation_time_s']<=end_time+1e-9]
    stable=bool(len(tail)>=2 and tail[-1]['simulation_time_s']-tail[0]['simulation_time_s']>=case['stable_duration_s']-.1 and max(math.dist(s['positions'][part],tail[-1]['positions'][part]) for s in tail)<=case['stable_displacement_m'])
    position=run.get('positions',{}).get(part);joint=follower.get('gripper_joint_position');seq=follower.get('sequence_length')
    contacts_robot=run.get('robot_contacts')
    from .contacts import forbidden_robot_environment
    phase_range=(case['tracking_phase'],case['release_phase']+1) if case.get('evidence_per_item') else None
    forbidden=forbidden_robot_environment(contacts_robot,robot,case['forbidden_environment_paths'],phase_range)
    if joint is None: opened=False
    elif case['open_direction']=='greater':opened=joint>=case['open_threshold']
    elif case['open_direction']=='less':opened=joint<=case['open_threshold']
    else:opened=False
    checks={'sequence_completed':isinstance(seq,int) and seq>0 and follower.get('sequence_index')==seq and follower.get('sequence_error') is None,
        'lifted':bool(initial and lift and max(s['positions'][part][2] for s in lift)-initial[-1]['positions'][part][2]>=case['minimum_lift_m']),
        'left_lift_contact':sustained(case['lift_phase'],case['left_finger']), 'right_lift_contact':sustained(case['lift_phase'],case['right_finger']),
        'left_transfer_contact':sustained(case['transfer_phase'],case['left_finger']), 'right_transfer_contact':sustained(case['transfer_phase'],case['right_finger']),
        'opened':opened, 'retracted':bool(position and follower.get('tcp_position') and math.dist(position,follower['tcp_position'])>=case['retract_distance_m']),
        'contained':contained,'stable':stable,'no_forbidden_robot_environment_contact':contacts_robot is not None and robot in run.get('monitored_robot_ids',[]) and not forbidden,
        'contacts_not_truncated':run.get('contacts_truncated') is False}
    if 'tracking_phase' in case:
        tracking=phase_samples(case['tracking_phase'])
        checks['belt_motion_observed']=bool(len(tracking)>=2 and tracking[-1]['positions'][part][0]-tracking[0]['positions'][part][0]>=case['minimum_belt_displacement_m'])
        if 'belt_path' in case:
            checks['belt_contact_during_tracking']=any(v.get('count',0)>0 for v in contact(case['tracking_phase'],case['belt_path']))
    if case.get('evidence_per_item'):
        release=case['release_phase'];end=transitions.get(release+1)
        checks['sequence_completed']=release+2 in transitions
        release_frames=[s for s in samples if end is not None and end<=s['physics_steps']<=end+5 and s.get('followers',{}).get(robot,{}).get('gripper_joint_position') is not None]
        direction=case['open_direction'];threshold=case['open_threshold']
        checks['opened']=any((direction=='less' and s['followers'][robot]['gripper_joint_position']<=threshold) or (direction=='greater' and s['followers'][robot]['gripper_joint_position']>=threshold) for s in release_frames)
        retract=phase_samples(release+1)
        checks['retracted']=any(s.get('followers',{}).get(robot,{}).get('tcp_position') and math.dist(s['positions'][part],s['followers'][robot]['tcp_position'])>=case['retract_distance_m'] for s in retract)
        if archived is not None:
            checks['archive_after_retraction']=bool(isinstance(archived,dict) and release+2 in transitions and isinstance(archived.get('physics_step'),int) and archived['physics_step']>=transitions[release+2] and isinstance(end_time,(int,float)) and end_time>=0)
    if 'max_linear_velocity_m_s' in case or 'max_angular_velocity_rad_s' in case:
        from .settling import stable as kinematic_stability
        checks['linear_and_angular_speed_stable']=bool('max_linear_velocity_m_s' in case and 'max_angular_velocity_rad_s' in case and kinematic_stability(samples,part,end_time,case['stable_duration_s'],case['max_linear_velocity_m_s'],case['max_angular_velocity_rad_s']))
    return {'checks':checks,'passed':all(checks.values()),'forbidden_contacts':forbidden,'scope':'one object; no repeated-run reliability, full self-collision or multi-arm validation'}
