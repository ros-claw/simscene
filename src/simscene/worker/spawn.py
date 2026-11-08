"""Instantiate scheduled primitive workpieces during an Isaac session."""
def spawn(stage, name, obj):
    from pxr import Gf,UsdGeom,UsdPhysics,PhysxSchema
    path='/World/'+name.replace('-', '_')
    if stage.GetPrimAtPath(path): raise ValueError('scheduled object already exists: '+name)
    size=obj.get('size',[1,1,1]);uniform=size[0]==size[1]==size[2]
    if obj['kind']=='box':
        entity=UsdGeom.Cube.Define(stage,path);entity.CreateSizeAttr(size[0] if uniform else 1.)
    elif obj['kind']=='sphere':
        entity=UsdGeom.Sphere.Define(stage,path);entity.CreateRadiusAttr(size[0]/2 if uniform else .5)
    else: raise ValueError('unsupported scheduled geometry')
    xform=UsdGeom.Xformable(entity.GetPrim())
    xform.AddTranslateOp().Set(Gf.Vec3d(*obj.get('position',[0,0,0])))
    q=obj.get('orientation_wxyz',[1,0,0,0]);xform.AddOrientOp().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
    if not uniform:xform.AddScaleOp().Set(Gf.Vec3f(*size))
    if 'color' in obj:entity.CreateDisplayColorAttr([Gf.Vec3f(*obj['color'])])
    if obj.get('visible',True) is False:UsdGeom.Imageable(entity.GetPrim()).MakeInvisible()
    if 'material' in obj:
        from simscene.materials import apply_material
        apply_material(stage,entity.GetPrim(),name,obj['material'])
    if obj.get('collision',True):UsdPhysics.CollisionAPI.Apply(entity.GetPrim())
    UsdPhysics.RigidBodyAPI.Apply(entity.GetPrim())
    if 'mass_kg' in obj:UsdPhysics.MassAPI.Apply(entity.GetPrim()).CreateMassAttr(obj['mass_kg'])
    if 'physics' in obj:
        from simscene.passive import author_physics
        author_physics(stage,entity.GetPrim(),name,obj)
    PhysxSchema.PhysxContactReportAPI.Apply(entity.GetPrim()).CreateThresholdAttr().Set(0)
    return path
