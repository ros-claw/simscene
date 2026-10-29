"""Run a short, opt-in PhysX overlap diagnostic on a saved scene spec."""
import json
import sys
import time
from simscene.jobs import start,status
from simscene.scene import SceneStore

if len(sys.argv)!=2:raise SystemExit('usage: run_overlap_diagnostic.py SCENE_SPEC_JSON')
scene=json.load(open(sys.argv[1]))
for obj in scene['objects'].values():
    if 'pose_follower' in obj:
        obj['pose_follower']['self_collision_enabled']=True
        obj['pose_follower']['diagnose_overlaps']=True
store=SceneStore();store.open('overlap_diagnostic')
store.apply('overlap_diagnostic',0,'configure',[{'op':'add','id':name,'object':obj} for name,obj in scene['objects'].items()])
job=start('overlap_diagnostic',120,17)
while True:
    result=status(job['job_id'])
    if result['state'] not in ('queued','running','paused'):print(json.dumps(result,indent=2));break
    time.sleep(1)
