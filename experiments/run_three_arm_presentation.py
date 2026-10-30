"""Record four views of a genuine, independently configured simulation run.

Run only when an Isaac GPU is available.  This is a presentation run, not a
replacement for the longer, independently checked acceptance suite.  The source
scene remains unchanged and the fixed acceptance case remains pinned to the run.
"""
import copy
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from simscene.jobs import start, status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate

if len(sys.argv) != 4:
    raise SystemExit('usage: run_three_arm_presentation.py SOURCE_SCENE CASE_JSON FEEDER_Y_OFFSET')
source, case, feeder_offset = sys.argv[1], sys.argv[2], float(sys.argv[3])
if not -.04 <= feeder_offset <= .04:
    raise SystemExit('feeder offset outside tested diagnostic range')
spacing_factor=float(os.environ.get('SIMSCENE_PRESENTATION_SPACING_FACTOR','1.0'))
if not 1.0<=spacing_factor<=2.0:
    raise SystemExit('presentation spacing factor must be between 1 and 2')
class_order=[x.strip() for x in os.environ.get('SIMSCENE_PRESENTATION_CLASS_ORDER','').split(',') if x.strip()]
bin_offset=float(os.environ.get('SIMSCENE_PRESENTATION_GREEN_BIN_Y_OFFSET','0'))
if not -.12 <= bin_offset <= 0:
    raise SystemExit('green bin offset outside diagnostic range')
lift_settle_steps=int(os.environ.get('SIMSCENE_PRESENTATION_LIFT_SETTLE_STEPS','15'))
if not 5 <= lift_settle_steps <= 15:
    raise SystemExit('lift settling outside diagnostic range')
store = SceneStore()
objects = copy.deepcopy(store.get(source)['objects'])
# Presentation-only, non-colliding housing and colour accents.  The conveyor
# surface, robot models, workpieces, controller phases and verification case
# remain the same physical mechanisms as in the source scene.
objects['sun']['intensity'] = 500
objects['ambient'] = {'kind':'light','intensity':300,'light':{'type':'dome'}}
objects['floor']['size'] = [30, 30, .1]
objects['floor']['material'] = {'color': [.10, .13, .17], 'roughness': .8}
objects['belt']['material'] = {'color': [.08, .11, .15], 'roughness': .75}
# The separately tested feeder changes the actual workpiece origin. Record a
# separate case with that origin before the run; no acceptance threshold changes.
spawn_steps=[value['spawn_step'] for value in objects.values() if value.get('dynamic') and value.get('spawn_step',0)>0]
first_spawn=min(spawn_steps) if spawn_steps else 0
ordered_steps=sorted(spawn_steps)
base_intervals=[b-a for a,b in zip(ordered_steps,ordered_steps[1:])]
for value in objects.values():
    if value.get('dynamic') and value.get('spawn_step', 0) > 0:
        value['position'] = [-1.23, -.5 + feeder_offset, .84]
        value['spawn_step']=first_spawn+round((value['spawn_step']-first_spawn)*spacing_factor)
    for phase in value.get('pose_follower',{}).get('sequence',[]):
        if phase.get('type')=='wait_object':phase['max_steps']=18000
if class_order:
    from simscene.scene_edits.interleave import interleave
    if not base_intervals or len(set(base_intervals))!=1 or base_intervals[0]<=0:
        raise SystemExit('class order requires an evenly spaced source stream')
    ids=[name for name,value in objects.items() if value.get('dynamic') and value.get('spawn_step',0)>0]
    interval=round(base_intervals[0]*spacing_factor)
    proposal=interleave({'objects':objects},ids,class_order,interval,first_spawn)
    for operation in proposal['operations']:
        objects[operation['id']]['spawn_step']=operation['changes']['spawn_step']
