"""Create a URDF copy with a fixed joint origin matching the authored USD frame.

This is a calibration candidate; dynamic and application TCP validation remain
necessary. Source files are never modified.
"""
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from pxr import Usd,UsdGeom
p=argparse.ArgumentParser()
p.add_argument('--usd',required=True);p.add_argument('--urdf',required=True);p.add_argument('--output',required=True)
p.add_argument('--parent-prim',required=True);p.add_argument('--child-prim',required=True);p.add_argument('--joint',required=True)
a=p.parse_args()
stage=Usd.Stage.Open(a.usd)
parent,child=stage.GetPrimAtPath(a.parent_prim),stage.GetPrimAtPath(a.child_prim)
if not parent or not child: raise ValueError('USD parent or child missing')
cache=UsdGeom.XformCache(); relative=cache.GetLocalToWorldTransform(child)*cache.GetLocalToWorldTransform(parent).GetInverse()
if any(abs(relative[i][j] - (1 if i==j else 0))>1e-5 for i in range(3) for j in range(3)):
    raise ValueError('nonidentity frame rotation requires explicit calibration')
source=Path(a.urdf).resolve(); output=Path(a.output).resolve()
if source==output: raise ValueError('output must not overwrite source')
tree=ET.parse(source); joint=next((j for j in tree.getroot().findall('joint') if j.get('name')==a.joint),None)
if joint is None or joint.get('type')!='fixed': raise ValueError('fixed joint not found')
if joint.find('parent').get('link') != parent.GetName() or joint.find('child').get('link') != child.GetName():
    raise ValueError('joint links do not match the USD frames')
origin=joint.find('origin')
if origin is None: origin=ET.SubElement(joint,'origin')
origin.set('xyz', ' '.join(f'{relative[3][i]:.9g}' for i in range(3)))
origin.set('rpy','0 0 0')
tree.write(output,encoding='utf-8',xml_declaration=True)
