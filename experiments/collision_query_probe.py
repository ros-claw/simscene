"""Inspect PhysX scene-query coverage; not a complete collision audit."""
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('scene');p.add_argument('output');a=p.parse_args()
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'multi_gpu':False,'active_gpu':0})
try:
    import omni.usd,omni.physx
    from pxr import Usd,UsdPhysics,PhysxSchema,PhysicsSchemaTools,Gf,Sdf
    from isaacsim.core.simulation_manager import SimulationManager
    import isaacsim.core.experimental.utils.app as app_utils
    if not omni.usd.get_context().open_stage(a.scene):raise RuntimeError('stage open failed')
    stage=omni.usd.get_context().get_stage()
    if not stage.GetPrimAtPath('/World/PhysicsScene'):
        scene=UsdPhysics.Scene.Define(stage,'/World/PhysicsScene');scene.CreateGravityDirectionAttr(Gf.Vec3f(0,0,-1));scene.CreateGravityMagnitudeAttr(9.81)
        api=PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim());api.CreateEnableGPUDynamicsAttr().Set(False);api.CreateBroadphaseTypeAttr().Set('MBP')
    shapes=[]
    for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
        if not any(str(prim.GetPath()).startswith(f'/World/{name}/Asset/') for name in ('arm','kawasaki','franka','ur10')) or not prim.HasAPI(UsdPhysics.CollisionAPI):continue
        parent=prim
        while parent and not parent.HasAPI(UsdPhysics.RigidBodyAPI):parent=parent.GetParent()
        shapes.append({'path':str(prim.GetPath()),'body':str(parent.GetPath()) if parent else None,'type':prim.GetTypeName()})
    SimulationManager.set_physics_dt(1/60);app_utils.play();app.update()
    for _ in range(10):app.update()
    query=omni.physx.get_physx_scene_query_interface();records=[]
    for shape in shapes:
        hits=[]
        def report(hit):
            hits.append({'rigid_body':str(hit.rigid_body),'collision':str(getattr(hit,'collision',''))})
            return True
        code=PhysicsSchemaTools.encodeSdfPath(Sdf.Path(shape['path']))
        try:
            count=query.overlap_shape(code[0],code[1],report,False)
            records.append(dict(shape,hit_count=count,hits=hits,own_body_seen=any(h['rigid_body']==shape['body'] for h in hits)))
        except Exception as error:records.append(dict(shape,error=str(error)))
    Path(a.output).write_text(json.dumps({'scope':'one-time scene query exploration, not continuous or complete collision proof','shapes':records},indent=2)+'\n')
    app_utils.stop()
finally:app.close()
