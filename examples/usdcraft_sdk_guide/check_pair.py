#!/usr/bin/env python3
"""Read-only paired check for the two generated-plate example runs."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from simscene.evidence_integrity import verify as verify_evidence
from simscene.physics_binding import validate_asset_binding
from simscene.recipes.cases import freeze_case
from simscene.recipes.io import resolve_operations
from simscene.run_integrity import verify as verify_inputs

HERE = Path(__file__).resolve().parent


def check(short_run, long_run, case_path):
    case_path = Path(case_path).resolve()
    case = json.loads(case_path.read_text())
    case_sha = hashlib.sha256(case_path.read_bytes()).hexdigest()
    runs = {}
    for name, directory in (('short', short_run), ('long', long_run)):
        root = Path(directory).resolve()
        runs[name] = {'root':root, 'lock':json.loads((root/'run-lock.json').read_text()),
                      'spec':json.loads((root/'spec.json').read_text()),
                      'result':json.loads((root/'result.json').read_text()),
                      'inputs':verify_inputs(root), 'evidence':verify_evidence(root)}
    checks = {'distinct_runs':runs['short']['root'] != runs['long']['root']}
    lock = json.loads((HERE/'assets.lock.json').read_text())
    template = json.loads((HERE/'case.json').read_text())
    bindings = {name:{'asset_path':item['spec']['objects']['plate']['asset_path'],
                      'asset_binding':item['spec']['objects']['plate']['asset_binding']}
                for name,item in runs.items()}
    expected = freeze_case(template,bindings,lock['assets'])['case']
    checks['case_matches_example_template_and_rebuilt_assets'] = case == expected
    same = ('physics_dt_s','physics_device','requested_physics_steps','seed',
            'runtime_version','runtime_python_sha256','worker_code_sha256')
    checks['same_runtime_and_physics'] = all(k in runs['short']['lock'] and k in runs['long']['lock']
        and runs['short']['lock'][k]==runs['long']['lock'][k] for k in same)

    def normalize(spec):
        spec = copy.deepcopy(spec)
        for key in ('scene_id','revision','requests'):spec.pop(key,None)
        plate = spec['objects']['plate']
        plate.pop('asset_path');plate.pop('asset_binding')
        return spec
    checks['same_scene_except_selected_plate'] = normalize(runs['short']['spec']) == normalize(runs['long']['spec'])
    details = {}
    for name,item in runs.items():
        root,run_lock,spec,result = (item[key] for key in ('root','lock','spec','result'))
        frozen = case['assets'][name]
        recipe=json.loads((HERE/('recipe-'+name+'.json')).read_text())
        ops=resolve_operations(recipe,bindings,selections=lock['assets'])
        expected_objects={op['id']:op['object'] for op in ops if op.get('op')=='add'}
        expected_observation=next(op['observation'] for op in ops if op.get('op')=='set_observation')
        expected_presentation=next(op['presentation'] for op in ops if op.get('op')=='set_presentation')
        checks[name+'_scene_matches_example']=(spec['objects']==expected_objects
            and spec.get('observation')==expected_observation and spec.get('presentation')==expected_presentation)
        settings=result.get('physics_settings',{})
        checks[name+'_actual_physics_matches_case']=(run_lock.get('seed')==case['seed']
            and run_lock.get('requested_physics_steps')==case['steps']
            and run_lock.get('physics_device')==case['physics_device']=='cpu'
            and abs(run_lock.get('physics_dt_s',0)-case['physics_dt_s'])<1e-12
            and result.get('seed')==case['seed'] and result.get('task_status') in ('unverified','completed')
            and all(isinstance(settings.get(key),dict) and settings[key].get('requested_device')=='cpu'
                    and settings[key].get('request_matches_observation') is True
                    and settings[key].get('enable_gpu_dynamics') is False
                    and abs(settings[key].get('authored_time_steps_per_second',0)*case['physics_dt_s']-1)<1e-5
                    for key in ('before_warmup','after_run')))
        checks[name+'_case_and_inputs_locked'] = (run_lock.get('acceptance_case_sha256') == case_sha
            and hashlib.sha256((root/'acceptance-case.json').read_bytes()).hexdigest()==case_sha
            and item['inputs']['passed'] is True and item['evidence']['passed'] is True
            and item['evidence']['partial'] is False)
        obj = spec['objects']['plate']
        manifest = validate_asset_binding(obj['asset_binding'],asset_path=obj['asset_path'])
        checks[name+'_source_and_geometry_pinned'] = (
            obj['asset_binding']['manifest_sha256']==frozen['manifest_sha256']
            and Path(obj['asset_path']).resolve().is_relative_to(root)
            and manifest['source_ref']==frozen['source_ref'] and manifest['source_sha256']==frozen['source_sha256']
            and manifest['parameters']['static_proxy']['size_m']==[frozen['length_m'],.18,.015]
            and manifest['parameters']['source_physics_policy']=='replace_visual_only')
        from pxr import Usd
        stage=Usd.Stage.Open(str(root/'scene.usda'))
        scene_ccd=stage.GetPrimAtPath('/World/PhysicsScene').GetAttribute('physxScene:enableCCD')
        ball_ccd=stage.GetPrimAtPath('/World/ball').GetAttribute('physxRigidBody:enableCCD')
        checks[name+'_ccd_enabled']=(spec['objects']['ball'].get('physics',{}).get('enable_ccd') is True
                                    and bool(scene_ccd) and scene_ccd.Get() is True
                                    and bool(ball_ccd) and ball_ccd.Get() is True)
        frames = [result['initial_observation'],*result['samples']]
        finite=lambda value:type(value) in (int,float) and math.isfinite(value)
        absolute_step=result.get('run_zero_absolute_physics_step')
        absolute_time=result.get('run_zero_absolute_simulation_time_s')
        checks[name+'_complete_timeline'] = (result['partial'] is False and result['samples_truncated'] is False
            and result['contacts_truncated'] is False and result['actual_physics_steps']==case['steps']
            and result.get('requested_physics_steps')==case['steps'] and result.get('observation_interval_steps')==1
            and type(absolute_step) is int and absolute_step>=0 and finite(absolute_time)
            and finite(result.get('simulation_time_s'))
            and abs(result['simulation_time_s']-case['steps']*case['physics_dt_s'])<1e-6
            and result.get('contact_geometry_incomplete') is False
            and len(frames)==case['steps']+1 and all(type(row.get('physics_steps')) is int and row['physics_steps']==i
                and finite(row.get('simulation_time_s'))
                and abs(row['simulation_time_s']-i*case['physics_dt_s'])<1e-6
                and type(row.get('absolute_physics_step')) is int and row['absolute_physics_step']==absolute_step+i
                and finite(row.get('absolute_simulation_time_s'))
                and abs(row['absolute_simulation_time_s']-absolute_time-i*case['physics_dt_s'])<1e-5
                for i,row in enumerate(frames)))
        positions=[frame.get('positions',{}).get('/World/ball') for frame in frames]
        checks[name+'_all_ball_positions_finite'] = all(isinstance(position,list) and len(position)==3
            and all(finite(value) for value in position) for position in positions)
        if not checks[name+'_complete_timeline'] or not checks[name+'_all_ball_positions_finite']:
            return {'schema':'simscene.generated_plate_support_pair_report.v1','passed':False,'checks':checks,
                    'scope':'Incomplete or malformed per-step physics evidence.'}
        reset=result.get('initialization_reset',{})
        checks[name+'_initial_ball_matches_case']=(len(positions[0])==3
            and math.dist(positions[0],case['ball_center_initial_m'])<=1e-5
            and spec['objects']['ball'].get('size')==[2*case['ball_radius_m']]*3
            and spec['objects']['plate'].get('position')==case['plate_origin_m'])
        checks[name+'_initial_state_measured']=(reset.get('applied') is True
            and reset.get('phase')=='before_task_start' and reset.get('setters_during_task') is False
            and reset.get('max_linear_speed_m_s',math.inf)<=1e-5
            and reset.get('max_angular_speed_rad_s',math.inf)<=1e-5
            and math.dist(frames[0]['linear_velocities_m_s']['/World/ball'],[0.,0.,0.])<=1e-5
            and math.dist(frames[0]['angular_velocities_rad_s']['/World/ball'],[0.,0.,0.])<=1e-5)
        tail=positions[-case['settled_last_steps']-1:]; z=[p[2] for p in tail]
        checks[name+'_ball_settled_at_expected_height']=(case['expected_final_ball_z_m'][name][0] <= z[-1]
            <= case['expected_final_ball_z_m'][name][1] and max(z)-min(z)<=case['max_settled_z_range_m']
            and max(math.dist(p[:2],tail[0][:2]) for p in tail)<=case['max_settled_xy_drift_m'])
        contacts={};valid_contacts=True
        for frame in frames:
            for pair in frame.get('contact_pairs',[]):
                bodies=pair.get('body_ids',[])
                if not isinstance(bodies,list) or len(bodies)!=2 or not all(isinstance(value,str) for value in bodies):
                    valid_contacts=False;continue
                if 'ball' not in bodies:continue
                other=next((value for value in bodies if value!='ball'),None)
                separation=pair.get('minimum_separation_m')
                if other and type(separation) in (int,float) and math.isfinite(separation):
                    contacts[other]=min(contacts.get(other,math.inf),separation)
                else:valid_contacts=False
        target=case['expected_contact'][name]
        checks[name+'_expected_contact_reported']=(valid_contacts and set(contacts)=={target}
            and contacts[target]<=case['require_direct_contact_min_separation_m_at_most'])
        checks[name+'_reported_penetration_within_limit']=(contacts.get(target,-math.inf)>=-case['max_reported_penetration_m'])
        details[name]={'run':str(root),'final_ball_position_m':positions[-1],
                       'last_second_z_range_m':max(z)-min(z),'minimum_reported_contact_separation_m':contacts,
                       'physics_steps':result['actual_physics_steps']}
    return {'schema':'simscene.generated_plate_support_pair_report.v1','passed':all(checks.values()),
            'checks':checks,'observations':details,
            'scope':'Two selected static proxies and one CCD ball; contact callbacks do not exclude unreported penetration.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--short-run',required=True);parser.add_argument('--long-run',required=True)
    parser.add_argument('--case',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();report=check(args.short_run,args.long_run,args.case)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'passed':report['passed'],'checks':report['checks'],'report':str(output)},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
