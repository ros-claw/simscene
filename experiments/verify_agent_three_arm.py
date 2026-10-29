"""Check a fresh agent's scene and recorded run against a frozen user case."""
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from simscene.evidence_integrity import verify as verify_outputs
from simscene.run_integrity import verify as verify_inputs
from simscene.verification.case_runner import evaluate

if len(sys.argv) != 2:
    raise SystemExit('usage: verify_agent_three_arm.py EVALUATION_DIRECTORY')
root=Path(sys.argv[1]).resolve();case_path=root/'pre_registered_case.json';case=json.loads(case_path.read_text())
if case.get('schema')!='simscene.agent_three_arm_case.v1':
    raise SystemExit('unsupported pre-registered case')
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
checks={'case_copy_hash_matches':(root/'pre_registered_case.sha256').read_text().strip()==digest(case_path),
        'agent_session_completed':(root/'exit-code.txt').read_text().strip()=='0',
        'no_external_intervention':not (root/'external-intervention.json').exists() and not (root/'external-interventions.jsonl').exists()}
try:
    expected=(root/'frozen-checker.sha256').read_text().strip()
    checks['checker_matches_frozen_copy']=digest(root/'frozen-checker.py')==expected and digest(Path(__file__).resolve())==expected
except OSError:
    checks['checker_matches_frozen_copy']=False
runs=[]
for directory in sorted((root/'state'/'runs').glob('*')):
    try:
        lock=json.loads((directory/'run-lock.json').read_text())
        result=json.loads((directory/'result.json').read_text())
        spec=json.loads((directory/'spec.json').read_text())
        if result.get('actual_physics_steps')==result.get('requested_physics_steps') and result.get('actual_physics_steps',0)>0:
            runs.append((directory,lock,result,spec))
    except (OSError,ValueError,KeyError,TypeError):
        continue
checks['completed_run']=bool(runs)
if not runs:
    print(json.dumps({'passed':False,'checks':checks,'scope':case['scope']},indent=2));raise SystemExit(1)
directory,lock,run,spec=max(runs,key=lambda row:row[0].stat().st_mtime)
job_id=json.loads((directory/'job.json').read_text()).get('job_id')
all_calls=[event.get('item',{}) for event in (json.loads(line) for line in (root/'trace.jsonl').read_text().splitlines())
       if event.get('type')=='item.completed' and event.get('item',{}).get('type')=='mcp_tool_call'
       and event.get('item',{}).get('status')=='completed']
calls=[call for call in all_calls if call.get('arguments',{}).get('job_id')==job_id]
checks['agent_observed_selected_run']=any(call.get('tool') in ('run_observe','scene_observe') for call in calls)
def completed_call(call):
    if call.get('tool')=='run_verify':return True
    if call.get('tool')!='job_status':return False
    try:return json.loads(call['result']['content'][0]['text']).get('state')=='completed'
    except (KeyError,IndexError,TypeError,ValueError):return False
checks['agent_saw_completed_run']=any(completed_call(call) for call in calls)
objects=spec['objects'];classes=case['classes'];robots={}
try: asset_locks=json.loads((directory/'asset-lock.json').read_text())
except (OSError,ValueError,TypeError): asset_locks={}
aliases={'red':'red','红':'red','红色':'red','green':'green','绿':'green','绿色':'green',
         'blue':'blue','蓝':'blue','蓝色':'blue'}
def canonical(value):
    return aliases.get(value.strip().lower(),value) if isinstance(value,str) else value
for suffix in case['robot_asset_suffixes']:
    matching=[]
    for name,obj in objects.items():
        if obj.get('kind')!='asset':continue
        # Cache paths are intentionally flattened/padded. The locked source
        # URL retains the original model identity and is itself integrity
        # checked below; do not infer identity from the cache's basename.
        record=asset_locks.get(name,{})
        source=str(record.get('source',''))
        source_path=urlsplit(source).path if source.startswith(('https://','http://')) else source
        if (str(obj.get('asset_path','')).lower().endswith(suffix.lower()) or
                source_path.lower().endswith(suffix.lower())):
            matching.append(name)
    if len(matching)==1:robots[suffix]=matching[0]
checks['three_distinct_listed_robots']=len(robots)==len(case['robot_asset_suffixes']) and len(set(robots.values()))==len(robots)
robot_ids=set(robots.values())
online_sources={asset_locks.get(name,{}).get('source') for name in robot_ids}
inspected={call.get('arguments',{}).get('asset_url') for call in all_calls if call.get('tool')=='asset_inspect'}
acquired={call.get('arguments',{}).get('asset_url') for call in all_calls if call.get('tool')=='asset_acquire'}
checks['online_discovery_and_acquisition']=(len(online_sources)==len(case['robot_asset_suffixes']) and
    all(isinstance(source,str) and source.startswith('https://') for source in online_sources) and
    all(asset_locks.get(name,{}).get('kind')=='snapshot' for name in robot_ids) and
    any(call.get('tool')=='asset_search' for call in all_calls) and online_sources<=inspected and online_sources<=acquired)
