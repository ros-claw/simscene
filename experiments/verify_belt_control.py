"""Check the paired moving-belt and zero-speed physical control runs."""
import hashlib,json,math,sys
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from verify_arm_drive_control import read

def normalized(spec):
    spec=json.loads(json.dumps(spec));spec.pop('requests',None)
    spec['objects']['belt']['conveyor']['speed_m_s']='<controlled>'
    return spec

def window(run,case):
    samples=[s for s in run.get('samples',[]) if case['window_start_s']<=s.get('simulation_time_s',-1)<=case['window_end_s'] and case['part_path'] in s.get('positions',{})]
    if len(samples)<2 or samples[0]['simulation_time_s']>case['window_start_s']+.1 or samples[-1]['simulation_time_s']<case['window_end_s']-.1:return None
    points=[s['positions'][case['part_path']] for s in samples]
    return {'x_displacement_m':points[-1][0]-points[0][0],
            'maximum_motion_m':max(math.dist(point,points[0]) for point in points),
            'start_time_s':samples[0]['simulation_time_s'],'end_time_s':samples[-1]['simulation_time_s']}

def evaluate(positive,positive_status,negative,negative_status,case_path):
    p,ps,pl,pr,pa=read(positive);n,ns,nl,nr,na=read(negative)
    data=Path(case_path).read_bytes();case=json.loads(data);digest=hashlib.sha256(data).hexdigest()
    statuses=[json.loads(Path(x).read_text()) for x in (positive_status,negative_status)]
    positive_window=window(p,case);negative_window=window(n,case)
    def contact(run):
        return any(k.startswith(case['part_id']+'|'+case['belt_path']+'|') and v.get('count',0)>0 for k,v in run.get('contact_counts',{}).items())
    checks={'both_processes_completed_without_crash':all(s.get('state')=='completed' and s.get('exit_code')==0 and s.get('run_id')==lock.get('run_id') for s,lock in zip(statuses,(pl,nl))),
            'input_locks_valid':verify_inputs(positive)['passed'] and verify_inputs(negative)['passed'],
            'same_pinned_case':pl.get('acceptance_case_sha256')==nl.get('acceptance_case_sha256')==digest,
            'same_scene_other_than_belt_speed':normalized(ps)==normalized(ns) and pr==nr and pa==na,
            'intended_belt_speeds':ps['objects']['belt']['conveyor']['speed_m_s']==case['expected_positive_speed_m_s'] and ns['objects']['belt']['conveyor']['speed_m_s']==0,
            'same_seed_and_full_duration':p.get('seed')==n.get('seed')==17 and p.get('actual_physics_steps')==n.get('actual_physics_steps')==p.get('requested_physics_steps')==n.get('requested_physics_steps')==case['physics_steps'],
            'belt_contact_observed':contact(p) and contact(n) and p.get('contacts_truncated') is False and n.get('contacts_truncated') is False,
            'positive_belt_moves_part':bool(positive_window and positive_window['x_displacement_m']>=case['minimum_moving_displacement_m']),
            'zero_belt_part_remains_still':bool(negative_window and negative_window['maximum_motion_m']<=case['maximum_stopped_displacement_m'])}
    return {'passed':all(checks.values()),'checks':checks,'positive_window':positive_window,'negative_window':negative_window,
            'scope':'one isolated object on a moving versus zero-speed conveyor; does not establish full multi-arm acceptance'}

if __name__=='__main__':
    if len(sys.argv)!=6:raise SystemExit('usage: verify_belt_control.py POS_DIR POS_STATUS NEG_DIR NEG_STATUS CASE')
    result=evaluate(*sys.argv[1:]);print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
