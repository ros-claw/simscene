"""Export an editable local project from an intact real run, without source mutation.

Third-party geometry remains a local delivery. Do not add the resulting assets
to Git without their licenses. The run's original evidence is referenced by hash;
the editable project is a new artifact, not a replacement for that evidence.
"""
import argparse,copy,hashlib,json,os,shutil
from pathlib import Path
from simscene.run_integrity import verify as verify_input
from simscene.evidence_integrity import verify as verify_output
from simscene.usd_export import export_scene

LAUNCHER='''"""Reopen the editable project using its frozen SimScene worker package."""
import argparse,copy,hashlib,json,os,sys,time,uuid
from pathlib import Path
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--scene-file',default='scene.json');p.add_argument('--case-file',default='case.json');p.add_argument('--steps',type=int);p.add_argument('--isaac-python',default=os.getenv('SIMSCENE_ISAAC_PYTHON'));a=p.parse_args()
manifest=json.load(open(root/'project.json'));scene=json.load(open(root/a.scene_file))
os.environ['SIMSCENE_HOME']=str(root/'state')
if a.isaac_python:os.environ['SIMSCENE_ISAAC_PYTHON']=a.isaac_python
sys.path.insert(0,str(root/'runtime'))
from simscene.scene import SceneStore
from simscene.usd_export import export_scene
for obj in scene['objects'].values():
 if obj.get('asset_path'):obj['asset_path']=str((root/obj['asset_path']).resolve())
 cfg=obj.get('pose_follower')
 if cfg:
  cfg['model_directory']=str((root/cfg['model_directory']).resolve())
  if cfg.get('gripper_urdf'):cfg['gripper_urdf']=str((root/cfg['gripper_urdf']).resolve())
  metadata=Path(cfg['model_directory'])/'profile.json'
  if metadata.is_file():
   profile=json.load(open(metadata));profile['asset_path']=obj['asset_path'];metadata.write_text(json.dumps(profile,indent=2))
store=SceneStore();scene_id='project_'+uuid.uuid4().hex[:12];store.open(scene_id)
ops=[{'op':'add','id':name,'object':obj} for name,obj in scene['objects'].items()]
if scene.get('presentation'):ops.append({'op':'set_presentation','presentation':scene['presentation']})
if scene.get('observation'):ops.append({'op':'set_observation','observation':scene['observation']})
store.apply(scene_id,0,'import-editable',ops);current=store.get(scene_id)
if a.check_only:
 stage=export_scene(current,root/'state'/(scene_id+'.usda'));print(json.dumps({'scene_id':scene_id,'schema_and_export':'passed','stage':stage['path'],'physics_validation':'not run'}));raise SystemExit(0)
case=None;case_path=None
if (root/a.case_file).is_file():
 case_path=root/a.case_file;original_case_bytes=case_path.read_bytes();case=json.loads(original_case_bytes)
 if 'source_scene_sha256' in case:
  current_sha=hashlib.sha256(json.dumps(current,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
  if case['source_scene_sha256']!=current_sha:
   case['source_scene_sha256']=current_sha
   rebound_path=root/'state'/(scene_id+'.case.json')
   with rebound_path.open('x') as f:json.dump(case,f,sort_keys=True,separators=(',',':'),allow_nan=False)
   print(json.dumps({'project_case_rebound':{'original_file':str(case_path),'original_sha256':hashlib.sha256(original_case_bytes).hexdigest(),'rebound_file':str(rebound_path),'rebound_sha256':hashlib.sha256(rebound_path.read_bytes()).hexdigest(),'reason':'legacy source_scene_sha256 follows the newly imported scene; original case retained'}}),flush=True)
   case_path=rebound_path
from simscene.jobs import start,status
archive=bool(case and 'expected_spawn_order' in case)
job=start(scene_id,a.steps or manifest['default_steps'],manifest['seed'],case_path=str(case_path) if case_path else None,archive_verified_objects=archive,request_id='project-'+uuid.uuid4().hex)
print(json.dumps(job),flush=True)
while True:
 state=status(job['job_id'])
 if state['state'] not in ('queued','running','paused','stalled'):break
 time.sleep(1)
print(json.dumps({k:v for k,v in state.items() if k!='result'}),flush=True)
if state['state']!='completed':raise SystemExit(1)
if case and ('objects' in case or 'expected_spawn_order' in case or case.get('schema') in ('simscene.mechanism.v1','simscene.mechanism.v2','simscene.passive_network.v1','simscene.passive_network.v2','simscene.passive_network.v3')):
 from simscene.verification.case_runner import evaluate
 report=evaluate(Path(state['result_file']).parent);print(json.dumps({'passed':report['passed']}));raise SystemExit(0 if report['passed'] else 1)
print(json.dumps({'task_verification':'unverified by stock case checker; inspect measured state and supplied validation separately'}))
'''