checks['robot_bodies_observed']=bool(robot_ids) and all(any(path.startswith('/World/'+robot.replace('-','_')+'/Asset/') for path in run.get('positions',{})) for robot in robot_ids)
belts={name:obj['conveyor'] for name,obj in objects.items() if obj.get('conveyor')}
checks['nonzero_conveyor']=len(belts)==1 and next(iter(belts.values())).get('speed_m_s',0)>0
cameras={name:o for name,o in objects.items() if o.get('kind')=='camera'}
checks['cameras_and_images']=len(cameras)>=case['minimum_cameras'] and len(set(cameras)&set(run.get('images',{})))>=case['minimum_cameras'] and bool(run.get('videos'))
camera_sample=next((sample.get('cameras') for sample in reversed(run.get('samples',[])) if sample.get('cameras')), {})
views=[camera_sample[name] for name in cameras if name in camera_sample and 'position' in camera_sample[name] and 'orientation_wxyz' in camera_sample[name]]
checks['camera_positions_distinct']=len({tuple(view['position']) for view in views})>=case['minimum_cameras']
def forward(view):
    w,x,y,z=view['orientation_wxyz']
    return [-2*(x*z+w*y),-2*(y*z-w*x),-(1-2*(x*x+y*y))]
def looks_at(view,target):
    ray=[target[i]-view['position'][i] for i in range(3)];distance=math.sqrt(sum(x*x for x in ray))
    return distance>0 and sum(a*b for a,b in zip(forward(view),ray))/distance>=.7
checks['top_view_observed']=any(forward(view)[2]<=-.8 for view in views)
robot_bases=[objects[name].get('position',[0,0,0]) for name in robot_ids]
checks['closeup_view_observed']=bool(robot_bases) and any(math.dist(view['position'],base)<=case.get('maximum_closeup_distance_m',3.5) and looks_at(view,base) for view in views for base in robot_bases)
center=[sum(base[i] for base in robot_bases)/len(robot_bases) for i in range(3)] if robot_bases else [0,0,0]
checks['overview_view_observed']=bool(robot_bases) and any(max(math.dist(view['position'],base) for base in robot_bases)>=3 and looks_at(view,center) for view in views)
counter_classes={canonical(o.get('counter',{}).get('class_label')) for o in objects.values() if o.get('kind')=='counter' and o.get('counter',{}).get('source')=='verified_archives'}
indicator_robots={o.get('indicator',{}).get('robot_id') for o in objects.values() if o.get('indicator')}
checks['verified_class_counters']=set(classes).issubset(counter_classes)
checks['controller_indicators']=bool(robot_ids) and robot_ids.issubset(indicator_robots)
def indicator_matches(robot):
    sequence=objects[robot].get('pose_follower',{}).get('sequence',[]);states=[]
    for sample in run.get('samples',[]):
        follower=sample.get('followers',{}).get(robot,{})
        shown=[value.get('controller_phase_state') for value in sample.get('displays',{}).values() if value.get('robot_id')==robot]
        if not shown:continue
        index=follower.get('sequence_index');error=follower.get('sequence_error')
        if error:expected='error'
        elif type(index) is int and index==len(sequence):expected='complete'
        elif type(index) is int and 0<=index<len(sequence):expected='waiting' if sequence[index].get('type')=='wait_object' else 'active'
        else:expected='unknown'
        if any(value!=expected for value in shown):return False
        states.extend(shown)
    return len(set(states))>=2
checks['indicators_follow_observed_phases']=bool(robot_ids) and all(indicator_matches(robot) for robot in robot_ids)
events=run.get('spawn_events',[])
counts={label:sum(canonical(e.get('class_label'))==label for e in events) for label in classes}
checks['multiple_spawned_items_per_class']=all(counts[label]>=case['minimum_items_per_class'] for label in classes)
chutes=[]
for name,obj in objects.items():
    q=obj.get('orientation_wxyz',[1,0,0,0])
    if obj.get('kind')=='box' and obj.get('collision') and not obj.get('dynamic') and len(q)==4 and (abs(q[1])>1e-3 or abs(q[2])>1e-3):
        chutes.append(name)
