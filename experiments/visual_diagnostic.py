"""Record matching real grasp intervals at native resolutions (no image synthesis)."""
import argparse,copy,json,os,time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--mode',choices=['baseline','native','quality','dlaa'],required=True)
a=p.parse_args();root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False)
os.environ['SIMSCENE_HOME']=str(root/'state');os.environ.setdefault('SIMSCENE_ISAAC_PYTHON','/data/omniverse/isaac-sim-6.2.0/python.sh')
project=Path(__file__).resolve().parents[1]/'deliverables/triarm_sorting'
data=json.loads((project/'sorting_station.scene.json').read_text());objects=copy.deepcopy(data['objects'])
for name in list(objects):
 obj=objects[name]
 if obj.get('kind')=='camera' and name!='grip_close':del objects[name];continue
 if 'asset_path' in obj:
  folder='assets' if '/assets/' in obj['asset_path'] else 'authored'
  obj['asset_path']=str(project/folder/obj['asset_path'].split('/'+folder+'/',1)[1])
 cfg=obj.get('pose_follower')
 if cfg:
  cfg['model_directory']=str(project/'controllers'/cfg['model_directory'].split('/controllers/',1)[1])
  if cfg.get('gripper_urdf'):cfg['gripper_urdf']=str(project/'controllers'/cfg['gripper_urdf'].split('/controllers/',1)[1])
  # Camera/clock diagnostic only. Full discrete audit is retained in the final
  # enriched nine-item run, not repeated for every render-quality comparison.
  cfg['diagnose_overlaps']=False
camera=objects['grip_close'];camera['record_fps']=6 if a.mode=='baseline' else 30
camera['preview_fps']=1;camera['camera']={'resolution':[640,480] if a.mode=='baseline' else [1920,1080],
 'capture_window':{'start_step':2820,'end_step':3420},'focal_length_mm':24,'horizontal_aperture_mm':36}
store=SceneStore();store.open('diagnostic')
ops=[{'op':'add','id':n,'object':o} for n,o in objects.items()]
if a.mode in ('quality','dlaa'):
 ops.append({'op':'set_presentation','presentation':{'profile':'technical_showcase_1080p','capture':{'anti_aliasing':'dlaa' if a.mode=='dlaa' else 'dlss_quality'},'diagnostics':{'keyframe_interval_s':1},'budget':{'max_cameras':1}}})
store.apply('diagnostic',0,'setup',ops)
job=start('diagnostic',3420,42,request_id='diagnostic-'+a.mode)
(root/'job.json').write_text(json.dumps(job,indent=2));print(json.dumps(job),flush=True)
previous=None
while True:
 state=status(job['job_id']);progress=state.get('progress',{});step=progress.get('physics_steps',0) if isinstance(progress,dict) else 0
 marker=(state['state'],step//600)
 if marker!=previous:print(json.dumps({'state':state['state'],'step':step}),flush=True);previous=marker
 if state['state'] not in ('queued','running','paused'):break
 time.sleep(1)
(root/'status.json').write_text(json.dumps(state,indent=2))
print(json.dumps(state),flush=True)
raise SystemExit(0 if state['state']=='completed' else 1)