def export(run,destination):
    run=Path(run).resolve();destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    if not verify_input(run)['passed'] or not verify_output(run)['passed']:raise ValueError('source run integrity failed')
    scene=json.load(open(run/'spec.json'));asset_lock=json.load(open(run/'asset-lock.json'));manifest=json.load(open(run/'run-lock.json'))
    destination.mkdir(parents=True);external={}
    for entry in asset_lock.values():
        if entry['kind']=='external':
            for item in entry['files']:external[item['path']]=item
    common=Path(os.path.commonpath(list(external))) if external else None
    if common and common.is_file():common=common.parent
    for name in ('assets','models','runtime'):
        if (run/name).is_dir():shutil.copytree(run/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for filename,item in external.items():
        source=Path(filename)
        if source.stat().st_size!=item['size'] or hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('external source changed during export')
        target=destination/'external'/source.relative_to(common);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for name,obj in scene['objects'].items():
        if obj.get('asset_path'):
            path=Path(obj['asset_path'])
            if path.is_relative_to(run):obj['asset_path']=str(destination/path.relative_to(run))
            else:obj['asset_path']=str(destination/'external'/path.relative_to(common))
        cfg=obj.get('pose_follower')
        if cfg:
            cfg['model_directory']=str(destination/Path(cfg['model_directory']).relative_to(run))
            if cfg.get('gripper_urdf'):cfg['gripper_urdf']=str(destination/Path(cfg['gripper_urdf']).relative_to(run))
    export_scene(scene,destination/'scene.usda')
    for obj in scene['objects'].values():
        if obj.get('asset_path'):obj['asset_path']=str(Path(obj['asset_path']).relative_to(destination))
        cfg=obj.get('pose_follower')
        if cfg:
            cfg['model_directory']=str(Path(cfg['model_directory']).relative_to(destination))
            if cfg.get('gripper_urdf'):cfg['gripper_urdf']=str(Path(cfg['gripper_urdf']).relative_to(destination))
    (destination/'scene.json').write_text(json.dumps(scene,indent=2))
    if manifest.get('acceptance_case_file'):shutil.copyfile(run/manifest['acceptance_case_file'],destination/'case.json')
    (destination/'run_project.py').write_text(LAUNCHER)
    result={'source_run':str(run),'run_id':run.name,'source_run_lock_sha256':hashlib.sha256((run/'run-lock.json').read_bytes()).hexdigest(),
            'source_evidence_lock_sha256':hashlib.sha256((run/'evidence-lock.json').read_bytes()).hexdigest(),
            'default_steps':manifest['requested_physics_steps'],'seed':manifest['seed'],'isaac_version':manifest['runtime_version'],
            'runtime_provided_materials':{n:e.get('runtime_provided_dependencies',{}) for n,e in asset_lock.items() if e.get('runtime_provided_dependencies')},
            'scope':'editable local project with geometry and frozen worker; original recorded evidence remains separate; runtime-provided materials still require compatible Isaac'}
    (destination/'project.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('destination');a=p.parse_args();print(json.dumps(export(a.run,a.destination),indent=2))