contacts=run.get('contact_counts') or {}
def chute_flow(event,chute,belt):
    part=event.get('id');path=event.get('path');spawn=event.get('physics_step')
    if not isinstance(part,str) or not isinstance(path,str) or type(spawn) is not int:return False
    chute_prefix=part+'|/World/'+chute.replace('-','_')+'|';belt_prefix=part+'|/World/'+belt.replace('-','_')+'|'
    first_chute=[v.get('first_physics_step') for k,v in contacts.items() if k.startswith(chute_prefix) and v.get('count',0)>0 and type(v.get('first_physics_step')) is int]
    first_belt=[v.get('first_physics_step') for k,v in contacts.items() if k.startswith(belt_prefix) and v.get('count',0)>0 and type(v.get('first_physics_step')) is int]
    if not first_chute or not first_belt or min(first_chute)>=min(first_belt):return False
    points=[s['positions'][path] for s in run.get('samples',[]) if path in s.get('positions',{}) and spawn<=s['physics_steps']<=min(first_belt)+180]
    return bool(len(points)>=2 and max(math.hypot(p[0]-points[0][0],p[1]-points[0][1]) for p in points)>=.2 and points[0][2]-min(p[2] for p in points)>=.1)
checks['physical_chute_feeds_belt']=bool(chutes and belts and any(chute_flow(event,chute,belt) for event in events for chute in chutes for belt in belts))
try:
    # Check an actual colliding tray below and beyond the belt end. The
    # separate recovery probe tests a missed part physically; this geometry
    # check does not invent a missed part in an otherwise successful run.
    from pxr import Usd,UsdGeom
    stage_for_tray=Usd.Stage.Open(str(directory/'scene.usda'))
    bounds_cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render],useExtentsHint=True)
    def bounds_for(name):
        prim=stage_for_tray.GetPrimAtPath('/World/'+name.replace('-','_'))
        if not prim:return None
        box=bounds_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        return ([float(x) for x in box.GetMin()],[float(x) for x in box.GetMax()])
    belt_id=next(iter(belts));belt_bounds=bounds_for(belt_id)
    direction=belts[belt_id].get('direction',[1,0,0]);axis=0 if abs(direction[0])>=abs(direction[1]) else 1
    sign=1 if direction[axis]>0 else -1;side=1-axis
    def along(bounds):
        lo,hi=bounds
        return (lo[axis],hi[axis]) if sign>0 else (-hi[axis],-lo[axis])
    belt_end=along(belt_bounds)[1];belt_lo,belt_hi=belt_bounds
    boxes={name:bounds_for(name) for name,obj in objects.items() if obj.get('kind')=='box' and obj.get('collision') and not obj.get('dynamic') and not obj.get('conveyor')}
    boxes={name:value for name,value in boxes.items() if value is not None}
    tray_found=False
    for name,bounds in boxes.items():
        lo,hi=bounds;front,back=along(bounds);top=hi[2]
        if not (front<=belt_end+.02 and back>=belt_end+.1 and top<=belt_lo[2]-.02 and
                lo[side]<=belt_lo[side]-.02 and hi[side]>=belt_hi[side]+.02):continue
        walls=set()
        for other,wall in boxes.items():
            if other==name:continue
            wlo,whi=wall;wa,wb=along(wall)
            if wlo[2]>top+.03 or whi[2]<top+.08:continue
            center_side=(wlo[side]+whi[side])/2
            if wb-wa>=.15:
                if abs(center_side-lo[side])<=.05:walls.add('left')
                if abs(center_side-hi[side])<=.05:walls.add('right')
            if abs((wa+wb)/2-back)<=.06 and whi[side]-wlo[side]>=belt_hi[side]-belt_lo[side]:walls.add('back')
        if len(walls)==3:tray_found=True;break
    checks['physical_recovery_tray_geometry']=bool(abs(direction[axis])>=.9 and tray_found)
except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError):
    checks['physical_recovery_tray_geometry']=False
try:
    checks['input_integrity']=verify_inputs(directory)['passed']
    sealed=verify_outputs(directory);checks['output_integrity']=sealed['passed'] and not sealed['partial']
except (OSError,ValueError,KeyError,TypeError):
    checks['input_integrity']=checks['output_integrity']=False
