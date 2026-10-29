"""Independent, fail-closed gate for the documented three-arm acceptance.

This combines four saved runs and the case snapshotted before each run. It does
not manufacture missing state, repair evidence, or replace physical inspection.
"""
import hashlib,json,math
from collections import Counter
from pathlib import Path
from .stream_probe import evaluate as evaluate_stream
from ..run_integrity import verify as verify_inputs
from ..evidence_integrity import verify as verify_evidence

SEEDS={17,29,43}
# This acceptance suite is bound to the three specified robot models and their
# independently reviewed mechanism exceptions. A caller-supplied case cannot
# make a new collision exemption and still call this particular suite passed.
COLLISION_POLICY={
    'mechanical_pairs':{
        'kawasaki':[['left_inner_knuckle','left_inner_finger'],['right_inner_knuckle','right_inner_finger'],
                    ['left_inner_knuckle','left_outer_knuckle'],['right_inner_knuckle','right_outer_knuckle'],
                    ['left_inner_knuckle','right_inner_knuckle'],['link5','onrobot_rg2_base_link']],
        'franka':[],'ur10':[]},
    'grasp_bodies':{'kawasaki':['left_inner_finger','right_inner_finger'],'franka':['panda_leftfinger','panda_rightfinger'],'ur10':['ee_link']},
    'allowed_mechanical_contacts':{'kawasaki':[],'franka':[['panda_leftfinger','panda_rightfinger']],'ur10':[]},
}

def _load(path):
    path=Path(path)
    data=path.read_bytes()
    if path.suffix.lower()=='.json':case=json.loads(data)
    else:
        import yaml
        case=yaml.safe_load(data)
    if not isinstance(case,dict):raise ValueError('acceptance case must be a mapping')
    return case,hashlib.sha256(data).hexdigest()

def _model_hash(record):
    if record.get('kind')=='snapshot':return record.get('package_sha256')
    if record.get('kind')=='external':
        return next((item.get('sha256') for item in record.get('files',[]) if item.get('path')==record.get('path')),None)
    return None

def _initial_reset(run,spec,robots):
    for robot in robots:
        config=spec.get('objects',{}).get(robot,{}).get('pose_follower',{})
        expected=config.get('initial_joints');follower=run.get('followers',{}).get(robot,{})
        actual=follower.get('initial_joint_positions');transitions=follower.get('transitions',[])
        if not isinstance(expected,dict) or not expected or not isinstance(actual,dict) or not transitions:return False
        if transitions[0].get('index')!=0 or transitions[0].get('physics_step')!=0:return False
        for joint,value in expected.items():
            observed=actual.get(joint)
            if not isinstance(value,(int,float)) or not isinstance(observed,(int,float)) or not math.isfinite(observed) or abs(value-observed)>.05:return False
    return True

def _resources(run):
    samples=run.get('resources') or [];steps=run.get('actual_physics_steps',0)
    if not samples or samples[0].get('physics_steps')!=0 or samples[-1].get('physics_steps')!=steps:return False
    positions=[s.get('physics_steps') for s in samples]
    return bool(all(type(p) is int for p in positions) and all(0<b-a<=3600 for a,b in zip(positions,positions[1:])) and
                all(isinstance(s.get('rss_bytes'),int) and s['rss_bytes']>0 and
                    isinstance(s.get('gpu_process_memory_bytes'),int) and s['gpu_process_memory_bytes']>0 for s in samples))

