"""Evidence-based checks for an experimental suction pick-place run."""
import math

def evaluate(run,case):
    follower=run.get('followers',{}).get(case['robot_id'],{})
    events=follower.get('suction_events',[]);part=case['part_path'];seq=follower.get('sequence_length')
    close=[e for e in events if e.get('event')=='close' and part in e.get('gripped',[])]
    opened=[e for e in events if e.get('event')=='open' and not e.get('gripped',[])]
    retained=[]
    for phase in case['held_phases']:
        frames=[s for s in run.get('samples',[]) if s.get('followers',{}).get(case['robot_id'],{}).get('sequence_index')==phase]
        retained.append(bool(frames) and all(part in (s['followers'][case['robot_id']].get('suction') or {}).get('gripped',[]) for s in frames))
    archived=run.get('archived_objects',{}).get(case['part_id'])
    end_time=archived.get('simulation_time_s',-1) if isinstance(archived,dict) else run.get('simulation_time_s',0)
    if not isinstance(end_time,(int,float)) or isinstance(end_time,bool) or not math.isfinite(end_time):end_time=-1
    bounds=archived.get('bounds') if isinstance(archived,dict) else run.get('bounds',{}).get(case['part_id'])
    contained=bool(bounds and all(bounds['min'][i]>=case['bin_min'][i]-case['tolerance_m'] and bounds['max'][i]<=case['bin_max'][i]+case['tolerance_m'] for i in range(3)))
    samples=[s for s in run.get('samples',[]) if part in s.get('positions',{}) and end_time-case['stable_duration_s']<=s['simulation_time_s']<=end_time+1e-9]
    stable=bool(len(samples)>=2 and samples[-1]['simulation_time_s']-samples[0]['simulation_time_s']>=case['stable_duration_s']-.1 and max(math.dist(s['positions'][part],samples[-1]['positions'][part]) for s in samples)<=case['stable_displacement_m'])
    if 'tracking_phase' in case:
        tracking=[s for s in run.get('samples',[]) if s.get('followers',{}).get(case['robot_id'],{}).get('sequence_index')==case['tracking_phase'] and part in s.get('positions',{})]
        belt_motion=bool(len(tracking)>=2 and tracking[-1]['positions'][part][0]-tracking[0]['positions'][part][0]>=case['minimum_belt_displacement_m'])
    else: belt_motion=None
    robot_contacts=run.get('robot_contacts')
    from .contacts import forbidden_robot_environment
    defaults=['/World/bin_','/World/table']+(['/World/belt'] if 'tracking_phase' in case else [])
    paths=case.get('forbidden_environment_paths',defaults)
    if not isinstance(paths,list) or not paths or not all(isinstance(path,str) and path.startswith('/World/') for path in paths):
        paths=[]
        invalid_forbidden_paths=True
    else:
        paths=list(dict.fromkeys(paths+defaults))
        invalid_forbidden_paths=False
    phase_range=(case['tracking_phase'],case['release_phase']+1) if case.get('evidence_per_item') else None
    forbidden=forbidden_robot_environment(robot_contacts,case['robot_id'],paths,phase_range)
    checks={'sequence_completed':isinstance(seq,int) and seq>0 and follower.get('sequence_index')==seq and follower.get('sequence_error') is None,
            'suction_acquired_target':bool(close),'retained_in_each_held_phase':all(retained) and bool(retained),
            'suction_released':bool(opened) and not any(e.get('event')=='lost' for e in events),
            'contained':contained,'stable':stable,'no_robot_belt_table_or_bin_contact':not invalid_forbidden_paths and robot_contacts is not None and case['robot_id'] in run.get('monitored_robot_ids',[]) and not forbidden,
            'contacts_not_truncated':run.get('contacts_truncated') is False}
    if belt_motion is not None: checks['belt_motion_observed']=belt_motion
    if case.get('evidence_per_item'):
        transitions={e['index']:e['physics_step'] for e in follower.get('transitions',[])}
        release=case['release_phase'];close_phase=case['tracking_phase']+1
        checks['sequence_completed']=release+2 in transitions
        checks['suction_acquired_target']=bool(close_phase in transitions and close_phase+1 in transitions and any(transitions[close_phase]<=e.get('physics_step',-1)<=transitions[close_phase+1] for e in close))
        checks['suction_released']=bool(release in transitions and release+1 in transitions and any(transitions[release]<=e.get('physics_step',-1)<=transitions[release+1] for e in opened) and not any(e.get('event')=='lost' and transitions.get(close_phase,0)<=e.get('physics_step',-1)<=transitions.get(release+1,-1) for e in events))
        if release+1 in transitions and release+2 in transitions:
            retract=[s for s in run.get('samples',[]) if transitions[release+1]<=s.get('physics_steps',-1)<=transitions[release+2] and part in s.get('positions',{})]
            checks['retracted']=any(s.get('followers',{}).get(case['robot_id'],{}).get('tcp_position') and math.dist(s['positions'][part],s['followers'][case['robot_id']]['tcp_position'])>=case['retract_distance_m'] for s in retract)
        else:checks['retracted']=False
        if archived is not None:
            checks['archive_after_retraction']=bool(isinstance(archived,dict) and release+2 in transitions and isinstance(archived.get('physics_step'),int) and archived['physics_step']>=transitions[release+2] and isinstance(end_time,(int,float)) and end_time>=0)
    if 'minimum_lift_m' in case:
        minimum=case['minimum_lift_m'];tracking=case.get('tracking_phase');held=case.get('held_phases',[])
        transitions={e['index']:e['physics_step'] for e in follower.get('transitions',[])}
        close_phase=tracking+1 if type(tracking) is int else None
        lift_phase=held[0] if isinstance(held,list) and held and type(held[0]) is int else None
        def positions(phase):
            if phase not in transitions or phase+1 not in transitions:return []
            return [s['positions'][part] for s in run.get('samples',[]) if transitions[phase]<=s.get('physics_steps',-1)<=transitions[phase+1] and part in s.get('positions',{})]
        initial=positions(close_phase) if close_phase is not None else []
        lifted=positions(lift_phase) if lift_phase is not None else []
        checks['lifted']=bool(type(minimum) in (int,float) and math.isfinite(minimum) and minimum>0 and initial and lifted and max(p[2] for p in lifted)-initial[-1][2]>=minimum)
    if 'max_linear_velocity_m_s' in case or 'max_angular_velocity_rad_s' in case:
        from .settling import stable as kinematic_stability
        checks['linear_and_angular_speed_stable']=bool('max_linear_velocity_m_s' in case and 'max_angular_velocity_rad_s' in case and kinematic_stability(run.get('samples',[]),part,end_time,case['stable_duration_s'],case['max_linear_velocity_m_s'],case['max_angular_velocity_rad_s']))
    return {'checks':checks,'passed':all(checks.values()),'forbidden_contacts':forbidden,
            'scope':'single object; does not establish general path safety, stream throughput or multi-arm acceptance'}
