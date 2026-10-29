"""Gate the 6.2 online-asset suite on a complete, independently checked probe."""
import copy, hashlib, json, math, os, shutil, subprocess, sys, time
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs

if len(sys.argv) != 5:
    raise SystemExit('usage: run_formal_after_online_probe.py PROBE_RUN SUITE_HOME PRESENTATION_HOME RECOVERY_RUN')
probe=Path(sys.argv[1]).resolve(); home=Path(sys.argv[2]).resolve(); presentation=Path(sys.argv[3]).resolve();recovery=Path(sys.argv[4]).resolve()
while not (probe/'job-status.json').is_file():
    time.sleep(5)
status=json.loads((probe/'job-status.json').read_text())
report_path=probe/'verification.json'
if status.get('state') == 'completed':
    deadline=time.monotonic()+300
    while not report_path.is_file() and time.monotonic()<deadline:
        time.sleep(1)
case=json.loads(report_path.read_text()) if report_path.is_file() else {}
try:
    inputs=verify_inputs(probe); outputs=verify_outputs(probe)
except Exception as exc:
    inputs={'passed':False,'error':repr(exc)};outputs={'passed':False,'partial':True}
checks={'completed':status.get('state')=='completed','observed_exit_zero':status.get('exit_code')==0 and status.get('exit_code_inferred') is False,
        'fixed_case_passed':case.get('passed') is True,'input_integrity':inputs.get('passed') is True,
        'output_integrity':outputs.get('passed') is True and not outputs.get('partial')}
gate={'probe':str(probe),'checks':checks,'passed':all(checks.values())}
(home/'probe-gate.json').write_text(json.dumps(gate,indent=2)+'\n')
print(json.dumps(gate),flush=True)
if not gate['passed']:
    raise SystemExit(1)
while not (presentation/'presentation-exit.json').is_file():
    if (presentation/'presentation-gate.json').is_file():
        try: pg=json.loads((presentation/'presentation-gate.json').read_text())
        except (OSError,ValueError):pg={}
        if pg and not pg.get('passed'):
            gate.update(passed=False,presentation_gate=pg)
            (home/'probe-gate.json').write_text(json.dumps(gate,indent=2)+'\n')
            raise SystemExit(1)
    time.sleep(5)
