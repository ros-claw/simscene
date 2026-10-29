"""Compare paired actual runs for the disabled-arm-drive negative control."""
import hashlib,json,sys
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.verification.moving_pick import evaluate as evaluate_pick

def read(directory):
    root=Path(directory)
    return (json.loads((root/'result.json').read_text()),json.loads((root/'spec.json').read_text()),
            json.loads((root/'run-lock.json').read_text()),json.loads((root/'runtime-lock.json').read_text()),
            json.loads((root/'asset-lock.json').read_text()))

def normalize(spec,flag='arm_drives_enabled'):
    data=json.loads(json.dumps(spec));objects=data['objects']
    data.pop('requests',None)
    for obj in objects.values():
        cfg=obj.get('pose_follower')
        if cfg:
            cfg.pop(flag,None)
            cfg['model_directory']='<snapshot>'
            if 'gripper_urdf' in cfg:cfg['gripper_urdf']=Path(cfg['gripper_urdf']).name
    return data

def evaluate(positive,positive_status,negative,negative_status,case_path):
    p,ps,pl,pr,pa=read(positive);n,ns,nl,nr,na=read(negative)
    with open(case_path,'rb') as f:case_bytes=f.read()
    case=json.loads(case_bytes);digest=hashlib.sha256(case_bytes).hexdigest()
    pstatus=json.loads(Path(positive_status).read_text());nstatus=json.loads(Path(negative_status).read_text())
    pos=evaluate_pick(p,case);neg=evaluate_pick(n,case)
    robot=case['robot_id'];gains=n.get('followers',{}).get(robot,{}).get('arm_drive_gains') or {}
    vectors=[gains.get('stiffness'),gains.get('damping')]
    checks={'both_processes_completed_without_crash':all(s.get('state')=='completed' and s.get('exit_code')==0 and s.get('run_id')==lock.get('run_id') for s,lock in [(pstatus,pl),(nstatus,nl)]),
            'input_locks_valid':verify_inputs(positive)['passed'] and verify_inputs(negative)['passed'],
            'same_pinned_case':pl.get('acceptance_case_sha256')==nl.get('acceptance_case_sha256')==digest,
            'same_seed_and_duration':p.get('seed')==n.get('seed')==17 and p.get('actual_physics_steps')==n.get('actual_physics_steps')==p.get('requested_physics_steps')==n.get('requested_physics_steps')==2000,
            'same_scene_and_locked_models':normalize(ps)==normalize(ns) and pr==nr and pa==na,
            'only_negative_disables_arm_drives':ps['objects'][robot]['pose_follower'].get('arm_drives_enabled') is True and ns['objects'][robot]['pose_follower'].get('arm_drives_enabled') is False,
            'measured_arm_gains_zero':bool(gains.get('joint_names')) and all(isinstance(v,list) and len(v)==len(gains['joint_names']) and all(isinstance(x,(int,float)) and abs(x)<=1e-6 for x in v) for v in vectors),
            'positive_physical_pick_passed':pos['passed'],
            'negative_failed_pick_and_did_not_reach_bin':not neg['passed'] and not neg['checks']['contained'] and n.get('task_status')=='failed' and bool(n['followers'][robot].get('sequence_error'))}
    return {'passed':all(checks.values()),'checks':checks,'positive':pos,'negative':neg,
            'scope':'one arm-drive negative control with physics continuing after controller error; other mandatory negative controls and formal multi-arm acceptance are separate'}

if __name__=='__main__':
    if len(sys.argv)!=6:raise SystemExit('usage: verify_arm_drive_control.py POS_DIR POS_STATUS NEG_DIR NEG_STATUS CASE')
    result=evaluate(*sys.argv[1:]);print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
