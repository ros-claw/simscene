"""Local USD inspection; source properties are observations, not certifications."""
from pathlib import Path
from .assets import SearchError

def inspect_local(path):
    try:
        from pxr import Usd, UsdGeom, UsdPhysics, UsdUtils
    except ImportError as error:
        raise SearchError('USD Python bindings required for local inspection') from error
    path=Path(path).expanduser().resolve()
    if not path.is_file(): raise SearchError('asset file not found')
    stage=Usd.Stage.Open(str(path))
    if not stage: raise SearchError('could not open USD stage')
    root=stage.GetDefaultPrim()
    _, assets, unresolved=UsdUtils.ComputeAllDependencies(str(path))
    from .mdl_dependencies import missing as missing_mdl
    try:unresolved=list(unresolved)+missing_mdl(assets)
    except ValueError as error:unresolved=list(unresolved)+['MDL scan error: '+str(error)]
    from .runtime_dependencies import classify
    dependencies=classify(unresolved)
    prims=list(stage.Traverse())
    joints=[]
    for prim in prims:
        if prim.IsA(UsdPhysics.Joint):
            joint=UsdPhysics.Joint(prim)
            entry={'path':str(prim.GetPath()),'type':prim.GetTypeName(),
                   'body0':[str(p) for p in joint.GetBody0Rel().GetTargets()],
                   'body1':[str(p) for p in joint.GetBody1Rel().GetTargets()],
                   'enabled':joint.GetJointEnabledAttr().Get(),
                   'drives':[s for s in prim.GetAppliedSchemas() if 'DriveAPI' in s]}
            for key in ('physics:axis','physics:lowerLimit','physics:upperLimit'):
                attr=prim.GetAttribute(key)
                if attr and attr.Get() is not None:entry[key]=attr.Get()
            entry['local_pos0_units']=list(joint.GetLocalPos0Attr().Get())
            entry['local_pos1_units']=list(joint.GetLocalPos1Attr().Get())
            for index in (0,1):
                q=getattr(joint,'GetLocalRot'+str(index)+'Attr')().Get()
                entry['local_rot'+str(index)+'_wxyz']=[q.GetReal(),*q.GetImaginary()]
            joints.append(entry)
    bbox=None
    if root:
        try:
            box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render]).ComputeWorldBound(root).ComputeAlignedRange()
            if not box.IsEmpty():
                bbox={'min':list(box.GetMin()),'max':list(box.GetMax()),'dimensions_units':list(box.GetSize())}
                if stage.HasAuthoredMetadata('metersPerUnit'):
                    bbox['dimensions_m_in_source_axes']=[x*UsdGeom.GetStageMetersPerUnit(stage) for x in box.GetSize()]
        except Exception as error:
            bbox={'error':str(error)}
    return {'path':str(path), 'default_prim':str(root.GetPath()) if root else None,
            'meters_per_unit':UsdGeom.GetStageMetersPerUnit(stage), 'meters_per_unit_authored':stage.HasAuthoredMetadata('metersPerUnit'),
            'up_axis':UsdGeom.GetStageUpAxis(stage), 'up_axis_authored':stage.HasAuthoredMetadata('upAxis'),
            'bounds':bbox, 'joint_count':len(joints), 'joints':joints,
            'collision_prims':[str(p.GetPath()) for p in prims if p.HasAPI(UsdPhysics.CollisionAPI)],
            'rigid_bodies':[str(p.GetPath()) for p in prims if p.HasAPI(UsdPhysics.RigidBodyAPI)],
            'articulation_roots':[str(p.GetPath()) for p in prims if p.HasAPI(UsdPhysics.ArticulationRootAPI)],
            'unresolved_dependencies':dependencies['unresolved'], 'runtime_provided_dependencies':dependencies['runtime_provided'], 'behavior_validation':'not verified'}