exit_record=json.loads((presentation/'presentation-exit.json').read_text())
while not (recovery/'recovery-verification.json').is_file():time.sleep(5)
try:
    summary=json.loads((presentation/'presentation.stdout').read_text().splitlines()[-1])
    run=Path(summary['directory']).resolve()
    physical=json.loads((run/'verification.json').read_text())
    pin=verify_inputs(run);pout=verify_outputs(run)
    if (exit_record.get('exit_code')!=0 or summary.get('passed') is not True or physical.get('passed') is not True or
            pin.get('passed') is not True or pout.get('passed') is not True or pout.get('partial')):
        raise ValueError('presentation did not pass its full physical case and locks')
    recovery_report=json.loads((recovery/'recovery-verification.json').read_text())
    recovery_inputs=verify_inputs(recovery);recovery_outputs=verify_outputs(recovery)
    if recovery_report.get('passed') is not True or recovery_inputs.get('passed') is not True or recovery_outputs.get('passed') is not True or recovery_outputs.get('partial'):
        raise ValueError('physical missed-item recovery probe did not pass')
    from simscene.scene import SceneStore
    store=SceneStore(); scene=store.get('stream'); visual=store.get('three_arm_showcase') if store.path==presentation else json.loads((presentation/'three_arm_showcase.json').read_text())
    visual_objects=visual['objects'];ops=[]
    recovery_objects=json.loads((recovery.parent.parent/'recovery.json').read_text())['objects']
    for name in ('reject_floor','reject_left','reject_right','reject_back'):
        if scene['objects'].get(name)!=recovery_objects.get(name) or visual_objects.get(name)!=recovery_objects.get(name):
            raise ValueError('formal or presentation recovery tray differs from the physically tested geometry')
    for robot in ('kawasaki','franka','ur10'):
        if scene['objects'][robot]['asset_path']!=visual_objects[robot]['asset_path']:
            raise ValueError('presentation and formal suite use different robot assets')
    original=(home/'case.json').read_bytes()
    original_case=json.loads(original)
    presentation_case=json.loads((presentation/'showcase-case.json').read_text())
    # Copy a physically verified bin translation to the formal geometry, drop
    # targets, and independently frozen case together.  Reject partial changes.
    bin_offset=visual_objects['bin_f_floor']['position'][1]-scene['objects']['bin_f_floor']['position'][1]
    if not -.12 <= bin_offset <= 0:
        raise ValueError('presentation green-bin translation is outside diagnostic limits')
    for name,obj in scene['objects'].items():
        if name.startswith('bin_f_'):
            expected=copy.deepcopy(obj['position']); expected[1]+=bin_offset
            shown=visual_objects[name]
            if any(abs(a-b)>1e-8 for a,b in zip(expected,shown['position'])) or obj.get('size')!=shown.get('size') or obj.get('orientation_wxyz')!=shown.get('orientation_wxyz'):
                raise ValueError('presentation contains an inconsistent bin translation')
            if bin_offset:
                ops.append({'op':'update','id':name,'changes':{'position':expected}})
    checked_lift=[phase for phase in visual_objects['franka']['pose_follower']['sequence']
                  if phase.get('type')=='move' and phase.get('object')]
    if not checked_lift or len({phase.get('settle_steps') for phase in checked_lift})!=1:
        raise ValueError('presentation has inconsistent lift settling')
    lift_settle_steps=checked_lift[0]['settle_steps']
    if type(lift_settle_steps) is not int or not 5<=lift_settle_steps<=15:
        raise ValueError('presentation lift settling outside diagnostic limits')
    original_by_part={item['part_id']:item for item in original_case['objects']}
    for item in presentation_case['objects']:
        reference=original_by_part[item['part_id']]
        for key in ('bin_min','bin_max'):
            expected=copy.deepcopy(reference[key])
            if item.get('robot_id')=='franka':expected[1]+=bin_offset
            if any(abs(a-b)>1e-8 for a,b in zip(expected,item[key])):
                raise ValueError('presentation case bounds do not match translated physical bin')
    order=original_case['expected_spawn_order']
    visual_order=sorted((obj['spawn_step'],name) for name,obj in visual_objects.items() if obj.get('dynamic') and obj.get('spawn_step',0)>0)
    if len(visual_order)!=18:raise ValueError('presentation does not contain the expected 18 spawned objects')
    visual_steps=[step for step,name in visual_order]
    intervals=[b-a for a,b in zip(visual_steps,visual_steps[1:])]
    if not intervals or len(set(intervals))!=1 or intervals[0]<=0:
        raise ValueError('presentation spawn timing is not a regular ordered stream')
    first_spawn=visual_steps[0];interval=intervals[0]
    class_order=[visual_objects[name].get('class_label') for _,name in visual_order[:3]]
    from simscene.scene_edits.interleave import interleave
    proposed=interleave(scene,order,class_order,interval,first_spawn)
    ordered=[row['id'] for row in proposed['schedule']]
    if [name for _,name in visual_order]!=ordered[:18]:
        raise ValueError('presentation part order does not match the proposed formal schedule')
    schedule={row['id']:row['spawn_step'] for row in proposed['schedule']}
    requested_steps=max(48000,math.ceil((max(schedule.values())+17000)/6000)*6000)
    if requested_steps>72000:raise ValueError('validated stream timing exceeds the supported formal duration')
    for name,obj in scene['objects'].items():
        changes={}
        if obj.get('dynamic') and obj.get('spawn_step',0)>0:
            changes['position']=copy.deepcopy(visual_objects['part0000']['position'])
            if name not in schedule:raise ValueError('formal spawned object is absent from the frozen case')
            changes['spawn_step']=schedule[name]
        if 'pose_follower' in obj:
            follower=copy.deepcopy(obj['pose_follower'])
            for phase in follower.get('sequence',[]):
                if phase.get('type')=='wait_object':phase['max_steps']=18000
                position=phase.get('position')
                if name=='franka' and bin_offset and position and abs(position[0]-2.32)<1e-8 and abs(position[1]+.64)<1e-8:
                    position[1]+=bin_offset
                if name=='franka' and phase.get('type')=='move' and phase.get('object'):
                    phase['settle_steps']=lift_settle_steps
            if name=='franka':
                visual_phases=visual_objects[name]['pose_follower']['sequence']
                for candidate, checked in zip(follower['sequence'],visual_phases):
                    a=candidate.get('position'); b=checked.get('position')
                    if (a is None)!=(b is None) or (a is not None and (len(a)!=len(b) or any(abs(x-y)>1e-8 for x,y in zip(a,b)))):
                        raise ValueError('formal and physically verified Franka waypoints differ')
                    if candidate.get('type')=='move' and candidate.get('object'):
                        if any(candidate.get(k)!=checked.get(k) for k in ('object','offset','settle_steps','max_joint_speed','tolerance_m')):
                            raise ValueError('formal and physically verified lift settings differ')
            changes['pose_follower']=follower
        if changes:ops.append({'op':'update','id':name,'changes':changes})
    for name in ('chute','chute_left','chute_right','ambient'):
        if name in scene['objects']:raise ValueError('formal scene already contains feeder preparation')
        ops.append({'op':'add','id':name,'object':copy.deepcopy(visual_objects[name])})
    (home/'case-before-feeder.json').write_bytes(original)
    revised=copy.deepcopy(original_case);revised['upstream_position']=copy.deepcopy(visual_objects['part0000']['position'])
    revised['expected_spawn_order']=ordered
    if bin_offset:
        for item in revised['objects']:
            if item.get('robot_id')=='franka':
                item['bin_min'][1]+=bin_offset
                item['bin_max'][1]+=bin_offset
    store.apply('stream',scene['revision'],'attach-verified-feeder',ops)
    (home/'case.json').write_text(json.dumps(revised,indent=2)+'\n')
    (home/'suite-feeder-plan.json').write_text(json.dumps({'presentation_run':str(run),'recovery_run':str(recovery),
        'original_case_sha256':hashlib.sha256(original).hexdigest(),
        'prepared_case_sha256':hashlib.sha256((home/'case.json').read_bytes()).hexdigest(),
        'unchanged_acceptance_thresholds':revised['acceptance_thresholds']==original_case['acceptance_thresholds'],
        'unchanged_collision_policy':revised['collision_policy']==original_case['collision_policy'],
        'spawn_position':revised['upstream_position'],'green_bin_y_offset':bin_offset,'franka_lift_settle_steps':lift_settle_steps,'wait_max_steps':18000,'spawn_interval_steps':interval,'class_order':class_order,
        'requested_physics_steps':requested_steps,
        'scope':'prepared before all formal runs from the independently checked feeder presentation'},indent=2)+'\n')
