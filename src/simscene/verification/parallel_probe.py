"""Independent checks for a small parallel diagnostic, not stream acceptance."""
from .contact_pick import evaluate as parallel_pick
from .suction_pick import evaluate as suction_pick

def evaluate(run,spec,case):
    outcomes={}; active=[]; ids=[]
    for item in case['objects']:
        robot=item['robot_id'];ids.append(robot)
        single=dict(case['common'],**item)
        result=(parallel_pick if item['type']=='parallel' else suction_pick)(run,single)
        obj=spec.get('objects',{}).get(item['part_id'],{})
        result['checks']['class_matches_case']=obj.get('class_label')==item['class_label']
        if item['type']=='suction':
            phases=run.get('contact_counts',{})
            result['checks']['belt_contact_during_tracking']=any(k.startswith(item['part_id']+'|'+case['common']['belt_path']+'|') and robot+':'+str(item['tracking_phase']) in k.rsplit('|',1)[-1].split(',') and v.get('count',0)>0 for k,v in phases.items())
        result['passed']=all(result['checks'].values());outcomes[item['part_id']]=result
        follower=run.get('followers',{}).get(robot,{})
        transitions={x['index']:x['physics_step'] for x in follower.get('transitions',[])}
        if 0 in transitions and item['release_phase'] in transitions:active.append((transitions[0],transitions[item['release_phase']]))
    overlaps=bool(len(active)==len(case['objects']) and active and max(x[0] for x in active)<min(x[1] for x in active))
    robot_contacts=run.get('robot_contacts')
    cross=[]
    for key,value in (robot_contacts or {}).items():
        actors=key.split('|')[:2]
        matching={robot for robot in ids for actor in actors if actor.startswith('/World/'+robot+'/Asset')}
        if len(matching)>1 and value.get('count',0)>0:cross.append(key)
    checks={'all_objects_passed':bool(outcomes) and all(o['passed'] for o in outcomes.values()),
            'simultaneous_cycles_observed':overlaps,
            'no_arm_arm_contact':robot_contacts is not None and all(robot in run.get('monitored_robot_ids',[]) for robot in ids) and not cross,
            'physics_duration_completed':run.get('actual_physics_steps')==run.get('requested_physics_steps') and run.get('actual_physics_steps',0)>0,
            'contacts_not_truncated':run.get('contacts_truncated') is False}
    return {'checks':checks,'objects':outcomes,'cross_arm_contacts':cross,
            'parallel_steps':[max(a[0] for a in active),min(a[1] for a in active)] if overlaps else None,
            'passed':all(checks.values()),'scope':'one three-object parallel diagnostic; objects start near stations, not a continuous incoming stream or formal acceptance'}
