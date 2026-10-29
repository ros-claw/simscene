"""Generate the local experimental RS007L configuration from Isaac assets."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--isaac-root',required=True);p.add_argument('--assets-root');p.add_argument('--asset-usd');p.add_argument('--output',required=True)
a=p.parse_args()
if not a.asset_usd and not a.assets_root:p.error('provide --asset-usd or --assets-root')
root=Path(a.isaac_root).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
config=root/'extsDeprecated/isaacsim.robot_motion.motion_generation/motion_policy_configs/Kawasaki/rs007l'
source_urdf=config/'rs007l_onrobot_rg2.urdf'; descriptor=config/'rmpflow/rs007l_robot_description.yaml'; rmp=config/'rmpflow/rs007l_rmpflow_config.yaml'
usd=Path(a.asset_usd).resolve() if a.asset_usd else Path(a.assets_root).resolve()/'Isaac/Robots/Kawasaki/RS007L/rs007l_onrobot_rg2.usd'
for path in (source_urdf,descriptor,rmp,usd):
    if not path.is_file(): raise FileNotFoundError(path)
for name in ('robot.urdf','robot.xrdf','rmp_flow.yaml','profile.json'):
    if (out/name).exists(): raise FileExistsError(out/name)
scripts=Path(__file__).resolve().parent
def run(script,*args): subprocess.run([sys.executable,str(scripts/script),*map(str,args)],check=True)
run('align_fixed_frame.py','--usd',usd,'--urdf',source_urdf,'--output',out/'robot.urdf','--parent-prim','/khi_rs007l/onrobot_rg2_base_link','--child-prim','/khi_rs007l/gripper_center','--joint','gripper_center_joint')
run('convert_lula_to_xrdf.py','--descriptor',descriptor,'--urdf',out/'robot.urdf','--output',out/'robot.xrdf','--tool-frame','gripper_center')
run('convert_rmpflow.py','--source',rmp,'--output',out/'rmp_flow.yaml')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
profile={'status':'experimental','asset_path':str(usd),'tool_frame':'gripper_center','tcp_prim':'gripper_center',
         'source_sha256':{str(x):sha(x) for x in (usd,source_urdf,descriptor,rmp)},
         'generated_sha256':{x:sha(out/x) for x in ('robot.urdf','robot.xrdf','rmp_flow.yaml')},
         'limitations':['not a verified profile','self collision not configured','collision clearance not validated','gripper, TCP, and dynamics depend on exact source assets and runtime']}
(out/'profile.json').write_text(json.dumps(profile,indent=2));print(json.dumps(profile,indent=2))