angle = .65
orientation = [math.cos(angle/2), 0, math.sin(angle/2), 0]
objects['chute'] = {'kind': 'box', 'position': [-1, -.5 + feeder_offset, .6], 'size': [.8, .12, .02],
                    'orientation_wxyz': orientation, 'collision': True,
                    'material': {'color': [.18, .24, .30], 'metallic': .4, 'roughness': .5}}
for side, y in (('left', -.56), ('right', -.44)):
    objects['chute_'+side] = {'kind': 'box', 'position': [-1, y + feeder_offset, .65], 'size': [.8, .01, .10],
                             'orientation_wxyz': orientation, 'collision': True,
                             'material': {'color': [.18, .24, .30], 'metallic': .4, 'roughness': .5}}
palette = {'k': [.52, .09, .08], 'f': [.08, .43, .19], 'u': [.06, .19, .55]}
for key, value in objects.items():
    for prefix, color in palette.items():
        if key.startswith('bin_'+prefix+'_'):
            value['material'] = {'color': color, 'roughness': .6}
# A bin wall beside the belt can trap passing workpieces.  Translate the
# complete physical bin and the corresponding drop waypoints together; the
# independent case bounds are translated below before this run is frozen.
if bin_offset:
    for key, obj in objects.items():
        if key.startswith('bin_f_'):
            obj['position'][1] += bin_offset
    for phase in objects['franka']['pose_follower']['sequence']:
        position=phase.get('position')
        if position and abs(position[0]-2.32)<1e-8 and abs(position[1]+.64)<1e-8:
            position[1] += bin_offset
# Keep the same measured joint-speed threshold and target tolerance, but allow
# the lifted pose to advance after a shorter continuous settled interval.
# The full physical case still independently checks contacts and placement.
for phase in objects['franka']['pose_follower']['sequence']:
    if phase.get('type')=='move' and phase.get('object'):
        phase['settle_steps']=lift_settle_steps
objects['belt_housing'] = {'kind': 'box', 'position': [2, -.5, .19], 'size': [5.9, .32, .12],
                           'material': {'color': [.16, .21, .27], 'metallic': .5, 'roughness': .4}}
reference=os.environ.get('SIMSCENE_RECOVERY_TRAY_SCENE')
if reference:
    checked=json.loads(open(reference).read())['objects']
    for key in ('reject_floor','reject_left','reject_right','reject_back'):
        if objects[key]!=checked.get(key):raise SystemExit('presentation tray differs from the physically checked tray')
for index, x in enumerate((-.6, .5, 1.6, 2.7, 3.8, 4.75)):
    objects['belt_support_'+str(index)] = {'kind': 'box', 'position': [x, -.5, .09],
        'size': [.12, .25, .18], 'material': {'color': [.19, .24, .30], 'metallic': .5, 'roughness': .45}}
for side, y in (('near', -.655), ('far', -.345)):
    objects['belt_trim_'+side] = {'kind': 'box', 'position': [2, y, .275], 'size': [5.9, .018, .018],
        'material': {'color': [.04, .45, .60], 'metallic': .3, 'roughness': .35}}
# All frames are generated by the running simulator.  The static overview is
# continuous; the other independently recorded views can be used as cutaways.
objects['overview'].update({'position': [8.8, -11.5, 6.8], 'record_fps': 30, 'preview_fps': 1})
objects['top_view'] = {'kind': 'camera', 'position': [2, -0.48, 7], 'record_fps': 30}
objects['grasp_view'] = {'kind': 'camera', 'position': [.95, -1.55, 1.35], 'record_fps': 30}
last_spawn=max((value.get('spawn_step',0) for value in objects.values() if value.get('dynamic')),default=0)
steps=max(24000,math.ceil((last_spawn+20000)/6000)*6000)
if steps>72000:raise SystemExit('presentation exceeds maximum supported duration')
objects['moving_view'] = {'kind': 'camera', 'record_fps': 30, 'camera_orbit': {
    'center': [2, -0.5, 0.5], 'radius_m': 7.5, 'height_m': 4.0,
    'duration_s': steps/60, 'turns': 0.35, 'start_angle_rad': -1.2}}
