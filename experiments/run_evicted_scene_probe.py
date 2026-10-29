"""Run a saved scene whose selected online asset has been evicted."""
import json,sys,time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
if len(sys.argv)!=2:raise SystemExit('usage: run_evicted_scene_probe.py SCENE_ID')
name=sys.argv[1];store=SceneStore();scene=store.get(name);old=scene['objects']['franka']['asset_path']
store.apply(name,scene['revision'],'observe-restored-asset',[
 {'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[6,6,.1],'collision':True}},
 {'op':'add','id':'ambient','object':{'kind':'light','intensity':300,'light':{'type':'dome'}}},
 {'op':'add','id':'sun','object':{'kind':'light','intensity':700}},
 {'op':'add','id':'view','object':{'kind':'camera','position':[3,-3,2]}},
 {'op':'look_at','id':'view','target':[0,0,.5]}])
job=start(name,120,17);run=(store.path/'runs'/job['run_id']).resolve()
while True:
 current=status(job['job_id'])
 if current['state'] not in ('queued','running','paused'):break
 time.sleep(2)
(run/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
result=current.get('result') or {};inputs=verify_inputs(run);outputs=verify_outputs(run)
lock=json.loads((run/'asset-lock.json').read_text());saved=store.get(name)
checks={'completed':current['state']=='completed' and current.get('exit_code')==0 and current.get('exit_code_inferred') is False,
 'all_steps':result.get('actual_physics_steps')==120,'original_path_still_absent':not Path(old).exists(),
 'saved_path_unchanged':saved['objects']['franka']['asset_path']==old,
 'asset_snapshotted':lock.get('franka',{}).get('kind')=='snapshot',
 'rendered_image':bool(result.get('images',{}).get('view')),
 'input_integrity':inputs.get('passed') is True,'output_integrity':outputs.get('passed') is True and not outputs.get('partial')}
report={'passed':all(checks.values()),'checks':checks,'directory':str(run),'scope':'actual 6.2 simulation after automatic restoration of a saved asset path; no robot manipulation'}
(run/'recovery-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
raise SystemExit(0 if report['passed'] else 1)
