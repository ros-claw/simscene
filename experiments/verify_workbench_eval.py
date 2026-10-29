"""Independent geometry and playback checks for a workbench run.

The original check was authored after an exploratory agent run. Supplying the
separate, pre-registered case checks a new run against its frozen thresholds.
Neither mode verifies robot manipulation or continuous collision safety.
"""
import hashlib
import json
import math
import sys
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_evidence

if len(sys.argv) not in (2, 3):
    raise SystemExit('usage: verify_workbench_eval.py RUN_DIR [PRE_REGISTERED_CASE]')
root=Path(sys.argv[1]);spec=json.loads((root/'spec.json').read_text());run=json.loads((root/'result.json').read_text())
case_path=Path(sys.argv[2]) if len(sys.argv)==3 else None
case=json.loads(case_path.read_text()) if case_path else None
if case and case.get('schema')!='simscene.agent_workbench_case.v1':
    raise SystemExit('unsupported pre-registered case')
objects=spec['objects'];boxes=[(name,o) for name,o in objects.items() if o.get('kind')=='box' and isinstance(o.get('position'),list) and isinstance(o.get('size'),list)]
bins=[]
for name,base in boxes:
    x,y,z=base['position'];sx,sy,sz=base['size']
    if not (.05<=sx<=.5 and .05<=sy<=.5 and 0<sz<=.05):continue
    walls=set()
    for _,wall in boxes:
        wx,wy,wz=wall['position'];dx,dy,dz=wall['size']
        if not (.04<=dz<=.5 and wz>z):continue
        if abs(wy-y)<.03 and abs(dy-sy)<.04 and dx<.05:
            if abs(wx-(x-sx/2))<.03:walls.add('left')
            if abs(wx-(x+sx/2))<.03:walls.add('right')
        if abs(wx-x)<.03 and abs(dx-sx)<.06 and dy<.05:
            if abs(wy-(y-sy/2))<.03:walls.add('front')
            if abs(wy-(y+sy/2))<.03:walls.add('back')
    if len(walls)==4:bins.append({'base':name,'center':[x,y,z]})
minimum_per_row=case['minimum_bins_per_row'] if case else 2
tol=case['row_tolerance_m'] if case else .03
separation=case['minimum_row_separation_m'] if case else 0
rows=[]
for bin in sorted(bins,key=lambda item:item['center'][1]):
    y=bin['center'][1]
    if not rows or abs(y-sum(rows[-1])/len(rows[-1]))>tol:
        rows.append([y])
    else:
        rows[-1].append(y)
row_positions=[sum(row)/len(row) for row in rows if len(row)>=minimum_per_row]
two_rows=any(abs(a-b)>=separation for i,a in enumerate(row_positions) for b in row_positions[i+1:])
asset_suffix=case['robot_asset_suffix'].lower() if case else 'frankapanda'
robots=[name for name,obj in objects.items() if obj.get('kind')=='asset' and asset_suffix in str(obj.get('asset_path','')).lower()]
camera_data=[]
for name,obj in objects.items():
    if obj.get('kind')!='camera' or not obj.get('camera_orbit'):continue
    center=obj['camera_orbit']['center'];points=[s['cameras'][name]['position'] for s in run.get('samples',[]) if name in s.get('cameras',{})]
    angles=[math.atan2(p[1]-center[1],p[0]-center[0]) for p in points]
    turn=sum((b-a+math.pi)%(2*math.pi)-math.pi for a,b in zip(angles,angles[1:]))
    camera_data.append({'name':name,'samples':len(points),'observed_turn_rad':turn})
try:
    inputs=verify_inputs(root)
except (OSError, ValueError, KeyError, TypeError):
    inputs={'passed':False}
outputs=verify_evidence(root)
checks={'one_robot':len(robots)==1,'robot_body_observed':len(robots)==1 and any(k.startswith('/World/'+robots[0].replace('-','_')+'/Asset/') for k in run.get('positions',{})),
        'two_rows_of_open_bins':two_rows and len(bins)>=(case['minimum_bin_count'] if case else 4),'light_present':any(o.get('kind')=='light' for o in objects.values()),
        'orbit_observed':any(abs(c['observed_turn_rad'])>=(case['minimum_orbit_angle_rad'] if case else 1.8*math.pi) and c['samples']>=(case['minimum_camera_samples'] if case else 1) for c in camera_data),
        'simulation_completed':run.get('actual_physics_steps')==run.get('requested_physics_steps') and run.get('actual_physics_steps',0)>=(case['minimum_simulation_steps'] if case else 1),
        'recording_present':bool(run.get('videos')),'input_integrity':inputs['passed'],'output_integrity':outputs['passed'] and not outputs['partial']}
if case:
    digest=hashlib.sha256(case_path.read_bytes()).hexdigest()
    checksum=case_path.with_suffix('.sha256')
    checks['case_copy_hash_matches']=checksum.is_file() and checksum.read_text().strip()==digest
    try:
        frozen=case_path.parent/'frozen-checker.py'
        expected=(case_path.parent/'frozen-checker.sha256').read_text().strip()
        checks['checker_matches_frozen_copy']=hashlib.sha256(frozen.read_bytes()).hexdigest()==expected and hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()==expected
    except OSError:
        checks['checker_matches_frozen_copy']=False
    try:
        evaluation=case_path.parent
        package=json.loads((evaluation/'package-hashes.json').read_text())
        run_lock=json.loads((root/'run-lock.json').read_text())
        prefix='server/vendor/simscene/'
        worker={name[len(prefix):]:value for name,value in package.items() if name.startswith(prefix)}
        checks['worker_matches_frozen_package']=bool(worker) and worker==run_lock.get('worker_code_sha256')
        skill_prefix='skills/'
        skills={name[len(skill_prefix):]:value for name,value in package.items() if name.startswith(skill_prefix)}
        skills_root=evaluation/'work'/'.agents'/'skills'
        actual={str(path.relative_to(skills_root)):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in skills_root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
        checks['skill_matches_frozen_package']=bool(skills) and skills==actual
    except (OSError,ValueError,TypeError,KeyError):
        checks['worker_matches_frozen_package']=False
        checks['skill_matches_frozen_package']=False
report={'passed':all(checks.values()),'checks':checks,'bins':bins,'cameras':camera_data,
        'case_sha256':digest if case else None,
        'scope':case['scope'] if case else 'Post-hoc generic geometry/playback checks; no pre-registered case, robot manipulation, collision safety or three-arm acceptance.'}
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
