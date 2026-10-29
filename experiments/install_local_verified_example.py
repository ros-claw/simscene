"""Install the already physically tested 18-item example as an editable scene.

This fetches only its three selected source assets into the configured bounded
cache and regenerates their controller profiles on the current host. It refuses
changed asset content or mismatched controller files. The original run remains
unchanged, and a new run still requires its own physical verification.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from simscene.assets import USDSearch
from simscene.cache import AssetCache
from simscene.robotics.profiles import prepare
from simscene.scene import SceneStore
from simscene.settings import get

root=Path(__file__).resolve().parent.parent
evidence=root/'evidence/isaac-6.2-online-feeder-concurrent'
source=evidence/'three_arm_showcase.json'
case=evidence/'showcase-case.json'
asset_manifest=json.loads((evidence/'asset-lock.json').read_text())
scene=json.loads(source.read_text());objects=copy.deepcopy(scene['objects'])
store=SceneStore();name='three_arm_online_example'
example_dir=store.path/'examples'/'three_arm_online_example'
if (store.path/(name+'.json')).exists() or example_dir.exists():
    raise SystemExit('example scene or directory already exists; refusing to overwrite it')
cache=AssetCache(USDSearch(timeout=300),get('cache_directory','~/.cache/simscene/assets'),int(get('cache_bytes',2*1024**3)))
models={'kawasaki':'kawasaki_rs007l_rg2','franka':'franka_panda','ur10':'ur10_short_suction'}
records={}
for robot,model in models.items():
    original_profile=evidence/'models'/robot
    digest=asset_manifest[robot]['package_sha256']
    lock_path=evidence/'assets'/digest/'simscene-lock.json'
    if not lock_path.is_file():raise ValueError('original asset content lock missing for '+robot)
    original=json.loads(lock_path.read_text());acquired=cache.acquire(original['source'])
    if acquired['dependency_status'] not in ('resolved','resolved_with_runtime'):
        raise ValueError('dependencies not resolved for '+robot)
    if cache.content_identity(original['files'])!=cache.content_identity(acquired['files']):
        raise ValueError('the online asset or dependency content changed for '+robot)
    profile=prepare(model,acquired['root']);new_profile=Path(profile['model_directory'])
    hashes={}
    for filename in ('robot.urdf','robot.xrdf','rmp_flow.yaml'):
        before=hashlib.sha256((original_profile/filename).read_bytes()).hexdigest()
        after=hashlib.sha256((new_profile/filename).read_bytes()).hexdigest()
        if before!=after:raise ValueError('regenerated controller differs for '+robot+': '+filename)
        hashes[filename]=after
    objects[robot]['asset_path']=acquired['root'];cfg=objects[robot]['pose_follower'];cfg['model_directory']=str(new_profile)
    if 'gripper_urdf' in cfg:cfg['gripper_urdf']=str(new_profile/'robot.urdf')
    records[robot]={'source':original['source'],'asset_path':acquired['root'],
                    'dependency_status':acquired['dependency_status'],'package_sha256':acquired['package_sha256'],
                    'controller_directory':str(new_profile),'controller_sha256':hashes,'same_source_content':True}
    print(json.dumps({'prepared':robot,'dependency_status':acquired['dependency_status']}),flush=True)
example_dir.mkdir(parents=True,exist_ok=False)
fresh=store.open(name)
if fresh['revision'] or fresh['objects']:raise SystemExit('example scene was created by someone else; refusing to overwrite it')
ops=[{'op':'add','id':key,'object':obj} for key,obj in objects.items()]
store.apply(name,0,'install-verified-example',ops)
(example_dir/'case.json').write_bytes(case.read_bytes())
(example_dir/'installation.json').write_text(json.dumps({'scene_id':name,'source_run':'evidence/isaac-6.2-online-feeder-concurrent',
    'same_selected_asset_contents_and_controller_files':True,'assets':records,
    'scope':'Editable copy on this host; the copied scene has not itself been rerun. Cache packages may be restored after eviction using source and content locks.'},indent=2)+'\n')
print(json.dumps({'scene_id':name,'scene_path':str(store.path/(name+'.json')),'case':str(example_dir/'case.json')}),flush=True)