# Recipe camera names remain here; the execution and native capture settings
# are shared with other scene recipes. Default to two HD cameras, not four.
plan_file=os.environ.get('SIMSCENE_PRESENTATION_CAMERA_PLAN')
if plan_file:
    camera_plan=json.loads(Path(plan_file).read_text())
    for key in list(objects):
        if objects[key].get('kind')=='camera':del objects[key]
    objects.update(camera_plan)
else:
    objects.pop('top_view',None);objects.pop('moving_view',None)
name = 'three_arm_showcase'
fresh = store.open(name)
if fresh['revision'] or fresh['objects']:
    raise SystemExit('showcase scene already exists; use a fresh scene store')
ops = [{'op': 'add', 'id': key, 'object': value} for key, value in objects.items()]
if not plan_file:
    ops += [{'op':'look_at','id':'overview','target':[2.15,-.5,.45]},
            {'op':'look_at','id':'grasp_view','target':[2.05,-.5,.35]}]
ops.append({'op':'set_presentation','presentation':{'profile':'technical_showcase_1080p','budget':{'max_cameras':2}}})
store.apply(name, 0, 'showcase', ops)
case_data = json.loads(open(case).read())
if len(case_data.get('objects', [])) != 18:
    raise SystemExit('presentation requires the frozen 18-object case')
case_data['upstream_position'] = [-1.23, -.5 + feeder_offset, .84]
if bin_offset:
    for item in case_data['objects']:
        if item.get('robot_id') == 'franka':
            item['bin_min'][1] += bin_offset
            item['bin_max'][1] += bin_offset
if class_order:
    case_data['expected_spawn_order']=[name for _,name in sorted((obj['spawn_step'],name) for name,obj in objects.items() if obj.get('dynamic') and obj.get('spawn_step',0)>0)]
showcase_case = store.path/'showcase-case.json'
if showcase_case.exists():
    raise SystemExit('showcase case already exists')
showcase_case.write_text(json.dumps(case_data, indent=2)+'\n')
(store.path/'presentation-plan.json').write_text(json.dumps({'spacing_factor':spacing_factor,'class_order':class_order,'green_bin_y_offset':bin_offset,'franka_lift_settle_steps':lift_settle_steps,'first_spawn':first_spawn,
    'last_spawn':last_spawn,'requested_physics_steps':steps,'acceptance_thresholds':case_data.get('acceptance_thresholds')},indent=2)+'\n')
frozen=store.path/'presentation-builder-frozen.py';frozen.write_bytes(Path(__file__).read_bytes())
frozen_hash=hashlib.sha256(frozen.read_bytes()).hexdigest()
(store.path/'presentation-builder-frozen.sha256').write_text(frozen_hash+'\n')
if os.environ.get('SIMSCENE_PRESENTATION_BUILD_ONLY') == '1':
    print(json.dumps({'scene':name,'case':str(showcase_case),'state':'built_only'}))
    raise SystemExit(0)
job = start(name, steps, 17, str(showcase_case), archive_verified_objects=True)
directory = (store.path / 'runs' / job['run_id']).resolve()
while True:
    current = status(job['job_id'])
    if current['state'] not in ('queued', 'running', 'paused'):
        break
    time.sleep(3)
(directory / 'job-status.json').write_text(json.dumps(current, indent=2) + '\n')
report = {}
if current['state'] == 'completed':
    report = evaluate(directory)
    (directory / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
passed=(current['state']=='completed' and current.get('exit_code')==0 and
        current.get('exit_code_inferred') is False and report.get('passed') is True)
passed=passed and hashlib.sha256(frozen.read_bytes()).hexdigest()==frozen_hash
print(json.dumps({'directory': str(directory), 'state': current['state'], 'passed':passed,
                  'exit_code': current.get('exit_code'), 'simulated_seconds': steps/60}))
raise SystemExit(0 if passed else 1)