try:
    package=json.loads((root/'package-hashes.json').read_text());prefix='server/vendor/simscene/'
    worker={name[len(prefix):]:value for name,value in package.items() if name.startswith(prefix)}
    checks['worker_matches_frozen_package']=bool(worker) and worker==lock.get('worker_code_sha256')
    prefix='skills/';expected={name[len(prefix):]:value for name,value in package.items() if name.startswith(prefix)}
    skill_root=root/'work'/'.agents'/'skills'
    observed={str(path.relative_to(skill_root)):digest(path) for path in skill_root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
    checks['skill_matches_frozen_package']=bool(expected) and expected==observed
except (OSError,ValueError,KeyError,TypeError):
    checks.update(worker_matches_frozen_package=False,skill_matches_frozen_package=False)
try:
    report=evaluate(directory)
    checks['pinned_physical_case_passed']=bool(report['case_pinned_to_run'] and report['passed'])
    physical_case=json.loads((directory/lock['acceptance_case_file']).read_text())
    owners={label:{entry.get('robot_id') for entry in physical_case['objects'] if canonical(entry.get('class_label'))==label} for label in classes}
    checks['distinct_robot_per_class']=all(len(owners[label])==1 for label in classes) and {next(iter(owners[label])) for label in classes}==robot_ids and len(robot_ids)==len(classes)
    entries=report['ledger']['objects']
    correct={label:sum(canonical(e.get('class_label'))==label and e.get('state')=='correct' for e in entries) for label in classes}
    checks['physical_success_per_class']=all(correct[label]>=case['minimum_items_per_class'] for label in classes)
    checks['no_wrong_bin']=report['ledger']['wrong_bin']==0
    interval=report.get('parallel_steps')
    checks['simultaneous_robot_cycles']=bool(checks['distinct_robot_per_class'] and interval and interval[1]-interval[0]>=case['minimum_parallel_steps'])
    snapshot=next((sample for sample in reversed(run.get('samples',[])) if sample.get('verified_counts')), {})
    measured={}
    for label,value in (snapshot.get('verified_counts') or {}).get('by_class',{}).items():
        name=canonical(label);measured[name]=measured.get(name,0)+value
    displays=snapshot.get('displays',{})
    checks['displayed_counts_match_verified_ledger']=all(measured.get(label,0)==correct[label] and any(
        value.get('source')=='verified_archives' and canonical(value.get('class_label'))==label and value.get('available') and value.get('value')==correct[label]
        for value in displays.values()) for label in classes)
    # Verify actual archived object bounds against modeled box floors and four
    # walls, rather than trusting destination bounds supplied by the agent.
    from pxr import Usd,UsdGeom
    stage=Usd.Stage.Open(str(directory/'scene.usda'))
    cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render],useExtentsHint=True)
    boxes={}
    for name,obj in objects.items():
        if obj.get('kind')!='box' or not obj.get('collision') or obj.get('dynamic') or obj.get('conveyor'):
            continue
        prim=stage.GetPrimAtPath('/World/'+name.replace('-','_'))
        if prim:
            bound=cache.ComputeWorldBound(prim).ComputeAlignedRange()
            boxes[name]=([float(x) for x in bound.GetMin()],[float(x) for x in bound.GetMax()])
    def enclosure(part_bounds):
        lo=part_bounds['min'];hi=part_bounds['max']
        for name,(a,b) in boxes.items():
            if not (a[0]-.003<=lo[0] and hi[0]<=b[0]+.003 and a[1]-.003<=lo[1] and hi[1]<=b[1]+.003 and abs(lo[2]-b[2])<=.02):
                continue
            walls=set()
            for other,(c,d) in boxes.items():
                if other==name or d[2]<hi[2] or c[2]>lo[2]+.06:
                    continue
                if c[1]<=lo[1] and d[1]>=hi[1]:
                    if abs((c[0]+d[0])/2-a[0])<=.04:walls.add('left')
                    if abs((c[0]+d[0])/2-b[0])<=.04:walls.add('right')
                if c[0]<=lo[0] and d[0]>=hi[0]:
                    if abs((c[1]+d[1])/2-a[1])<=.04:walls.add('front')
                    if abs((c[1]+d[1])/2-b[1])<=.04:walls.add('back')
            if len(walls)==4:return name
        return None
    class_bins={}
    archived=run.get('archived_objects',{})
    for label in classes:
        found={enclosure(archived[e['id']]['bounds']) for e in entries
               if canonical(e.get('class_label'))==label and e.get('state')=='correct' and e['id'] in archived and 'bounds' in archived[e['id']]}
        if None not in found and len(found)==1:class_bins[label]=next(iter(found))
    checks['correct_objects_in_distinct_physical_bins']=len(class_bins)==len(classes) and len(set(class_bins.values()))==len(classes)
except (OSError,ValueError,KeyError,TypeError,IndexError,ImportError,RuntimeError,AttributeError):
    report=None;correct={}
    checks.update(pinned_physical_case_passed=False,physical_success_per_class=False,no_wrong_bin=False,
                  simultaneous_robot_cycles=False,displayed_counts_match_verified_ledger=False,correct_objects_in_distinct_physical_bins=False,distinct_robot_per_class=False)
summary={'passed':all(checks.values()),'checks':checks,'run_directory':str(directory),
         'spawned_by_class':counts,'correct_by_class':correct,'robot_ids':sorted(robot_ids),
         'case_sha256':digest(case_path),'scope':case['scope']}
print(json.dumps(summary,ensure_ascii=False,indent=2))
raise SystemExit(0 if summary['passed'] else 1)
