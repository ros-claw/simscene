"""Compare authored USD rest transforms to zero-position URDF FK.

This is an offline rest-pose check, not a dynamic simulation or a TCP validation.
"""
import argparse
import hashlib
import json
import math
from pxr import Usd, UsdGeom
from simscene.robotics.urdf import link_transform

p=argparse.ArgumentParser()
p.add_argument('--usd',required=True); p.add_argument('--urdf',required=True)
p.add_argument('--root',required=True); p.add_argument('--base',required=True)
p.add_argument('--links',nargs='+',required=True); p.add_argument('--output',required=True)
a=p.parse_args()
stage=Usd.Stage.Open(a.usd)
if not stage: raise RuntimeError('cannot open USD')
cache=UsdGeom.XformCache()
base=stage.GetPrimAtPath(a.root+'/'+a.base)
if not base: raise RuntimeError('base not found')
base_inverse=cache.GetLocalToWorldTransform(base).GetInverse()
comparisons=[]
for name in a.links:
    prim=stage.GetPrimAtPath(a.root+'/'+name)
    if not prim: raise RuntimeError('link not found: '+name)
    usd=cache.GetLocalToWorldTransform(prim) * base_inverse
    urdf=link_transform(a.urdf,a.base,name)
    trans=math.sqrt(sum((usd[3][j]-urdf[j][3])**2 for j in range(3)))
    rot=math.sqrt(sum((usd[j][i]-urdf[i][j])**2 for i in range(3) for j in range(3)))
    comparisons.append({'link':name,'translation_error_m':trans,'rotation_matrix_frobenius_error':rot})
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for data in iter(lambda:f.read(1048576),b''): h.update(data)
    return h.hexdigest()
result={'usd':a.usd,'usd_sha256':sha(a.usd),'urdf':a.urdf,'urdf_sha256':sha(a.urdf),
        'scope':'authored zero pose only; excludes simulation, TCP, limits and grasp', 'links':comparisons}
with open(a.output,'w') as f: json.dump(result,f,indent=2)
