"""Create an experimental USD override for Franka's gripper; retain source."""
import argparse
from pathlib import Path
from pxr import Gf,Usd,UsdGeom,UsdPhysics,UsdShade

p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output')
p.add_argument('--max-force',type=float,default=20.0);p.add_argument('--friction',type=float,default=1.0)
a=p.parse_args();source=Path(a.source).expanduser().resolve();output=Path(a.output).expanduser().resolve()
if not source.is_file() or output.exists() or output==source:raise ValueError('source must exist and output must be new')
if not 0<a.max_force<=100 or not 0<=a.friction<=2:raise ValueError('force or friction outside experiment bounds')
base=Usd.Stage.Open(str(source))
if not base or not base.GetDefaultPrim():raise ValueError('source has no default prim')
output.parent.mkdir(parents=True,exist_ok=True);stage=Usd.Stage.CreateNew(str(output))
UsdGeom.SetStageMetersPerUnit(stage,UsdGeom.GetStageMetersPerUnit(base));UsdGeom.SetStageUpAxis(stage,UsdGeom.GetStageUpAxis(base))
root=UsdGeom.Xform.Define(stage,'/panda').GetPrim();root.GetReferences().AddReference(str(source));stage.SetDefaultPrim(root)
joint=stage.GetPrimAtPath('/panda/panda_hand/panda_finger_joint1')
if not joint or not joint.IsA(UsdPhysics.PrismaticJoint):raise ValueError('expected Franka finger joint is missing')
UsdPhysics.DriveAPI.Apply(joint,'linear').CreateMaxForceAttr().Set(a.max_force)
material=UsdShade.Material.Define(stage,'/panda/SimSceneGripMaterial');physics=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
physics.CreateStaticFrictionAttr().Set(a.friction);physics.CreateDynamicFrictionAttr().Set(a.friction)
for name in ('panda_leftfinger','panda_rightfinger'):
    prim=stage.GetPrimAtPath('/panda/'+name)
    if not prim or not prim.HasAPI(UsdPhysics.RigidBodyAPI):raise ValueError('expected Franka finger body is missing')
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,bindingStrength=UsdShade.Tokens.strongerThanDescendants,materialPurpose='physics')
stage.GetRootLayer().Save()
print(str(output))
