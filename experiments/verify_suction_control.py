"""Compare paired real moving-belt runs with suction enabled and disabled."""
import hashlib,json,sys
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.verification.suction_pick import evaluate as evaluate_pick
from verify_arm_drive_control import read,normalize

def evaluate(positive,positive_status,negative,negative_status,case_path):
    p,ps,pl,pr,pa=read(positive);n,ns,nl,nr,na=read(negative)
    data=Path(case_path).read_bytes();case=json.loads(data);digest=hashlib.sha256(data).hexdigest()
    pstatus=json.loads(Path(positive_status).read_text());nstatus=json.loads(Path(negative_status).read_text())
    pos=evaluate_pick(p,case);neg=evaluate_pick(n,case);robot=case['robot_id'];part=case['part_path']
    events=n.get('followers',{}).get(robot,{}).get('suction_events',[])
    samples=[s.get('followers',{}).get(robot,{}).get('suction') for s in n.get('samples',[])]
    observed=[s for s in samples if isinstance(s,dict)]
    checks={'both_processes_completed_without_crash':all(s.get('state')=='completed' and s.get('exit_code')==0 and s.get('run_id')==lock.get('run_id') for s,lock in [(pstatus,pl),(nstatus,nl)]),
            'input_locks_valid':verify_inputs(positive)['passed'] and verify_inputs(negative)['passed'],
            'same_pinned_case':pl.get('acceptance_case_sha256')==nl.get('acceptance_case_sha256')==digest,
            'same_seed_and_duration':p.get('seed')==n.get('seed')==17 and p.get('actual_physics_steps')==n.get('actual_physics_steps')==p.get('requested_physics_steps')==n.get('requested_physics_steps')==1800,
            'same_scene_and_locked_models':normalize(ps,'suction_enabled')==normalize(ns,'suction_enabled') and pr==nr and pa==na,
            'only_negative_disables_suction':ps['objects'][robot]['pose_follower'].get('suction_enabled') is True and ns['objects'][robot]['pose_follower'].get('suction_enabled') is False,
            'no_suction_attachment_observed':bool(observed) and all(part not in s.get('gripped',[]) for s in observed) and any(e.get('event')=='close' and part not in e.get('gripped',[]) for e in events),
            'positive_physical_pick_passed':pos['passed'],
            'negative_failed_pick_and_did_not_reach_bin':not neg['passed'] and not neg['checks']['contained'] and n.get('task_status')=='failed' and bool(n['followers'][robot].get('sequence_error'))}
    return {'passed':all(checks.values()),'checks':checks,'positive':pos,'negative':neg,
            'scope':'one suction negative control with physics continuing after controller error; other mandatory negative controls and formal multi-arm acceptance are separate'}

if __name__=='__main__':
    if len(sys.argv)!=6:raise SystemExit('usage: verify_suction_control.py POS_DIR POS_STATUS NEG_DIR NEG_STATUS CASE')
    result=evaluate(*sys.argv[1:]);print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
