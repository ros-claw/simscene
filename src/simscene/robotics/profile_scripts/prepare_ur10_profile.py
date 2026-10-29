"""Prepare an experimental UR10 short-suction TCP model from local USD/URDF."""
import argparse,hashlib,json,shutil,xml.etree.ElementTree as ET
from pathlib import Path
from simscene.robotics.config_paths import cumotion_robot_config
import numpy as np
import yaml
from scipy.spatial.transform import Rotation
from pxr import Usd,UsdGeom,UsdPhysics
from simscene.robotics.urdf import link_transform
p=argparse.ArgumentParser();p.add_argument('--isaac-root',required=True);p.add_argument('--assets-root');p.add_argument('--asset-usd');p.add_argument('--output',required=True)
a=p.parse_args()
if not a.asset_usd and not a.assets_root:p.error('provide --asset-usd or --assets-root')
root=Path(a.isaac_root).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
config=cumotion_robot_config(root,'ur10');usd=Path(a.asset_usd).resolve() if a.asset_usd else Path(a.assets_root).resolve()/'Isaac/Robots/UniversalRobots/ur10/ur10.usd'
for f in ('robot.urdf','robot.xrdf','rmp_flow.yaml','profile.json'):
    if (out/f).exists(): raise FileExistsError(out/f)
stage=Usd.Stage.Open(str(usd));root_prim=stage.GetDefaultPrim();variant=root_prim.GetVariantSet('Gripper')
if 'Short_Suction' not in variant.GetVariantNames(): raise ValueError('short suction variant missing')
variant.SetVariantSelection('Short_Suction')
cache=UsdGeom.XformCache();base=stage.GetPrimAtPath('/ur10/base_link');ee=stage.GetPrimAtPath('/ur10/ee_link')
joint=UsdPhysics.Joint(stage.GetPrimAtPath('/ur10/ee_link/suction_cup/Suction_Joint'))
if not base or not ee or not joint:raise ValueError('required USD frames missing')
relative=cache.GetLocalToWorldTransform(ee)*cache.GetLocalToWorldTransform(base).GetInverse()
transform=np.eye(4);transform[:3,:3]=np.array([[relative[j][i] for j in range(3)] for i in range(3)]);transform[:3,3]=np.array(relative.ExtractTranslation())
position=joint.GetLocalPos0Attr().Get();rotation=joint.GetLocalRot0Attr().Get();imag=rotation.GetImaginary()
local=np.eye(4);local[:3,:3]=Rotation.from_quat([imag[0],imag[1],imag[2],rotation.GetReal()]).as_matrix();local[:3,3]=np.array(position)
model=np.array(link_transform(config/'robot.urdf','base_link','tool0'))
offset=np.linalg.inv(model)@transform@local
rpy=Rotation.from_matrix(offset[:3,:3]).as_euler('xyz')
tree=ET.parse(config/'robot.urdf');robot=tree.getroot()
ET.SubElement(robot,'link',{'name':'simscene_suction_tcp'});j=ET.SubElement(robot,'joint',{'name':'simscene_suction_tcp_fixed','type':'fixed'})
ET.SubElement(j,'parent',{'link':'tool0'});ET.SubElement(j,'child',{'link':'simscene_suction_tcp'});ET.SubElement(j,'origin',{'xyz':' '.join(f'{x:.12g}' for x in offset[:3,3]),'rpy':' '.join(f'{x:.12g}' for x in rpy)})
tree.write(out/'robot.urdf',encoding='utf8',xml_declaration=True)
xrdf=yaml.safe_load((config/'robot.xrdf').read_text());xrdf['tool_frames']=['simscene_suction_tcp']
(out/'robot.xrdf').write_text('# Derived from NVIDIA Corporation source: SPDX-License-Identifier: Apache-2.0\n# Experimental suction frame; not a verified profile.\n'+yaml.safe_dump(xrdf,sort_keys=False));shutil.copyfile(config/'rmp_flow.yaml',out/'rmp_flow.yaml')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
profile={'status':'experimental','asset_path':str(usd),'variants':{'Gripper':'Short_Suction'},'tool_frame':'simscene_suction_tcp','tcp_prim':'ee_link',
         'tcp_offset':list(position),'tcp_orientation_wxyz':[float(rotation.GetReal()),*[float(x) for x in imag]],
         'surface_gripper_prim':'ee_link/SurfaceGripper','source_sha256':{str(x):sha(x) for x in [usd,config/'robot.urdf',config/'robot.xrdf',config/'rmp_flow.yaml']},
         'generated_sha256':{f:sha(out/f) for f in ('robot.urdf','robot.xrdf','rmp_flow.yaml')},
         'limitations':['authored rest frame calculation only','runtime FK and suction behavior not yet verified','collision safety not validated']}
(out/'profile.json').write_text(json.dumps(profile,indent=2));print(json.dumps(profile,indent=2))
