"""Conservative checks on one recorded experimental moving-belt pick."""
import math

def evaluate(run, case):
    follower=run.get('followers',{}).get(case['robot_id'],{})
    samples=run.get('samples',[])
    part_path=case['part_path']; robot_id=case['robot_id']
    contacts=run.get('contact_counts',{})
    transitions={x['index']:x['physics_step'] for x in follower.get('transitions',[])}
    def pos(sample):return sample.get('positions',{}).get(part_path)
    def phase_samples(index):
        if index not in transitions or index+1 not in transitions:return []
        lo,hi=transitions[index],transitions[index+1]
        return [s for s in samples if lo<=s['physics_steps']<=hi and pos(s) is not None]
    def counts(phase,needle):
        return [v for k,v in contacts.items() if k.startswith(case['part_id']+'|') and needle in k and k.endswith('|'+robot_id+':'+str(phase))]
    tracking=phase_samples(case['tracking_phase']); lift=phase_samples(case['lift_phase']); release=phase_samples(case['release_phase'])
    final=run.get('bounds',{}).get(case['part_id'])
    contained=bool(final and all(final['min'][i]>=case['bin_min'][i]-case['tolerance_m'] and final['max'][i]<=case['bin_max'][i]+case['tolerance_m'] for i in range(3)))
    position=run.get('positions',{}).get(part_path)
    last=[s for s in samples if pos(s) is not None and s['simulation_time_s']>=run.get('simulation_time_s',0)-case['stable_duration_s']]
    stable=bool(len(last)>=2 and last[-1]['simulation_time_s']-last[0]['simulation_time_s']>=case['stable_duration_s']-.1 and max(math.dist(pos(s),pos(last[-1])) for s in last)<=case['stable_displacement_m'])
    def sustained(phase,side):
        events=counts(phase,side+'_inner_finger')
        if phase not in transitions or phase+1 not in transitions:return False
        duration=transitions[phase+1]-transitions[phase]
        return bool(duration>0 and case['contact_fraction']>0 and events and sum(e['count'] for e in events)>=duration*case['contact_fraction'])
    wall_hit=any(counts(phase,'/bin_w') for phase in [case['lift_phase'],case['transfer_phase'],case['lower_phase']])
    checks={'sequence_completed':isinstance(follower.get('sequence_length'),int) and follower['sequence_length']>0 and follower.get('sequence_index')==follower['sequence_length'] and follower.get('sequence_error') is None,
            'belt_motion_observed':bool(len(tracking)>=2 and pos(tracking[-1])[0]-pos(tracking[0])[0]>=case['minimum_belt_displacement_m'] and counts(case['tracking_phase'],'/belt')),
            'lifted':bool(lift and tracking and max(pos(s)[2] for s in lift)-pos(tracking[-1])[2]>=case['minimum_lift_m']),
            'left_contact_during_lift':sustained(case['lift_phase'],'left'), 'right_contact_during_lift':sustained(case['lift_phase'],'right'),
            'left_contact_during_transfer':sustained(case['transfer_phase'],'left'),'right_contact_during_transfer':sustained(case['transfer_phase'],'right'),
            'no_bin_wall_contact_before_release':not wall_hit,
            'open_gripper':follower.get('gripper_joint_position') is not None and follower['gripper_joint_position']<=case['open_joint_max_rad'],
            'retracted':bool(position and follower.get('tcp_position') and math.dist(position,follower['tcp_position'])>=case['retract_distance_m']),
            'contained':contained,'stable':stable,'contacts_complete':run.get('contacts_truncated') is False}
    return {'checks':checks,'passed':all(checks.values()),'scope':'one moving object; does not validate robot-environment collisions, repeated reliability, or multi-arm behavior'}
