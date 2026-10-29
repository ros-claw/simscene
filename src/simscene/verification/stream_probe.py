"""Check a small fixed stream case without claiming formal reliability."""
from .contact_pick import evaluate as parallel_pick
from .suction_pick import evaluate as suction_pick
from itertools import product
import math

def evaluate(run,spec,case):
    outcomes={};cross=[];robots=sorted({item['robot_id'] for item in case['objects']});active={robot:[] for robot in robots}
    raw_archive=run.get('archived_objects',{})
    archived=raw_archive if isinstance(raw_archive,dict) else {}
    expected={item['part_id']:item['robot_id'] for item in case['objects']}
    for item in case['objects']:
        single=dict(case['common'],**item);robot=item['robot_id'];part=item['part_id']
        result=(parallel_pick if item['type']=='parallel' else suction_pick)(run,single)
        obj=spec.get('objects',{}).get(part,{})
        if part in archived:
            from .archive_evidence import matches_observation
            result['checks']['archive_matches_observation']=matches_observation(run,part,obj,archived[part])
        result['checks']['correct_class']=obj.get('class_label')==item['class_label']
        result['checks']['origin_upstream']=obj.get('position')==case['upstream_position']
        track=item['tracking_phase'];follower=run.get('followers',{}).get(robot,{})
        transitions={x['index']:x['physics_step'] for x in follower.get('transitions',[])}
        end=item['release_phase']+1
        if track in transitions and end in transitions and transitions[track]<transitions[end]:
            active[robot].append((transitions[track],transitions[end]))
        before=[s['positions'][item['part_path']][0] for s in run.get('samples',[]) if track in transitions and s['physics_steps']<=transitions[track] and item['part_path'] in s.get('positions',{})]
        result['checks']['passed_earlier_stations']=bool(before) and all(min(before)<x and max(before)>=x for x in item['pass_x'])
        if item['type']=='suction':
            result['checks']['belt_contact_during_tracking']=any(k.startswith(part+'|'+case['common']['belt_path']+'|') and robot+':'+str(track) in k.rsplit('|',1)[-1].split(',') and v.get('count',0)>0 for k,v in run.get('contact_counts',{}).items())
        result['passed']=all(result['checks'].values());outcomes[part]=result
    foreign=[];foreign_proximity=[];cross_proximity=[]
    for key,value in (run.get('robot_contacts') or {}).items():
        if not value.get('count',0):continue
        actors=key.split('|')[:2]
        matching_robots={robot for robot in robots for actor in actors if actor.startswith('/World/'+robot+'/Asset')}
        separation=value.get('minimum_separation_m')
        separated=(run.get('contact_geometry_incomplete') is False and isinstance(separation,(int,float))
                   and not isinstance(separation,bool) and math.isfinite(separation) and separation>0)
        if len(matching_robots)>1:(cross_proximity if separated else cross).append(key)
        for part,owner in expected.items():
            if '/World/'+part in actors and matching_robots-{owner}:
                (foreign_proximity if separated else foreign).append(key)
    belt=spec.get('objects',{}).get(case['belt_id'],{}).get('conveyor',{})
    from .contacts import forbidden_robot_environment
    environment_contacts=[key for robot in robots for key in forbidden_robot_environment(run.get('robot_contacts'),robot,case['common']['forbidden_environment_paths'])]
    events=run.get('spawn_events',[])
    spawn_steps={event.get('id'):event.get('physics_step') for event in events if isinstance(event,dict)}
    ledger=[];seen=set();duplicates=False
    cases={item['part_id']:item for item in case['objects']}
    for event in events:
        part=event.get('id'); outcome=outcomes.get(part)
        duplicate=part in seen;seen.add(part);duplicates=duplicates or duplicate
        state='invalid_duplicate' if duplicate else ('correct' if outcome and outcome['passed'] else 'failed_or_unfinished')
        bounds=run.get('bounds',{}).get(part)
        if state=='failed_or_unfinished' and bounds and part in cases:
            for other_id,other in cases.items():
                if other_id==part or other['class_label']==cases[part]['class_label']:continue
                tol=case['common']['tolerance_m']
                if all(bounds['min'][i]>=other['bin_min'][i]-tol and bounds['max'][i]<=other['bin_max'][i]+tol for i in range(3)):
                    state='wrong_bin';break
        ledger.append({'id':part,'class_label':event.get('class_label'),'state':state})
    correct=sum(item['state']=='correct' for item in ledger)
    per_robot={}
    for robot in robots:
        assigned=[entry for entry in ledger if expected.get(entry['id'])==robot]
        per_robot[robot]={'generated':len(assigned),'correct':sum(entry['state']=='correct' for entry in assigned)}
        per_robot[robot]['success_rate']=per_robot[robot]['correct']/len(assigned) if assigned and not duplicates else None
    overlaps=[]
    if all(active.values()):
        for periods in product(*(active[robot] for robot in robots)):
            first=max(start for start,end in periods);last=min(end for start,end in periods)
            if first<last:overlaps.append([first,last])
    longest=max(overlaps,key=lambda interval:interval[1]-interval[0]) if overlaps else None
    checks={'exact_spawn_order':[e.get('id') for e in events]==case['expected_spawn_order'],
            'spawn_classes_match':all(e.get('id') in cases and e.get('class_label')==cases[e['id']]['class_label'] for e in events),
            'archive_records_match_spawned_objects':isinstance(raw_archive,dict) and set(archived).issubset(seen) and all(isinstance(event,dict) and event.get('terminal_state')=='correct' and type(event.get('physics_step')) is int and type(spawn_steps.get(part)) is int and event['physics_step']>=spawn_steps[part] and '/World/'+part.replace('-','_') not in run.get('positions',{}) for part,event in archived.items()),
            'no_pending_spawns':run.get('pending_spawn_ids')==[],
            'nonzero_belt':belt.get('speed_m_s',0)>=case['minimum_belt_speed'],
            'all_objects_passed':bool(outcomes) and all(o['passed'] for o in outcomes.values()),
            'no_arm_arm_contact':run.get('robot_contacts') is not None and all(r in run.get('monitored_robot_ids',[]) for r in robots) and not cross,
            'no_forbidden_robot_environment_contact':run.get('robot_contacts') is not None and all(r in run.get('monitored_robot_ids',[]) for r in robots) and not environment_contacts,
            'no_wrong_robot_contact':not foreign,
            'physics_duration_completed':run.get('actual_physics_steps')==run.get('requested_physics_steps') and run.get('actual_physics_steps',0)>0,
            'contacts_not_truncated':run.get('contacts_truncated') is False}
    thresholds=case.get('acceptance_thresholds')
    if thresholds is not None:
        # Failures remain in the generated denominator; unexpected or missing
        # spawns independently fail the exact-order check above.
        checks.pop('all_objects_passed')
        checks['minimum_overall_success_rate']=bool(ledger and not duplicates and correct/len(ledger)>=thresholds['overall_success_rate'])
        checks['minimum_per_robot_success_rate']=bool(per_robot) and all(v['success_rate'] is not None and v['success_rate']>=thresholds['per_robot_success_rate'] for v in per_robot.values())
        checks['no_wrong_bin']=not any(entry['state']=='wrong_bin' for entry in ledger)
        checks['simultaneous_cycles_observed']=bool(longest and longest[1]-longest[0]>=thresholds['minimum_parallel_steps'])
    return {'checks':checks,'objects':outcomes,'cross_arm_contacts':cross,'wrong_robot_contacts':foreign,
            'cross_arm_proximity':cross_proximity,'wrong_robot_proximity':foreign_proximity,'environment_contacts':environment_contacts,
            'ledger':{'generated':len(ledger),'correct':correct,'wrong_bin':sum(x['state']=='wrong_bin' for x in ledger),
                      'failed_or_unfinished':sum(x['state'] in ('failed_or_unfinished','invalid_duplicate') for x in ledger),
                      'success_rate':correct/len(ledger) if ledger and not duplicates else None,'per_robot':per_robot,'objects':ledger},
            'parallel_steps':longest,
            'passed':all(checks.values()),'scope':'single stream run; repeated-run reliability and formal acceptance require separate checks'}
