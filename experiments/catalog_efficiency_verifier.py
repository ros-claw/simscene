#!/usr/bin/env python3
"""Frozen host predicates for paired catalog trials; no model/SDK launches.

Inputs are evaluator configuration. Agent submission flags are ignored. Missing
measurements remain unknown, and legacy primitive bounds are reconstructed only
for explicitly uniform spheres, using the same predicates for both packages.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import io
import importlib.util
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import subprocess
import sys


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def local(root, relative):
    if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('expected a relative bundle locator')
    path=Path(root)/relative
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('bundle locator escapes root')
    return path


def equal(a,b,tolerance=1e-6):
    if type(a) is bool or type(b) is bool:return type(a) is type(b) and a==b
    if type(a) in (int,float) and type(b) in (int,float):return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance
    if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(equal(a[k],b[k],tolerance) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y,tolerance) for x,y in zip(a,b))
    return type(a) is type(b) and a==b


def package_tools(package):
    path=Path(package)/'server/vendor/simscene/mcp_server.py'
    tree=ast.parse(path.read_text());names=[]
    for item in tree.body:
        if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(isinstance(d,ast.Call) and ((isinstance(d.func,ast.Attribute) and d.func.attr=='tool') or (isinstance(d.func,ast.Name) and d.func.id=='threaded_tool')) for d in item.decorator_list):names.append(item.name)
    return set(names)


def host_usd_path():
    spec=importlib.util.find_spec('pxr')
    return str(Path(spec.origin).parent.parent) if spec and spec.origin else ''


def package_integrity(package,run):
    script="""import json,sys