def evaluate(directories, long_directory, case_path):
    case,case_hash=_load(case_path)
    package=Path(__file__).resolve().parents[1]
    current_code={str(path.relative_to(package)):hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in package.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc'}
    objects=case.get('objects',[]);labels=Counter(x.get('class_label') for x in objects if isinstance(x,dict))
    robots=sorted({x.get('robot_id') for x in objects if isinstance(x,dict) and isinstance(x.get('robot_id'),str)})
    thresholds=case.get('acceptance_thresholds') or {};common=case.get('common') or {}
    def meets(name,minimum):
        value=thresholds.get(name)
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=minimum
    ids=[x.get('part_id') for x in objects if isinstance(x,dict)]
    expected=case.get('expected_spawn_order',[])
    def maximum(name,limit):
        value=common.get(name)
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<value<=limit
    stable=common.get('stable_duration_s')
    belt_min=case.get('minimum_belt_speed')
    class_owners={label:{x.get('robot_id') for x in objects if isinstance(x,dict) and x.get('class_label')==label} for label in labels}
    checks={'fixed_case_shape':len(objects)==60 and len(ids)==len(set(ids)) and len(labels)==3 and set(labels.values())=={20} and len(robots)==3 and len(expected)==60 and len(set(expected))==60 and set(expected)==set(ids),
            'case_thresholds':meets('overall_success_rate',.9) and meets('per_robot_success_rate',.85) and meets('minimum_parallel_steps',1),
            'physical_thresholds':isinstance(stable,(int,float)) and not isinstance(stable,bool) and math.isfinite(stable) and stable>=1 and maximum('max_linear_velocity_m_s',.05) and maximum('max_angular_velocity_rad_s',.5) and maximum('stable_displacement_m',.003) and maximum('tolerance_m',.002),
            'belt_speed_threshold_nonzero':isinstance(belt_min,(int,float)) and not isinstance(belt_min,bool) and math.isfinite(belt_min) and belt_min>0,
            'fixed_collision_policy':case.get('collision_policy')==COLLISION_POLICY,
            'class_routes_unambiguous':len(class_owners)==3 and all(len(owners)==1 for owners in class_owners.values()) and len({next(iter(owners)) for owners in class_owners.values() if owners})==3,
            'three_runs':len(directories)==3}
    records=[];errors=[]
    for label,directory in [(str(i),p) for i,p in enumerate(directories)]+[('long',long_directory)]:
        try:
            root=Path(directory);manifest=json.loads((root/'run-lock.json').read_text())
            run=json.loads((root/'result.json').read_text());spec=json.loads((root/'spec.json').read_text())
            asset_lock=json.loads((root/'asset-lock.json').read_text());integrity=verify_inputs(root)
            runtime_lock=json.loads((root/'runtime-lock.json').read_text())
            evidence_integrity=verify_evidence(root)
            report=evaluate_stream(run,spec,case)
            model_hashes=[_model_hash(asset_lock.get(robot,{})) for robot in robots]
            from .overlap_audit import evaluate as evaluate_collision
            collision_audit=evaluate_collision(run,spec,case,root/'scene.usda')
            if manifest.get('archive_verified_objects'):
                from .archive_ledger import verify as verify_ledger
                archive_ledger_ok=verify_ledger(root,run)
            else:archive_ledger_ok=not run.get('archived_objects')
            record_checks={'input_integrity':integrity['passed'],
                           'worker_code_frozen':integrity['checks'].get('worker_code_snapshot') is True,
                           'verifier_code_matches_snapshot':manifest.get('worker_code_sha256')==current_code,
                           'evidence_integrity':evidence_integrity['passed'] and evidence_integrity['partial'] is False,
                           'case_frozen_before_run':manifest.get('acceptance_case_sha256')==case_hash and integrity['checks'].get('acceptance_case') is True,
                           'seed_matches_result':manifest.get('seed')==run.get('seed') and isinstance(manifest.get('seed'),int),
                           'distinct_robot_models':len(model_hashes)==3 and all(model_hashes) and len(set(model_hashes))==3,
                           'reset_observed':_initial_reset(run,spec,robots),
                           'duration_matches_lock':manifest.get('requested_physics_steps')==run.get('requested_physics_steps')==run.get('actual_physics_steps') and manifest.get('physics_dt_s')==1/60 and abs(run.get('simulation_time_s',-1)-run.get('actual_physics_steps',0)/60)<.01,
                           'collision_audit_complete':collision_audit['passed'],
                           'archive_ledger_consistent':archive_ledger_ok,
                           'stream_checks':report['passed']}
            if label=='long':
                record_checks['ten_minutes_simulated']=run.get('simulation_time_s',0)>=600 and run.get('actual_physics_steps',0)>=36000
                record_checks['resource_samples_complete']=_resources(run)
            records.append({'label':label,'run_id':manifest.get('run_id'),'seed':manifest.get('seed'),
                            'source_scene_sha256':manifest.get('source_scene_sha256'),
                            'worker_code_sha256':hashlib.sha256(json.dumps(manifest['worker_code_sha256'],sort_keys=True,separators=(',',':')).encode()).hexdigest() if isinstance(manifest.get('worker_code_sha256'),dict) and manifest['worker_code_sha256'] else None,
                            'asset_lock_fingerprint':hashlib.sha256(json.dumps(asset_lock,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                            'controller_files_fingerprint':hashlib.sha256(json.dumps({k:v.get('files_sha256') for k,v in runtime_lock.items()},sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                            'checks':record_checks,'stream':report,'collision_audit':collision_audit})
        except (OSError,ValueError,TypeError,KeyError,IndexError) as error:
            errors.append({'run':label,'error':str(error)})
    normal=[r for r in records if r['label']!='long'];all_ids=[r['run_id'] for r in records]
    hashes=[r['source_scene_sha256'] for r in records]
    checks['all_runs_readable']=len(records)==4 and not errors
    checks['expected_seeds']={r['seed'] for r in normal}==SEEDS and len(normal)==3
    checks['distinct_run_ids']=len(all_ids)==4 and all(isinstance(x,str) and x for x in all_ids) and len(set(all_ids))==4
    checks['same_initial_scene']=len(hashes)==4 and all(isinstance(x,str) and len(x)==64 for x in hashes) and len(set(hashes))==1
    code_hashes=[r['worker_code_sha256'] for r in records]
    checks['same_worker_code']=len(code_hashes)==4 and all(code_hashes) and len(set(code_hashes))==1
    for field in ('asset_lock_fingerprint','controller_files_fingerprint'):
        values=[r[field] for r in records]
        checks['same_'+field]=len(values)==4 and len(set(values))==1
    checks['all_run_checks']=len(records)==4 and all(all(r['checks'].values()) for r in records)
    return {'passed':all(checks.values()),'checks':checks,'case_sha256':case_hash,'runs':records,'errors':errors,
            'scope':'documented three-arm physical runs and 10-minute resource record; agent-client, negative-control and cross-machine tests are separate'}
