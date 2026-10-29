"""Check an exploratory repeated pick against a separate fixed case.

This is not the multi-arm acceptance ledger: no reliability or safety claim is
made beyond the explicitly recorded phases, contacts and final object states.
"""
from .contact_pick import evaluate as evaluate_object

def evaluate(run, case):
    robot=case['robot_id']
    transitions={entry['index']:entry['physics_step'] for entry in run.get('followers',{}).get(robot,{}).get('transitions',[])}
    events=run.get('spawn_events',[])
    outcomes={}
    for item in case['objects']:
        per_case=dict(case['common'],robot_id=robot,**item)
        result=evaluate_object(run,per_case)
        release_end=transitions.get(item['release_phase']+1)
        release_samples=[s for s in run.get('samples',[]) if release_end is not None and release_end<=s['physics_steps']<=release_end+5 and s.get('followers',{}).get(robot,{}).get('gripper_joint_position') is not None]
        direction=per_case['open_direction']
        result['checks']['gripper_open_at_release']=any(
            (direction=='less' and s['followers'][robot]['gripper_joint_position']<=per_case['open_threshold']) or
            (direction=='greater' and s['followers'][robot]['gripper_joint_position']>=per_case['open_threshold']) for s in release_samples)
        belt=[v for k,v in run.get('contact_counts',{}).items() if k.startswith(item['part_id']+'|/World/belt|') and robot+':'+str(item['tracking_phase']) in k.rsplit('|',1)[-1].split(',')]
        result['checks']['belt_contact_during_tracking']=any(v.get('count',0)>0 for v in belt)
        result['checks']['spawn_class_matches']=sum(1 for e in events if e.get('id')==item['part_id'] and e.get('class_label')==item['class_label'])==1
        result['passed']=all(result['checks'].values())
        outcomes[item['part_id']]=result
    expected={item['part_id'] for item in case['objects']}
    checks={'all_expected_objects_spawned_once':len(events)==len(expected) and {e.get('id') for e in events}==expected,
            'no_unspawned_objects':run.get('pending_spawn_ids')==[],
            'all_objects_passed':bool(outcomes) and all(result['passed'] for result in outcomes.values())}
    return {'checks':checks,'objects':outcomes,'passed':all(checks.values()),
            'scope':'one arm, two scheduled objects, one exploratory run; not multi-arm acceptance or reliability evidence'}