sys.path.insert(0,sys.argv[1])
if sys.argv[3]:sys.path.append(sys.argv[3])
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import verify as evidence
print(json.dumps({'inputs':inputs(sys.argv[2]),'evidence':evidence(sys.argv[2])}))
"""
    result=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(package)/'server/vendor'),str(run),host_usd_path()],capture_output=True,text=True,check=True,timeout=60)
    value=json.loads(result.stdout)
    return value['inputs']['passed'] is True and value['evidence']['passed'] is True and value['evidence']['partial'] is False,value


def sphere_bounds(obj,position):
    size=obj.get('size')
    if obj.get('kind')!='sphere' or not isinstance(size,list) or len(size)!=3 or not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in size) or max(size)-min(size)>1e-9:
        raise ValueError('analytic common bounds require an explicitly uniform sphere')
    radius=size[0]/2
    return {'min':[v-radius for v in position],'max':[v+radius for v in position]}


def frame_path(name,obj,run):
    if obj.get('asset_binding'):
        mapping=run.get('body_bindings',{}).get(name,{})
        if not isinstance(mapping.get('motion_body'),str):raise ValueError('prepared actual motion body is missing')
        return mapping['motion_body'],mapping.get('contact_bodies',[])
    path='/World/'+name.replace('-','_');return path,[path]


def contained(bounds,target,tolerance=1e-6):
    return all(target['min'][i]-tolerance<=bounds['min'][i]<=bounds['max'][i]<=target['max'][i]+tolerance for i in range(3))


def finite(values,n):
    return isinstance(values,list) and len(values)==n and all(type(v) in (int,float) and math.isfinite(v) for v in values)


def physical(run,spec,acceptance):
    steps=acceptance['steps'];dt=1/acceptance['physics_hz'];initial=run.get('initial_observation')
    frames=([initial] if initial else [])+run.get('samples',[])
    checks={'steps':run.get('actual_physics_steps')==run.get('requested_physics_steps')==steps,
      'seed':run.get('seed')==acceptance['seed'],
      'duration':type(run.get('simulation_time_s')) in (int,float) and abs(run['simulation_time_s']-steps*dt)<1e-6,
      'complete_cadence':[f.get('physics_steps') for f in frames]==list(range(steps+1)),
      'complete_timebase':len(frames)==steps+1 and all(type(f.get('simulation_time_s')) in (int,float) and abs(f['simulation_time_s']-i*dt)<1e-6 for i,f in enumerate(frames)),
      'no_robot_pose_followers':not run.get('followers'),
      'no_declared_partial_or_truncation':not any(run.get(k) is True for k in ('partial','samples_truncated','contacts_truncated','contact_geometry_incomplete'))}
    outcomes={}
    for name,rule in acceptance.get('payloads',{}).items():
        obj=spec['objects'].get(name,{});path,actors=frame_path(name,obj,run)
        positions=[frame.get('positions',{}).get(path) for frame in frames]
        orientations=[frame.get('orientations_wxyz',{}).get(path) for frame in frames]
        valid=bool(frames) and all(finite(p,3) and finite(q,4) and abs(sum(x*x for x in q)-1)<.02 for p,q in zip(positions,orientations))
        item={'actual_pose_coverage':valid,'dynamic_collision':obj.get('dynamic') is True and obj.get('collision') is True}
        if valid:
            if obj.get('kind')=='sphere':bounds=[sphere_bounds(obj,p) for p in positions]
            else:
                bounds=[f.get('bounds',{}).get(name) for f in frames]
                valid=all(isinstance(b,dict) and finite(b.get('min'),3) and finite(b.get('max'),3) for b in bounds)
            item['full_bounds_available']=valid
            if valid:
                item['final_work_area']=contained(bounds[-1],rule['target_bounds'])
                item['above_floor_entire_run']=all(b['min'][2]>=rule.get('floor_z_m',0)-rule.get('floor_tolerance_m',.005) for b in bounds)
            item['gravity_drop']=positions[0][2]-positions[-1][2]>=rule.get('min_drop_m',.01)
            tail=[(i,p,q) for i,(p,q) in enumerate(zip(positions,orientations)) if i*dt>=steps*dt-rule.get('settle_seconds',2)]
            stable=True
            for (_,a,qa),(_,b,qb) in zip(tail,tail[1:]):
                cosine=min(1,abs(sum(x*y for x,y in zip(qa,qb)))/math.sqrt(sum(x*x for x in qa)*sum(x*x for x in qb)))
                if math.dist(a,b)/dt>rule.get('max_linear_m_s',.03) or 2*math.acos(cosine)/dt>rule.get('max_angular_rad_s',.3):stable=False
            item['settled']=len(tail)>=round(rule.get('settle_seconds',2)/dt) and stable
            supports=set()
            for support in rule['support_object_ids']:
                support_obj=spec['objects'][support]
                if support_obj.get('asset_binding'):
                    support_manifest=read(support_obj['asset_binding']['manifest_path'])
                    for entry in support_manifest['body_map'].values():
                        supports.update('/World/'+support.replace('-','_')+support_manifest['default_prim']+'/'+p for p in entry['collider_relative_prim_paths'])
                else:supports.add('/World/'+support.replace('-','_'))
            contact=False
            for frame in frames:
                for pair in frame.get('contact_pairs',[]) or []:
                    pair_actors=pair.get('actor_paths',[])
                    if len(pair_actors)==2 and type(pair.get('count')) is int and pair['count']>0 and any(actor in pair_actors for actor in actors) and any(actor in pair_actors for actor in supports):contact=True
            item['required_support_contact']=contact
        outcomes[name]=item
    checks['payloads']=bool(outcomes) and all(all(v.values()) for v in outcomes.values()) if acceptance.get('payloads') else True
    return checks,outcomes


def physical_objects(spec):
    return {name:deepcopy(obj) for name,obj in spec['objects'].items() if obj.get('kind') not in ('camera','light')}


def normalized_objects(spec):
    objects=physical_objects(spec)
    for obj in objects.values():
        for key in ('asset_path','asset_binding'):obj.pop(key,None)
    return objects


def structural(spec,acceptance,bundle):
    objects=physical_objects(spec);required=acceptance['required_objects']
    checks={'exact_physical_actor_ids':set(objects)==set(required),
      'no_extra_actuation':all(not any(obj.get(key) for key in ('conveyor','pose_follower','rigid_attachment')) and (not obj.get('mechanism') or name in required and 'mechanism' in required[name]) for name,obj in objects.items()),
      'required_kinds':all(objects.get(name,{}).get('kind')==rule['kind'] for name,rule in required.items()),
      'dynamic_actor_ids':{name for name,obj in objects.items() if obj.get('dynamic')}==set(acceptance['dynamic_object_ids'])}
    for name,rule in required.items():
        obj=objects.get(name,{})
        checks['constraints:'+name]=all((all(equal(obj.get(key,{}).get(k),v) for k,v in value.items()) if key=='asset_metrics' else equal(obj.get(key,([1,1,1] if key=='size' else False if key in ('dynamic','collision') else None) if obj.get('kind')=='asset' else None),value)) for key,value in rule.items() if key!='kind')
    if acceptance.get('seed_scene'):
        seed=read(local(bundle,acceptance['seed_scene']));expected=normalized_objects(seed)
        edit=acceptance.get('edit')
        if edit:
            name=edit['object_id'];expected[name]['position']=[a+b for a,b in zip(expected[name]['position'],edit['delta_m'])]
        checks['frozen_physical_recipe']=equal(normalized_objects(spec),expected)
    if acceptance.get('measured_support_top_m') is not None:
        support=objects.get('support',{});checks['measured_support_top']=abs(support.get('position',[0,0,-999])[2]+support.get('size',[0,0,0])[2]/2-acceptance['measured_support_top_m'])<=.01
    return checks


def source_checks(run_dir,spec,acceptance):
    lock=read(run_dir/'asset-lock.json');checks={}
    for name,rule in acceptance.get('source_objects',{}).items():
        record=lock.get(name);obj=spec['objects'].get(name,{})
        if not isinstance(record,dict):checks[name]=False;continue
        if record.get('kind')=='prepared_snapshot':
            manifest=read(local(run_dir,record['manifest_relative_to_run']));files=manifest['files'];root=local(run_dir,record['manifest_relative_to_run']).parent
            hashes={item['sha256'] for item in files};checks[name]=all(value in hashes for value in rule['required_file_sha256'])
            if 'root_sha256' in rule:checks[name]=checks[name] and manifest.get('source_sha256')==rule['root_sha256']
            if 'profile_id' in rule:checks[name]=checks[name] and manifest.get('profile_id')==rule['profile_id']
            if 'source_ref' in rule:checks[name]=checks[name] and all(manifest.get('source_ref',{}).get(k)==v for k,v in rule['source_ref'].items())
            for key,value in rule.get('parameters',{}).items():checks[name]=checks[name] and equal(manifest.get('parameters',{}).get(key),value)
        else:
            if record.get('kind')=='external':hashes={item['sha256'] for item in record.get('files',[])}
            elif record.get('kind')=='snapshot':
                relative=record['root_relative_to_run'];parts=Path(relative).parts;package=run_dir/parts[0]/parts[1];hashes={item['sha256'] for item in read(package/'simscene-lock.json')['files']}
            else:hashes=set()
            checks[name]=all(value in hashes for value in rule['required_file_sha256']) and 'profile_id' not in rule
            if 'root_sha256' in rule:checks[name]=checks[name] and digest(obj['asset_path'])==rule['root_sha256']
            if rule.get('closure'):
                closure=rule['closure'];selected=Path(obj['asset_path']);entry=Path(closure['entry_path'])
                if not selected.as_posix().endswith('/'+entry.as_posix()):checks[name]=False
                else:
                    base=selected.parents[len(entry.parts)-1]
                    checks[name]=checks[name] and all(local(base,item['path']).is_file() and digest(local(base,item['path']))==item['sha256'] for item in closure['files'])
    return checks


def rotate(q, point):
    w,x,y,z=q;v=[x,y,z]
    cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    a=cross(v,point);b=cross(v,a)
    return [point[i]+2*w*a[i]+2*b[i] for i in range(3)]


def projected_visibility(image, frame, spec, camera, payload_rules):
    from PIL import Image
    width,height=image.size;obj=spec['objects'][camera];optics=obj['camera']
    pose=frame.get('cameras',{}).get(camera)
    if not pose or not finite(pose.get('position'),3) or not finite(pose.get('orientation_wxyz'),4):return False
    focal=optics.get('focal_length_mm',35)/optics.get('horizontal_aperture_mm',36)*width
    q=pose['orientation_wxyz'];inverse=[q[0],-q[1],-q[2],-q[3]]
    for name,rule in payload_rules.items():
        physical_obj=spec['objects'][name];position=frame.get('positions',{}).get('/World/'+name.replace('-','_'))
        if not finite(position,3):return False
        sphere_bounds(physical_obj,position);radius=physical_obj['size'][0]/2
        camera_point=rotate(inverse,[position[i]-pose['position'][i] for i in range(3)]);depth=-camera_point[2]
        if depth<=radius:return False
        cx=width/2+focal*camera_point[0]/depth;cy=height/2-focal*camera_point[1]/depth;r=focal*radius/(depth-radius)
        if r<rule.get('minimum_radius_px',5) or cx-r<2 or cy-r<2 or cx+r>width-2 or cy+r>height-2:return False
        palette=rule['dominant_channels'];pixels=[]
        for y in range(max(0,int(cy-r)),min(height,int(cy+r)+1)):
            for x in range(max(0,int(cx-r)),min(width,int(cx+r)+1)):
                if (x-cx)**2+(y-cy)**2<r*r:pixels.append(image.getpixel((x,y)))
        if not pixels:return False
        matching=sum(all(pixel[c]>max(pixel[k] for k in range(3) if k not in palette)*1.12+5 for c in palette) for pixel in pixels)
        if matching/len(pixels)<rule.get('minimum_color_fraction',.12):return False
    return True


def video_checks(run_dir,run,spec,rule):
    # Frozen host settings and source manifests establish cadence. Model-supplied
    # visibility/pass flags never participate. Pixel/motion QA remains fail-closed
    # until the fixed host visibility audit reports actual frame/body coverage.
    reports={}
    for name in rule.get('camera_ids',[]):
        value=run.get('videos',{}).get(name,{})
        if not value:reports[name]={'passed':False,'missing':True};continue
        path=Path(value['path']);manifest=Path(value.get('frame_manifest',''))
        checks={'run_local_files':path.parent.resolve()==run_dir.resolve() and manifest.parent.resolve()==run_dir.resolve(),
                'resolution':[value.get('width'),value.get('height')]==rule['resolution'],'fps':value.get('fps')==rule['fps'],
                'frames':value.get('frames')==rule['frames']}
        rows=[json.loads(line) for line in manifest.read_text().splitlines()]
        checks['native_cadence']=len(rows)==rule['frames'] and all(row.get('physics_step')==2*(i+1) and row.get('frame_id')==i and abs(row.get('sim_time_s',-1)-2*(i+1)/60)<1e-6 and abs(row.get('video_time_s',-1)-i/rule['fps'])<1e-6 and row.get('camera_id')==name for i,row in enumerate(rows))
        probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=width,height,nb_read_frames,r_frame_rate,color_space,color_transfer,color_primaries,color_range','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=30)
        stream=json.loads(probe.stdout)['streams'][0]
        checks['actual_decoded_dimensions_frames']=[stream['width'],stream['height']]==rule['resolution'] and int(stream['nb_read_frames'])==rule['frames'] and Fraction(stream['r_frame_rate'])==rule['fps']
        from PIL import Image,ImageStat
        raws=[Path(row['raw_png']) for row in rows if row.get('raw_png')]
        checks['raw_frames_present']=len(raws)>=rule.get('minimum_raw_frames',5) and all(p.parent.resolve()==run_dir.resolve() and p.is_file() for p in raws)
        if raws:
            stats=[ImageStat.Stat(Image.open(path).convert('RGB')) for path in raws]
            checks['nonblank_pixels']=all(sum(stat.var)>rule.get('minimum_channel_variance_sum',20) for stat in stats)
        lookup={f['physics_steps']:f for f in ([run['initial_observation']]+run['samples'])}
        checks['projected_body_and_native_pixels_visible']=len(raws)==len(rows) and all(projected_visibility(Image.open(Path(row['raw_png'])).convert('RGB'),lookup[row['physics_step']],spec,name,rule['payload_visibility']) for row in rows)
        checks['actual_motion_during_capture']=all(math.dist(lookup[2]['positions']['/World/'+body],lookup[300]['positions']['/World/'+body])>=rule.get('minimum_motion_m',.01) for body in rule['payload_visibility'])
        decoded_checks=[]
        if checks['raw_frames_present']:
            from PIL import ImageChops
            for index in [0,7,rule['frames']-1]:
                color_filter=('zscale=matrixin=709:transferin=709:primariesin=709:rangein=limited:matrix=gbr:transfer=iec61966-2-1:primaries=709:range=full,format=gbrp,format=rgb24' if all(stream.get(key)=='bt709' for key in ('color_space','color_transfer','color_primaries')) and stream.get('color_range')=='tv' else 'format=rgb24')
                decoded=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vf',f'select=eq(n\\,{index}),'+color_filter,'-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True,timeout=30)
                image=Image.open(io.BytesIO(decoded.stdout)).convert('RGB');raw=Image.open(rows[index]['raw_png']).convert('RGB')
                mean_error=sum(ImageStat.Stat(ImageChops.difference(raw,image)).mean)/3
                decoded_checks.append(mean_error<=rule.get('maximum_mean_codec_error_8bit',8) and projected_visibility(image,lookup[rows[index]['physics_step']],spec,name,rule['payload_visibility']))
        checks['decoded_pixels_match_native_and_visibility']=len(decoded_checks)==3 and all(decoded_checks)
        reports[name]={'passed':all(checks.values()),'checks':checks,'scope':'Every native RGB frame: measured sphere projection within viewport, minimum radius and actual role-colored pixels; full simulation cadence and observed motion.'}
    return bool(reports) and all(value['passed'] for value in reports.values()),reports


def metadata_trace_verified(work, tokens):
    path=Path(work).parent/'events.jsonl'
    if not path.is_file() or path.stat().st_size>64*1024**2:return False
    try:
        from experiments.eval_catalog_agent import analyze_trace
    except ModuleNotFoundError:
        from eval_catalog_agent import analyze_trace
    trace=analyze_trace(path,work)
    return any(call.get('successful') is True and call.get('tool') in ('asset_search','catalog_search') and any(token in json.dumps(call.get('result')) for token in tokens) for call in trace['calls'])


def attempted_runs(state):
    runs=Path(state)/'runs'
    return {p.name for p in runs.iterdir() if p.is_dir() and any((p/name).is_file() for name in ('job.json','process-exit.json','process-receipt.json'))} if runs.exists() else set()


def evaluate(task,work,state,package,acceptance_path,*,integrity_verifier=package_integrity):
    work=Path(work).resolve();state=Path(state).resolve();acceptance_path=Path(acceptance_path).resolve();acceptance=read(acceptance_path)
    if acceptance.get('schema')!='simscene.catalog_efficiency_acceptance.v1' or acceptance.get('task_id')!=task:raise ValueError('frozen task acceptance differs')
    submission=read(work/'submission.json');tools=package_tools(package)
    if submission.get('capability_gap'):
        missing=set(acceptance.get('required_capability_tools',[]))-tools
        feature_missing=[name for name in acceptance.get('required_capability_files',[]) if not local(Path(package)/'server/vendor/simscene',name).is_file()]
        gap=bool(missing) and bool(feature_missing) and acceptance.get('group')=='B' and acceptance.get('capability_requirement') is not None and set(submission.get('run_ids',[]))==attempted_runs(state)
        return {'passed':False,'provenance_verified':False,'quality_verified':False,'capability_gap':gap,'capability_gap_verified':gap,'missing_capability_tools':sorted(missing),'missing_feature_implementations':feature_missing,'mechanical_requirement':acceptance.get('capability_requirement'),'actual_download_bytes':None,'video_passed':None,'phase_intervals':[]}
    declared=submission.get('run_ids');selected=submission.get('selected_run_id')
    if not isinstance(declared,list) or not declared or len(declared)!=len(set(declared)) or selected not in declared:raise ValueError('submission requires every attempted run and selected_run_id')
    runs=state/'runs';actual=attempted_runs(state)
    checks={'all_attempts_declared':set(declared)==actual,'selected_scene_matches':False};attempts=[]
    for name in declared:
        if not isinstance(name,str) or not re.fullmatch('[0-9a-f]{32}',name):raise ValueError('invalid submitted run ID')
        path=local(runs,name);entry={'run_id':name,'complete_result':(path/'result.json').is_file()};attempts.append(entry)
    root=local(runs,selected);run=read(root/'result.json');spec=read(root/'spec.json');lock=read(root/'run-lock.json')
    checks['selected_scene_matches']=submission.get('scene_id')==spec.get('scene_id')==lock.get('scene_id')
    exit_record=read(root/'process-exit.json');checks['actual_process_success']=exit_record.get('exit_code')==0
    integrity,integrity_report=integrity_verifier(package,root);checks['input_and_saved_evidence_integrity']=integrity
    checks['frozen_runtime']=lock.get('physics_device')=='cpu' and equal(lock.get('physics_dt_s'),1/acceptance['physics_hz']) and lock.get('seed')==acceptance['seed']
    checks.update(structural(spec,acceptance,acceptance_path.parent))
    if acceptance.get('online_metadata_result_tokens'):
        checks['actual_online_source_metadata']=metadata_trace_verified(work,acceptance['online_metadata_result_tokens'])
    sources=source_checks(root,spec,acceptance);checks['source_identity']=bool(sources) and all(sources.values())
    physics,payloads=physical(run,spec,acceptance);checks.update(physics)
    video_passed=None;video=None
    if acceptance.get('video'):
        video_passed,video=video_checks(root,run,spec,acceptance['video']);checks['native_video_quality']=video_passed
    if task=='native-joint':
        # Reuse the admitted checker with exact frozen mechanical requirements;
        # its case must be hash-bound into the run before execution.
        case=read(local(acceptance_path.parent,acceptance['mechanism_case']))
        recorded=read(root/'acceptance-case.json');case_without_pins=deepcopy(recorded)
        for value in case_without_pins.get('objects',{}).values():value.pop('prepared_manifest_sha256',None)
        checks['mechanism_case_frozen']=equal(case_without_pins,case)
        script="import sys,json;sys.path.insert(0,sys.argv[1]);sys.path.extend([sys.argv[3]] if sys.argv[3] else []);from simscene.verification.articulated_asset_smoke import verify_run;print(json.dumps(verify_run(sys.argv[2])))"
        response=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(package)/'server/vendor'),str(root),host_usd_path()],capture_output=True,text=True,check=True,timeout=60);mechanism=json.loads(response.stdout);checks['actual_joint_motion_and_limits']=mechanism['passed']
    if task=='generated-module':
        generated=acceptance['generated'];base=generated['parameters'];changed=dict(base,length_m=generated['changed_length_m'])
        values=[]
        for folder in sorted((state/'generation_jobs').glob('gen-*')):
            if not (folder/'result.json').is_file() or read(folder/'job.json').get('state')!='completed':continue
            task_record=read(folder/'task.json');source=folder/'output/source.usda';manifest=read(folder/'output/generated.json');identity=manifest['identity']
            if task_record.get('recipe_id')!=generated['recipe_id']:continue
            from pxr import Usd,UsdGeom
            generated_stage=Usd.Stage.Open(str(source));box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_]).ComputeWorldBound(generated_stage.GetDefaultPrim()).ComputeAlignedRange();dimensions=list(box.GetSize())
            expected_dimensions=[identity['parameters'][key] for key in ('length_m','width_m','thickness_m')]
            valid=(equal(dimensions,expected_dimensions,1e-5) and abs(UsdGeom.GetStageMetersPerUnit(generated_stage)-1)<1e-9 and UsdGeom.GetStageUpAxis(generated_stage)=='Z' and manifest.get('schema')=='simscene.generated_source.v1' and identity.get('parameters')==task_record['parameters']
                and identity.get('toolchain',{}).get('reviewed_commit')==generated['reviewed_commit'] and identity.get('toolchain',{}).get('observed',{}).get('sand3d_commit')==generated['reviewed_commit']
                and identity.get('template_sha256')==generated['template_sha256'] and digest(source)==identity.get('output_sha256'))
            values.append({'parameters':identity['parameters'],'sha256':identity['output_sha256'],'valid':valid})
        base_outputs=[v for v in values if equal(v['parameters'],base)];changed_outputs=[v for v in values if equal(v['parameters'],changed)]
        checks['generated_repeatability']=len(base_outputs)>=2 and all(v['valid'] for v in base_outputs) and len({v['sha256'] for v in base_outputs})==1
        checks['generated_parameter_change']=bool(changed_outputs) and all(v['valid'] for v in changed_outputs) and bool(base_outputs) and all(v['sha256']!=base_outputs[0]['sha256'] for v in changed_outputs)
        record=read(root/'asset-lock.json').get(generated['object_id'],{});manifest=read(local(root,record['manifest_relative_to_run'])) if record.get('kind')=='prepared_snapshot' else {}
        identity=manifest.get('provenance',{}).get('identity',{})
        checks['generated_actual_source_in_scene']=bool(base_outputs) and identity.get('output_sha256')==base_outputs[0]['sha256'] and equal(identity.get('parameters'),base)
    passed=all(checks.values())
    return {'passed':passed,'provenance_verified':bool(integrity and checks['source_identity']),'quality_verified':bool(passed),'checks':checks,'payloads':payloads,'source_checks':sources,'attempts':attempts,'integrity':integrity_report,'video':video,'video_passed':video_passed,'actual_download_bytes':None,'phase_intervals':[],'manual_interventions':[],
        'unknown_measurements':['all-attempt transfer bytes and monotonic phases absent unless separately recorded by host'],'scope':'persisted inputs, actual complete trajectory, physical and source predicates; uniform-sphere video projection and native RGB color visibility checked identically across versions'}


def main():
    parser=argparse.ArgumentParser()
    for key in ('task','work','state','package','acceptance'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    try:result=evaluate(args.task,args.work,args.state,args.package,args.acceptance)
    except Exception as error:result={'passed':False,'provenance_verified':False,'quality_verified':False,'error':str(error),'actual_download_bytes':None,'video_passed':None,'phase_intervals':[]}
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__':main()
