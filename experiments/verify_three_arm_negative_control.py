"""Compare a completed three-arm negative control with its positive baseline."""
import copy
import json
import sys
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
from simscene.verification.case_runner import evaluate

if len(sys.argv)!=4 or sys.argv[3] not in ('disable_drive','disable_suction','stop_belt'):
    raise SystemExit('usage: verify_three_arm_negative_control.py BASELINE_DIR NEGATIVE_DIR MODE')
positive,negative=map(Path,sys.argv[1:3]);mode=sys.argv[3]
def read(root,name):return json.loads((root/name).read_text())
p,n=read(positive,'result.json'),read(negative,'result.json')
ps,ns=read(positive,'spec.json'),read(negative,'spec.json')
pl,nl=read(positive,'run-lock.json'),read(negative,'run-lock.json')
pr,nr=evaluate(positive),evaluate(negative)
def normalized(spec, run_root):
    value=copy.deepcopy(spec)
    for field in ('scene_id','revision','requests'):value.pop(field,None)
    for obj in value['objects'].values():
        if obj.get('kind')=='asset':
            path=Path(obj['asset_path']).resolve()
            try:obj['asset_path']='<run>/'+path.relative_to(run_root.resolve()).as_posix()
            except ValueError:pass  # external assets must remain exactly equal
        cfg=obj.get('pose_follower')
        if cfg:
            cfg.pop('arm_drives_enabled',None);cfg.pop('suction_enabled',None);cfg['model_directory']='<frozen-model>'
            if 'gripper_urdf' in cfg:cfg['gripper_urdf']=Path(cfg['gripper_urdf']).name
    value['objects']['belt']['conveyor']['speed_m_s']='<speed>'
    return value
def model_hashes(root):
    return {k:v['files_sha256'] for k,v in read(root,'runtime-lock.json').items()}
def displacement(run,first,last):
    values=[s['positions']['/World/part0000'][0] for s in run['samples'] if first<=s['physics_steps']<=last and '/World/part0000' in s.get('positions',{})]
    return values[-1]-values[0] if len(values)>1 else None
checks={'same_case':pl.get('acceptance_case_sha256')==nl.get('acceptance_case_sha256') and bool(pl.get('acceptance_case_sha256')),
        'same_seed':p.get('seed')==n.get('seed')==17,'same_scene_except_control':normalized(ps,positive)==normalized(ns,negative),
        'same_frozen_worker_and_models':pl.get('worker_code_sha256')==nl.get('worker_code_sha256') and bool(pl.get('worker_code_sha256')) and model_hashes(positive)==model_hashes(negative),
        'same_locked_assets':read(positive,'asset-lock.json')==read(negative,'asset-lock.json'),
        'input_and_output_integrity':all(x['passed'] for x in (verify_inputs(positive),verify_inputs(negative),verify_outputs(positive),verify_outputs(negative))),
        'both_processes_exited_normally':all(read(root,'job-status.json').get('state')=='completed' and read(root,'job-status.json').get('exit_code')==0 and read(root,'job-status.json').get('exit_code_inferred') is False for root in (positive,negative)),
        'both_physics_runs_complete':all(run.get('requested_physics_steps')==run.get('actual_physics_steps') and run.get('actual_physics_steps',0)>0 for run in (p,n))}
details={}
if mode=='disable_drive':
    cfgp=ps['objects']['kawasaki']['pose_follower'];cfgn=ns['objects']['kawasaki']['pose_follower']
    gains=n['followers']['kawasaki'].get('arm_drive_gains') or {};names=gains.get('joint_names') or []
    checks['only_drive_disabled']=cfgp.get('arm_drives_enabled',True) is True and cfgn.get('arm_drives_enabled') is False
    checks['measured_drive_gains_zero']=bool(names) and all(isinstance(gains.get(k),list) and len(gains[k])==len(names) and all(abs(x)<=1e-6 for x in gains[k]) for k in ('stiffness','damping'))
    checks['positive_red_pick']=pr['objects']['part0002']['passed'] and p.get('archived_objects',{}).get('part0002',{}).get('physics_step',10**9)<=n['actual_physics_steps']
    checks['negative_red_not_successful']=not nr['objects']['part0002']['passed'] and 'part0002' not in n.get('archived_objects',{})
elif mode=='disable_suction':
    cfgp=ps['objects']['ur10']['pose_follower'];cfgn=ns['objects']['ur10']['pose_follower']
    checks['only_suction_disabled']=cfgp.get('suction_enabled',True) is True and cfgn.get('suction_enabled') is False
    checks['positive_blue_pick']=pr['objects']['part0000']['passed'] and p.get('archived_objects',{}).get('part0000',{}).get('physics_step',10**9)<=n['actual_physics_steps']
    checks['negative_blue_not_successful']=not nr['objects']['part0000']['passed'] and 'part0000' not in n.get('archived_objects',{})
    details['negative_suction_events']=n['followers']['ur10'].get('suction_events',[])
    checks['no_negative_attachment']=not any(event.get('gripped') for event in details['negative_suction_events'])
else:
    checks['belt_only_disabled']=ps['objects']['belt']['conveyor']['speed_m_s']>0 and ns['objects']['belt']['conveyor']['speed_m_s']==0
    def spawned(run):
        matches=[event.get('physics_step') for event in run.get('spawn_events',[]) if event.get('id')=='part0000']
        return matches[0] if len(matches)==1 and type(matches[0]) is int else None
    pp,np=spawned(p),spawned(n)
    checks['matching_blue_spawn_time']=pp is not None and pp==np
    dp=displacement(p,pp+119,pp+539) if pp is not None else None
    dn=displacement(n,np+119,np+539) if np is not None else None
    details['displacement_m']={'baseline':dp,'zero_belt':dn};details['spawn_step']=pp
    checks['belt_motion_stops']=dp is not None and dn is not None and dp>=.1 and abs(dn)<=.005
report={'passed':all(checks.values()),'mode':mode,'checks':checks,'details':details,
        'scope':'Paired physical negative control in a three-arm scene; does not substitute for the multi-seed suite or swept-volume safety.'}
print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)
