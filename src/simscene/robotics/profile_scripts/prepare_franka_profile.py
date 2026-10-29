"""Prepare an experimental centred Franka TCP model from local Isaac files."""
import argparse,hashlib,json,shutil,xml.etree.ElementTree as ET
from pathlib import Path
from simscene.robotics.config_paths import cumotion_robot_config
import yaml
from pxr import Usd
p=argparse.ArgumentParser();p.add_argument('--isaac-root',required=True);p.add_argument('--assets-root');p.add_argument('--asset-usd');p.add_argument('--output',required=True)
a=p.parse_args()
if not a.asset_usd and not a.assets_root:p.error('provide --asset-usd or --assets-root')
root=Path(a.isaac_root).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
config=cumotion_robot_config(root,'franka'); usd=Path(a.asset_usd).resolve() if a.asset_usd else Path(a.assets_root).resolve()/'Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd'
for f in ('robot.urdf','robot.xrdf','rmp_flow.yaml','profile.json'):
    if (out/f).exists(): raise FileExistsError(out/f)
for f in ('robot.urdf','robot.xrdf','rmp_flow.yaml'):
    if not (config/f).is_file(): raise FileNotFoundError(config/f)
if not usd.is_file():raise FileNotFoundError(usd)
stage=Usd.Stage.Open(str(usd))
if not stage or not stage.GetDefaultPrim():raise ValueError('cannot open robot USD with a default prim')
names={prim.GetName() for prim in stage.Traverse()}
if not {'panda_link0','panda_hand'}.issubset(names):raise ValueError('asset is not compatible with the expected Franka Panda frames')
tree=ET.parse(config/'robot.urdf');robot=tree.getroot()
if any(link.get('name')=='simscene_tcp' for link in robot.findall('link')):raise ValueError('TCP link already exists')
ET.SubElement(robot,'link',{'name':'simscene_tcp'})
joint=ET.SubElement(robot,'joint',{'name':'simscene_tcp_fixed','type':'fixed'})
ET.SubElement(joint,'parent',{'link':'panda_hand'});ET.SubElement(joint,'child',{'link':'simscene_tcp'});ET.SubElement(joint,'origin',{'xyz':'0 0 0.1034','rpy':'0 0 0'})
tree.write(out/'robot.urdf',encoding='utf8',xml_declaration=True)
xrdf=yaml.safe_load((config/'robot.xrdf').read_text());xrdf['tool_frames']=['simscene_tcp']
(out/'robot.xrdf').write_text('# Derived from NVIDIA Corporation source: SPDX-License-Identifier: Apache-2.0\n# Experimental centred tool frame; not a verified profile.\n'+yaml.safe_dump(xrdf,sort_keys=False))
shutil.copyfile(config/'rmp_flow.yaml',out/'rmp_flow.yaml')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
profile={'status':'experimental','asset_path':str(usd),'tool_frame':'simscene_tcp','tcp_prim':'panda_hand','tcp_offset':[0,0,.1034],
         'generated_sha256':{f:sha(out/f) for f in ('robot.urdf','robot.xrdf','rmp_flow.yaml')},'source_sha256':{str(x):sha(x) for x in [usd,config/'robot.urdf',config/'robot.xrdf',config/'rmp_flow.yaml']},
         'limitations':['not a verified profile','centred TCP position and orientation require simulator comparison','gripper and collision behavior unverified']}
(out/'profile.json').write_text(json.dumps(profile,indent=2));print(json.dumps(profile,indent=2))
