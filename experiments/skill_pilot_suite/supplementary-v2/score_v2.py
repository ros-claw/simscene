#!/usr/bin/env python3
"""Independent pilot v1 examiner. Reads sealed native runs; writes stdout only.

No subprocess, scene edits, physics launch, retiming, sample interpolation,
missing-data repair, or outcome-dependent threshold adjustment is performed.
Imports only pinned generic v43 evidence readers for custody/clock/contact checks.
The two task predicates and isolated interventions are implemented here.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent/'original-design'
PAIRED_FIELDS = (
    'worker_code_sha256','physics_dt_s','physics_device','runtime_python',
    'runtime_python_sha256','queue_launcher_python','queue_launcher_python_sha256',
    'runtime_version','gpu_selection','continue_on_controller_error','archive_verified_objects',
)
GENERIC_MODULES = (
    'simscene.run_integrity','simscene.evidence_integrity',
    'simscene.verification.mechanism','simscene.verification.passive_network','simscene.scene',
)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def frozen_design():
    frozen = read(ROOT/'DESIGN-FREEZE.json')
    checks = {}
    for rel, digest in frozen['files_sha256'].items():
        file = ROOT/rel
        checks[rel] = file.is_file() and not file.is_symlink() and sha(file) == digest
    for module, digest in frozen['generic_readers_sha256'].items():
        spec = importlib.util.find_spec(module)
        checks[module] = bool(spec and spec.origin and sha(spec.origin) == digest)
    return {'passed':bool(checks) and all(checks.values()),'checks':checks,
            'freeze_sha256':sha(ROOT/'DESIGN-FREEZE.json')}


def xyz(p):
    return isinstance(p,list) and len(p)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in p)


def path(n):
    return '/World/'+n.replace('-','_')


def position(sample,n):
    return sample['positions'][path(n)]


def rotation(sample,n):
    return sample['orientations_wxyz'][path(n)]


def dist(a,b):
    return math.dist(a,b)


def sub(a,b):
    return [x-y for x,y in zip(a,b)]


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def qmul(a,b):
    aw,ax,ay,az=a;bw,bx,by,bz=b
    return [aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
            aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw]


def inv(q):
    return [q[0],-q[1],-q[2],-q[3]]


def rotate(q,p):
    return qmul(qmul(q,[0,*p]),inv(q))[1:]


def angle(a,b):
    size=math.sqrt(dot(a,a)*dot(b,b))
    if size<=0:
        raise ValueError('zero quaternion')
    return math.degrees(2*math.acos(max(-1.,min(1.,abs(dot(a,b))/size))))


def pose_span(samples,n):
    return max((dist(position(a,n),position(b,n)) for a in samples for b in samples),default=math.inf)


def rotation_span(samples,n):
    return max((angle(rotation(a,n),rotation(b,n)) for a in samples for b in samples),default=math.inf)


def body_quiet(samples,initial,n,translation,rotation_limit):
    return bool(samples) and all(dist(position(s,n),position(initial,n))<=translation and
        angle(rotation(s,n),rotation(initial,n))<=rotation_limit for s in samples)


def relative_position(sample,n,base):
    return rotate(inv(rotation(sample,base)),sub(position(sample,n),position(sample,base)))


def horizontal_offset(sample,initial,n):
    return math.dist(position(sample,n)[:2],position(initial,n)[:2])


def contact_steps(journal,a,b):
    return sorted({r['observation_step'] for r in journal.get('records',[]) if set(r['body_ids'])=={a,b}})


def unit_sphere(obj):
    dims=obj.get('size',[])
    return len(dims)==3 and max(dims)-min(dims)<=1e-8 and min(dims)>0


def initial_hinge_angle(objects):
    cfg=objects['hinge']['joint']
    q0=cfg.get('local_rot0_wxyz',[1,0,0,0])
    q1=qmul(objects['lever'].get('orientation_wxyz',[1,0,0,0]),cfg.get('local_rot1_wxyz',[1,0,0,0]))
    relative=qmul(inv(q0),q1)
    axis='XYZ'.index(cfg.get('axis','X'))
    return (math.degrees(2*math.atan2(relative[axis+1],relative[0]))+180)%360-180


def source_checks(spec,case,mode):
    from simscene.scene import validate
    objects=spec['objects'];roles=case['roles']
    issues=validate(spec)
    kinds=set(case['allowed_geometry'])|{'joint','camera','light'}
    dynamic={n for n,o in objects.items() if o.get('dynamic')}
    joints={n for n,o in objects.items() if o.get('kind')=='joint'}
    forbidden=('pose_follower','conveyor','driver','drive','motor','kinematic','rigid_attachment','camera_orbit','camera_path')
    cameras=[o for o in objects.values() if o.get('kind')=='camera']
    c={
      'v43_scene_schema_valid':not issues,
      'declared_roles_present':set(roles.values())<=set(objects),
      'only_primitive_geometry_and_passive_infrastructure':all(o.get('kind') in kinds for o in objects.values()),
      'object_budget':len(objects)<=case['maximum_object_count'],
      'exact_dynamic_inventory':dynamic==set(case['dynamic_ids']),
      'exact_joint_inventory':joints==set(case['joint_ids']),
      'per_step_strict_contact_observation':spec.get('observation')==case['observation'],
      'no_active_or_external_scene_fields':not spec.get('drivers') and not spec.get('followers') and all(not any(o.get(k) for k in forbidden) for o in objects.values()),
      'one_fixed_low_resolution_camera':len(cameras)==1 and cameras[0].get('camera',{}).get('resolution') in ([320,240],[640,360]),
      'all_dynamics_explicit_mass_collision':all(type(o.get('mass_kg')) in (int,float) and
          case['mass_range_kg'][0]<=o['mass_kg']<=case['mass_range_kg'][1] for o in objects.values() if o.get('dynamic')),
      'only_driver_scheduled':{n:o.get('spawn_step') for n,o in objects.items() if o.get('spawn_step',0)}=={'driver':case['release_step']},
    }
    if not c['declared_roles_present']:
        return c
    driver=objects['driver']
    c['driver_real_metric_sphere']=driver.get('kind')=='sphere' and unit_sphere(driver) and case['driver_diameter_range_m'][0]<=driver['size'][0]<=case['driver_diameter_range_m'][1]
    if case['task_id']=='P1':
        cfg=objects['hinge'].get('joint',{})
        c['metric_lever_and_free_payload']=objects['lever'].get('kind')=='compound' and objects['payload'].get('kind') in ('box','sphere')
        c['one_world_grounded_passive_revolute']=cfg.get('type')=='revolute' and cfg.get('body0') is None and cfg.get('body1')=='lever' and cfg.get('enabled',True) is True
        axis=[int(i=='XYZ'.index(cfg.get('axis','X'))) for i in range(3)]
        world_axis=rotate(cfg.get('local_rot0_wxyz',[1,0,0,0]),axis)
        c['hinge_axis_horizontal']=abs(world_axis[2])<=1e-5
        limits=[cfg.get('lower_limit'),cfg.get('upper_limit')]
        c['finite_hinge_limits']=all(type(x) in (int,float) and math.isfinite(x) for x in limits)
        if c['finite_hinge_limits']:
            initial=initial_hinge_angle(objects)
            if mode=='negative':
                c['hinge_locked_at_authored_initial']=all(abs(x-initial)<=case['thresholds']['hinge_lock_angle_tolerance_degrees'] for x in limits)
            else:
                c['hinge_initial_inside_nonzero_limits']=limits[0]<limits[1] and limits[0]-1e-4<=initial<=limits[1]+1e-4
    else:
        payload,ramp,deck=(objects[k] for k in ('payload','ramp','deck'))
        edges=payload.get('size',[]);lo,hi=case['thresholds']['payload_edge_range_m']
        c['payload_free_upright_metric_box']=payload.get('kind')=='box' and len(edges)==3 and all(lo<=x<=hi for x in edges) and angle(payload.get('orientation_wxyz',[1,0,0,0]),[1,0,0,0])<=1e-4
        c['ramp_and_horizontal_deck_static_collision']=ramp.get('kind') in ('box','compound') and deck.get('kind')=='box' and all(o.get('dynamic',False) is False and o.get('collision') is True for o in (ramp,deck)) and angle(deck.get('orientation_wxyz',[1,0,0,0]),[1,0,0,0])<=1e-4
        if mode=='positive':
            c['driver_payload_pair_collidable']='payload' not in driver.get('collision_exclusions',[]) and 'driver' not in payload.get('collision_exclusions',[])
    return c


def runtime_identity(lock,identity):
    approved=identity.get('approved_manifest_fields',{})
    return {k:k in lock and k in approved and lock[k]==approved[k] for k in PAIRED_FIELDS}


def load_native(directory,case,case_path,identity,mode):
    from simscene.run_integrity import verify as input_verify
    from simscene.evidence_integrity import verify as output_verify
    from simscene.verification.mechanism import timeline,strict_initial_state,passive_checks
    from simscene.verification.passive_network import contact_journal
    root=Path(directory).expanduser().resolve()
    inputs=input_verify(root);outputs=output_verify(root)
    lock=read(root/'run-lock.json');spec=read(root/'spec.json');run=read(root/'result.json')
    name=lock.get('acceptance_case_file')
    pin=name in ('acceptance-case.json','acceptance-case.yaml','acceptance-case.yml') and (root/name).is_file() and (root/name).read_bytes()==Path(case_path).read_bytes() and lock.get('acceptance_case_sha256')==sha(case_path)
    checks={
      'input_lock_complete':inputs.get('passed') is True,
      'output_lock_complete_not_partial':outputs.get('passed') is True and outputs.get('partial') is False,
      'case_pinned_before_native_run':pin,
      'worker_snapshot_pinned':bool(lock.get('worker_code_sha256')) and inputs.get('checks',{}).get('worker_code_snapshot') is True,
      'frozen_runtime_identity':all(runtime_identity(lock,identity).values()),
      'fixed_seed_and_steps':lock.get('seed')==run.get('seed')==case['seed'] and lock.get('requested_physics_steps')==run.get('requested_physics_steps')==case['steps'],
      'fixed_timestep':lock.get('physics_dt_s')==case['physics_dt_s'],
    }
    checks.update(source_checks(spec,case,mode))
    compiled_collisions = effective_compiled_collisions(root, spec, case, lock)
    checks['all_dynamics_explicit_mass_collision'] = bool(checks['all_dynamics_explicit_mass_collision'] and compiled_collisions['passed'])
    report={'directory':str(root),'checks':checks,'input_integrity':inputs,'output_integrity':outputs,
            'runtime_identity_checks':runtime_identity(lock,identity),'compiled_dynamic_collisions':compiled_collisions,'passed':False}
    if not all(checks.values()):
        return report,None
    dt=case['physics_dt_s']
    clock=timeline(run,spec,dt);strict=strict_initial_state(run,spec,case,dt)
    passive=passive_checks(run,spec,{'release_step':case['release_step'],'trigger_id':'driver'})
    # Empty joint inventories are legitimate in P2; the old P1 helper requires
    # at least one joint, so that single legacy bool is replaced explicitly.
    if not case['joint_ids']:
        passive['all_joint_observations_passive']=empty_joint_observations_valid([run['initial_observation'],*run['samples']])
    journal=contact_journal(run,spec)
    checks['complete_native_step_clock']=clock['passed']
    checks['strict_zero_velocity_reset_and_full_native_maps']=strict['passed']
    checks['passive_native_settings_and_inventory']=all(passive.values())
    checks['per_step_contact_journal_consistent']=journal['passed']
    checks['full_task_no_missing_contact_geometry']=run.get('contact_geometry_incomplete') is False
    samples=run['samples'];initial=run['initial_observation']
    before=[s for s in samples if s['physics_steps']<=case['release_step']]
    checks['pre_release_all_initial_bodies_quiet']=all(body_quiet(before,initial,n,case['initial_max_translation_m'],case['initial_max_rotation_degrees']) for n in case['dynamic_ids'] if n!='driver')
    checks['no_severe_initial_contact_interpenetration']=all(r.get('minimum_separation_m',0)>=-case['maximum_initial_interpenetration_m'] for r in journal['records'] if r['observation_step']<=case['release_step'])
    checks['all_native_joint_anchors_bounded']=all(j['anchor_error_m']<=case['maximum_joint_anchor_error_m'] for s in [initial,*samples] for j in s.get('joints',{}).values() if j.get('enabled'))
    checks['native_visual_evidence_present']=bool(run.get('images') or run.get('videos'))
    # Validate legacy revolute readback independently from the saved body poses.
    if case['task_id']=='P1':
        cfg=spec['objects']['hinge']['joint'];axis='XYZ'.index(cfg.get('axis','X'))
        q0=cfg.get('local_rot0_wxyz',[1,0,0,0]);p0=cfg.get('local_pos0',[0,0,0])
        a0=None;okay=True
        for s in [initial,*samples]:
            q1=qmul(rotation(s,'lever'),cfg.get('local_rot1_wxyz',[1,0,0,0]))
            r=qmul(inv(q0),q1);a=(math.degrees(2*math.atan2(r[axis+1],r[0]))+180)%360-180
            if a0 is not None:a=a0+(a-a0+180)%360-180
            p1=[v+w for v,w in zip(position(s,'lever'),rotate(rotation(s,'lever'),cfg.get('local_pos1',[0,0,0])))]
            obs=s['joints']['hinge'];okay=okay and abs(a-obs['angle_degrees'])<=0.02 and dist(p0,obs['anchor0_world_m'])<=1e-5 and dist(p1,obs['anchor1_world_m'])<=1e-4 and abs(dist(p0,p1)-obs['anchor_error_m'])<=1e-4
            a0=a
        checks['hinge_frames_reconstructed_from_native_poses']=okay
    report.update(clock=clock,strict_initial_state=strict,passive_checks=passive,
                  contact_journal_errors=journal['errors'],passed=all(checks.values()))
    return report,{'root':root,'lock':lock,'spec':spec,'run':run,'journal':journal} if report['passed'] else None


def driver_metrics(data,case):
    samples=[s for s in data['run']['samples'] if path('driver') in s['positions']]
    first=samples[0]
    return {'drop_m':max(position(first,'driver')[2]-position(s,'driver')[2] for s in samples),
            'horizontal_travel_m':max(horizontal_offset(s,first,'driver') for s in samples),
            'first_observed_step':first['physics_steps']}


def task_predicates(data,case,mode):
    run,spec,journal=data['run'],data['spec'],data['journal']
    samples=run['samples'];initial=run['initial_observation'];t=case['thresholds'];release=case['release_step']
    driver=driver_metrics(data,case);checks={};metrics={'driver':driver}
    rise=[position(s,'payload')[2]-position(initial,'payload')[2] for s in samples]
    if case['task_id']=='P1':
        driver_contacts=contact_steps(journal,'driver','lever')
        support=contact_steps(journal,'payload','lever')
        checks['driver_falls_and_reaches_lever']=driver['drop_m']>=t['driver_min_drop_m'] and any(s>release for s in driver_contacts)
        checks['payload_initially_physically_supported']=sum(s<=release for s in support)>=t['initial_support_contact_min_steps']
        turns=[angle(rotation(s,'lever'),rotation(initial,'lever')) for s in samples]
        metrics.update(payload_max_rise_m=max(rise),lever_max_rotation_degrees=max(turns),
                       driver_lever_contact_steps=driver_contacts,payload_lever_contact_steps=support)
        if mode=='negative':
            checks['locked_lever_stays_still']=max(turns)<=t['negative_lever_max_rotation_degrees']
            checks['payload_not_lifted']=max(rise)<=t['negative_payload_max_rise_m'] and max(dist(position(s,'payload'),position(initial,'payload')) for s in samples)<=t['negative_payload_max_translation_m']
        else:
            first_contact=min(driver_contacts,default=case['steps']+1)
            hold=t['payload_lift_hold_steps'];winner=None;gap=t['lift_contact_max_gap_steps']
            for i in range(len(samples)-hold+1):
                window=samples[i:i+hold]
                if window[0]['physics_steps']<first_contact-case['contact_time_tolerance_steps']:continue
                if not all(r>=t['payload_min_rise_m'] and a>=t['lever_min_rotation_degrees'] for r,a in zip(rise[i:i+hold],turns[i:i+hold])):continue
                relative=[relative_position(s,'payload','lever') for s in window]
                if max(dist(a,b) for a in relative for b in relative)>t['carried_relative_max_translation_m']:continue
                begin,end=window[0]['physics_steps'],window[-1]['physics_steps']
                if not all(any(start<=s<start+gap for s in support) for start in range(begin,end-gap+2)):continue
                winner={'onset_step':begin,'confirmation_step':end};break
            checks['sustained_physically_carried_lift']=winner is not None
            checks['lever_and_payload_quiet_until_driver_contact']=body_quiet([s for s in samples if s['physics_steps']<first_contact-case['contact_time_tolerance_steps']],initial,'lever',case['initial_max_translation_m'],case['initial_max_rotation_degrees']) and body_quiet([s for s in samples if s['physics_steps']<first_contact-case['contact_time_tolerance_steps']],initial,'payload',case['initial_max_translation_m'],case['initial_max_rotation_degrees'])
            metrics['lift_window']=winner
    else:
        impact=contact_steps(journal,'driver','payload');ramp=contact_steps(journal,'driver','ramp');support=contact_steps(journal,'payload','deck')
        first_driver=next(s for s in samples if path('driver') in s['positions'])
        driver_rotation=max((angle(rotation(s,'driver'),rotation(first_driver,'driver')) for s in samples if s['physics_steps'] in ramp and path('driver') in s['positions']),default=0)
        metrics['driver_rotation_during_ramp_contact_degrees']=driver_rotation
        checks['upstream_gravity_rolls_on_ramp']=driver['drop_m']>=t['driver_min_drop_m'] and driver['horizontal_travel_m']>=t['driver_min_horizontal_travel_m'] and bool(ramp) and driver_rotation>=t['driver_min_rotation_on_ramp_degrees']
        checks['payload_initially_physically_supported']=sum(s<=release for s in support)>=t['initial_support_contact_min_steps']
        offsets=[horizontal_offset(s,initial,'payload') for s in samples]
        metrics.update(payload_max_horizontal_offset_m=max(offsets),payload_final_horizontal_offset_m=offsets[-1],driver_payload_contact_steps=impact,driver_ramp_contact_steps=ramp)
        if mode=='negative':
            checks['sole_pair_exclusion_removes_impact']=not impact
            checks['free_payload_stays_quiet']=body_quiet(samples,initial,'payload',t['negative_payload_max_translation_m'],t['negative_payload_max_rotation_degrees'])
        else:
            checks['real_driver_payload_collision']=bool(impact)
            first=min(impact,default=case['steps']+1)
            before=[s for s in samples if s['physics_steps']<first-case['contact_time_tolerance_steps']]
            checks['payload_quiet_before_real_impact']=body_quiet(before,initial,'payload',t['before_impact_payload_max_translation_m'],t['before_impact_payload_max_rotation_degrees'])
            moved=next((s['physics_steps'] for s,o in zip(samples,offsets) if o>=t['payload_min_horizontal_travel_m']),None)
            checks['payload_moves_after_collision']=moved is not None and bool(impact) and moved>=first-case['contact_time_tolerance_steps']
            tail=samples[-t['terminal_hold_steps']:]
            checks['payload_stops_at_new_location']=len(tail)==t['terminal_hold_steps'] and all(horizontal_offset(s,initial,'payload')>=t['payload_final_min_horizontal_offset_m'] for s in tail) and pose_span(tail,'payload')<=t['terminal_max_translation_span_m'] and rotation_span(tail,'payload')<=t['terminal_max_rotation_degrees']
            checks['payload_slides_without_fall_or_tumble']=max(abs(v) for v in rise)<=t['payload_max_vertical_deviation_m'] and all(math.degrees(math.acos(max(-1.,min(1.,rotate(rotation(s,'payload'),[0,0,1])[2]))))<=t['payload_max_tilt_degrees'] for s in samples)
            deck=spec['objects']['deck'];deck_p=deck.get('position',[0,0,0]);deck_s=deck['size'];half=[x/2 for x in spec['objects']['payload']['size']]
            deck_top=deck_p[2]+deck_s[2]/2;tol=t['deck_top_tolerance_m'];contained=True
            for s in tail:
                corners=[[position(s,'payload')[k]+rotate(rotation(s,'payload'),[sx*half[0],sy*half[1],sz*half[2]])[k] for k in range(3)] for sx in (-1,1) for sy in (-1,1) for sz in (-1,1)]
                contained=contained and all(abs(p[k]-deck_p[k])<=deck_s[k]/2+1e-5 for p in corners for k in (0,1)) and abs(min(p[2] for p in corners)-deck_top)<=tol
            checks['terminal_whole_payload_supported_on_deck']=contained and any(s>=tail[0]['physics_steps'] for s in support)
            metrics['payload_travel_onset_step']=moved
    return {'passed':all(checks.values()),'checks':checks,'metrics':metrics}


def isolated_intervention(positive,negative,case):
    a=positive['spec'];b=negative['spec'];expected=copy.deepcopy(a['objects'])
    if case['task_id']=='P1':
        initial=initial_hinge_angle(expected)
        expected['hinge']['joint']['lower_limit']=initial
        expected['hinge']['joint']['upper_limit']=initial
        actual=copy.deepcopy(b['objects'])
        cfg=actual.get('hinge',{}).get('joint',{})
        valid=all(type(cfg.get(k)) in (int,float) and abs(cfg[k]-initial)<=case['thresholds']['hinge_lock_angle_tolerance_degrees'] for k in ('lower_limit','upper_limit'))
        if valid:
            cfg['lower_limit']=initial;cfg['upper_limit']=initial
    else:
        exclusions=expected['driver'].setdefault('collision_exclusions',[])
        valid='payload' not in exclusions and 'driver' not in expected['payload'].get('collision_exclusions',[])
        exclusions.append('payload');actual=copy.deepcopy(b['objects'])
        # The public operation is list insertion; ordering of this set has no
        # physics meaning. All remaining list/object fields compare exactly.
        actual_list=actual.get('driver',{}).get('collision_exclusions',[])
        valid=valid and len(actual_list)==len(exclusions) and set(actual_list)==set(exclusions)
        if valid:actual['driver']['collision_exclusions']=exclusions
    ignored={'scene_id','revision','requests','objects'}
    a_meta={k:v for k,v in a.items() if k not in ignored};b_meta={k:v for k,v in b.items() if k not in ignored}
    checks={'exact_single_intervention_only':valid and actual==expected,
            'all_scene_settings_unchanged':a_meta==b_meta,
            'distinct_native_runs':positive['root']!=negative['root'] and positive['lock'].get('run_id')!=negative['lock'].get('run_id'),
            'same_frozen_runtime_seed_duration':all(positive['lock'].get(k)==negative['lock'].get(k) for k in (*PAIRED_FIELDS,'seed','requested_physics_steps'))}
    return {'passed':all(checks.values()),'checks':checks}



def empty_joint_observations_valid(observations):
    """An absent map encodes the same empty inventory as {}; None/extra joints fail.

    Called only when the unchanged source/case joint inventories are both empty.
    The strict t0/full-clock checks still run independently and remain unchanged.
    """
    return all(s.get('joints', {}) == {} for s in observations)


def effective_compiled_collisions(root, spec, case, lock):
    """Read effective USD schemas, without running or mutating any physics.

    Initial bodies are checked in the sealed original authored stage. Scheduled
    bodies do not yet exist in that stage: an isolated CPU-only compilation of
    an initial-equivalent source copy supplies their schema witness. This is
    explicitly a compiler-policy witness, not a saved native spawn-stage
    readback. The original native contact/clock/passivity predicates still must
    pass. The exporter and spawn implementation bytes must match the run's
    approved, intact worker snapshot; no fresh implementation is substituted.
    """
    report={'passed':False,'bodies':{},'compiler_identity':{},
            'scope':'Effective compiled USD colliders. Source-equivalent CPU compilation only for scheduled bodies; no simulation, stage edits or evidence rewrites.'}
    try:
        from pxr import Usd, UsdPhysics
        import simscene
        from simscene.usd_export import export_scene
        package=Path(simscene.__file__).resolve().parent
        dependency_names=('usd_export.py','passive.py','materials.py','attachments.py','capture.py','d6.py','geometry.py','scene.py','worker/spawn.py')
        expected=lock.get('worker_code_sha256',{})
        report['compiler_identity']={name:name in expected and (package/name).is_file() and sha(package/name)==expected[name] for name in dependency_names}
        if not all(report['compiler_identity'].values()):
            return report
        if any(o.get('kind') not in set(case['allowed_geometry'])|{'joint','camera','light'} for o in spec['objects'].values()):
            report['error']='unsupported source: no external asset compilation allowed';return report
        stage=Usd.Stage.Open(str(Path(root)/'scene.usda'))
        if not stage:
            report['error']='sealed authored USD stage cannot be opened';return report
        scheduled=[n for n in case['dynamic_ids'] if spec['objects'][n].get('spawn_step',0)>0]
        probe_stage=None
        with tempfile.TemporaryDirectory(prefix='simscene-collision-interface-cpu-') as temporary:
            if scheduled:
                probe=copy.deepcopy(spec)
                for n in scheduled:
                    probe['objects'][n].pop('spawn_step',None)
                probe_path=Path(temporary)/'source-equivalent-compiled.usda'
                export_scene(probe,probe_path)
                probe_stage=Usd.Stage.Open(str(probe_path))
            for name in case['dynamic_ids']:
                selected=probe_stage if name in scheduled else stage
                body=selected.GetPrimAtPath(path(name)) if selected else None
                body_ok=bool(body and body.IsActive() and body.HasAPI(UsdPhysics.RigidBodyAPI))
                if body_ok:
                    api=UsdPhysics.RigidBodyAPI(body)
                    body_ok=api.GetRigidBodyEnabledAttr().Get() is True and api.GetKinematicEnabledAttr().Get() is False
                colliders=[]
                if body_ok:
                    for prim in Usd.PrimRange(body):
                        if not prim.HasAPI(UsdPhysics.CollisionAPI) or UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get() is not True:
                            continue
                        ancestor=prim
                        while ancestor and not ancestor.IsPseudoRoot() and not ancestor.HasAPI(UsdPhysics.RigidBodyAPI):
                            ancestor=ancestor.GetParent()
                        if ancestor and ancestor.GetPath()==body.GetPath():
                            colliders.append(str(prim.GetPath()))
                report['bodies'][name]={'source_collision_field':spec['objects'][name].get('collision','ABSENT'),
                    'stage_witness':'CPU source-equivalent compilation of scheduled body' if name in scheduled else 'sealed original authored stage',
                    'rigid_dynamic_enabled':body_ok,'enabled_colliders':colliders,'passed':body_ok and bool(colliders)}
        report['passed']=bool(report['bodies']) and all(x['passed'] for x in report['bodies'].values())
        return report
    except (ImportError,OSError,ValueError,RuntimeError,TypeError,KeyError,AttributeError) as error:
        report['error']=str(error);return report


def main():
    global ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design-root',required=True,help='Unmodified original design directory containing DESIGN-FREEZE.json')
    parser.add_argument('--task',choices=('P1','P2'),required=True)
    parser.add_argument('--positive',required=True)
    parser.add_argument('--negative')
    parser.add_argument('--identity',required=True)
    args=parser.parse_args()
    ROOT=Path(args.design_root).expanduser().resolve()
    freeze=frozen_design()
    if not freeze['passed']:
        print(json.dumps({'passed':False,'evidence_status':'design_or_generic_checker_identity_changed','freeze':freeze},ensure_ascii=False,indent=2));return 2
    case_path=ROOT/'public'/args.task/'public-case.json';case=read(case_path);identity=read(args.identity)
    if identity.get('schema')!='simscene.pilot_runtime_identity.v1' or set(identity.get('approved_manifest_fields',{}))!=set(PAIRED_FIELDS):
        raise ValueError('independently frozen runtime identity required')
    positive,data=load_native(args.positive,case,case_path,identity,'positive')
    if data:
        positive['task']=task_predicates(data,case,'positive');positive['passed']=positive['passed'] and positive['task']['passed']
    report={'schema':'simscene.independent_pilot_report.supplementary_v2','task_id':args.task,
            'supplementary_posthoc':True,'replaces_frozen_outcome':False,'original_checker_sha256':sha(ROOT/'examiner/score.py'),
            'interface_changes':['effective compiled USD dynamic collisions instead of requiring an explicit collision:true source key','omitted empty sample joints map accepted only for exact zero-joint source inventory'],
            'checker_sha256':sha(__file__),'case_sha256':sha(case_path),'identity_sha256':sha(args.identity),
            'freeze':freeze,'positive':positive,'negative':None,'intervention':None,
            'positive_passed':positive['passed'],'physics_suite_passed':False,
            'scope':'SUPPLEMENTARY POST-HOC / EXPLORATORY ONLY; original frozen scores and protocol outcomes remain authoritative. Native sealed physics and isolated causal control only. Overall arm status also requires independent review of visibility, assistance, attempt counts and frozen model/time/usage budgets. No efficiency conclusion follows from this report alone.'}
    if args.negative:
        negative,neg=load_native(args.negative,case,case_path,identity,'negative')
        if neg:
            negative['task']=task_predicates(neg,case,'negative');negative['passed']=negative['passed'] and negative['task']['passed']
        intervention=isolated_intervention(data,neg,case) if data and neg else {'passed':False,'checks':{'both_native_runs_admitted':False}}
        report.update(negative=negative,intervention=intervention,
                      physics_suite_passed=bool(positive['passed'] and negative['passed'] and intervention['passed']))
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if (report['physics_suite_passed'] if args.negative else report['positive_passed']) else 1


if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,ZeroDivisionError) as error:
        print(json.dumps({'positive_passed':False,'physics_suite_passed':False,'evidence_status':'evidence_incomplete_or_invalid','error':str(error)},ensure_ascii=False,indent=2))
        sys.exit(2)
