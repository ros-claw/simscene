"""Compare an offset physical chute with the completed showcase diagnostic.

This is a new diagnostic, not a formal 60-item acceptance run. It changes only
feed lateral placement and camera recording, retaining the original checker
thresholds and all item definitions. A 15,000-step run leaves future spawns
pending, so a full-case failure is expected and must not be labeled a pass.
"""
import copy
import json
import sys
import time
from pathlib import Path
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate

if len(sys.argv)!=4:
    raise SystemExit('usage: run_feeder_alignment_probe.py SOURCE_SCENE CASE_JSON Y_OFFSET_M')
source, case_path, offset = sys.argv[1], Path(sys.argv[2]), float(sys.argv[3])
if not -.04 <= offset <= .04: raise SystemExit('offset outside diagnostic range')
store=SceneStore();objects=copy.deepcopy(store.get(source)['objects'])
for name,obj in objects.items():
    if name in ('chute','chute_left','chute_right') or obj.get('dynamic') and obj.get('spawn_step',0)>0:
        obj['position'][1]+=offset
    # The chute adds travel time before the belt. Give each robot's wait
    # phase enough time to observe that physical trip; do not change the
    # placement, collision, class or success-rate checks.
    for phase in obj.get('pose_follower',{}).get('sequence',[]):
        if phase.get('type')=='wait_object':phase['max_steps']=18000
for name in ('top_view','grasp_view','moving_view'):
    objects.pop(name,None)
objects['overview']['record_fps']=2
scene='feeder_offset_probe';store.open(scene)
store.apply(scene,0,'configure',[{'op':'add','id':name,'object':obj} for name,obj in objects.items()])
case=json.loads(case_path.read_text());case['upstream_position'][1]+=offset
case_file=store.path/'feeder-offset-case.json';case_file.write_text(json.dumps(case,indent=2)+'\n')
job=start(scene,15000,17,str(case_file),archive_verified_objects=True)
directory=(store.path/'runs'/job['run_id']).resolve()
while True:
    current=status(job['job_id'])
    if current['state'] not in ('queued','running','paused'):break
    time.sleep(3)
(directory/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
if current['state']=='completed':
    report=evaluate(directory);(directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'directory':str(directory),'state':current['state'],'offset_y_m':offset,'scope':'partial 25-item diagnostic, not full acceptance'}))
raise SystemExit(0 if current['state']=='completed' else 1)