except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
    gate.update(passed=False,presentation_error=str(exc))
    (home/'probe-gate.json').write_text(json.dumps(gate,indent=2)+'\n')
    raise SystemExit(1)
env=dict(os.environ,SIMSCENE_HOME=str(home))
case_path=str(home/'case.json')
frozen=home/'negative-frozen'
frozen.mkdir(exist_ok=False)
hashes={}
for filename in ('run_three_arm_negative_control.py','verify_three_arm_negative_control.py'):
    source=Path('experiments')/filename;shutil.copyfile(source,frozen/filename)
    hashes[filename]=hashlib.sha256((frozen/filename).read_bytes()).hexdigest()
(frozen/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
harness=home/'suite-frozen';harness.mkdir(exist_ok=False);harness_hashes={}
for filename in ('run_formal_suite.py','run_negative_suite.py'):
    shutil.copyfile(Path('experiments')/filename,harness/filename)
    harness_hashes[filename]=hashlib.sha256((harness/filename).read_bytes()).hexdigest()
(harness/'sha256.json').write_text(json.dumps(harness_hashes,indent=2)+'\n')
with (home/'suite.stdout').open('w') as suite_out, (home/'suite.stderr').open('w') as suite_err, (home/'negative.stdout').open('w') as neg_out, (home/'negative.stderr').open('w') as neg_err:
    suite=subprocess.Popen([sys.executable,str(harness/'run_formal_suite.py'),'stream',case_path,str(requested_steps)],env=env,stdout=suite_out,stderr=suite_err)
    negative=subprocess.Popen([sys.executable,str(harness/'run_negative_suite.py'),'stream',case_path],env=env,stdout=neg_out,stderr=neg_err)
    suite_code=suite.wait();negative_code=negative.wait()
result={'suite_exit':suite_code,'negative_exit':negative_code,'passed':suite_code==0 and negative_code==0}
(home/'combined-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(0 if result['passed'] else 1)
