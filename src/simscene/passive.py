"""Metric passive rigid mechanisms: baked shapes, compound bodies and joints.

Joint frames are local metres/quaternions; body poses define the initial state.
No drive, target, timed release or force callback is authored by this module.
"""
import math

GEOMETRY = ('box', 'sphere', 'cylinder', 'capsule', 'compound')
JOINT_TYPES = ('fixed', 'revolute', 'prismatic', 'spherical', 'd6')

def finite(value):
    return type(value) in (float, int) and math.isfinite(value)

def vector(value, count=3):
    return isinstance(value, list) and len(value)==count and all(finite(v) for v in value)

def quaternion(value):
    return vector(value,4) and abs(sum(v*v for v in value)-1)<1e-4

def validate_parts(obj):
    parts=obj.get('parts')
    if obj.get('kind')!='compound' or not isinstance(parts,list) or not 1<=len(parts)<=128:
        return ['parts requires a compound body with 1..128 primitive parts']
    errors=[]
    for part in parts:
        if not isinstance(part,dict) or set(part)-{'kind','size','position','orientation_wxyz','color','collision','material','visible'}:
            errors.append('unsupported compound part fields');continue
        if part.get('kind') not in GEOMETRY[:-1]:errors.append('compound parts must be primitive geometry')
        size=part.get('size',[1,1,1])
        if not vector(size) or min(size)<=0:errors.append('part size must be positive finite dimensions')
        elif part.get('kind') in ('cylinder','capsule') and (abs(size[0]-size[1])>1e-8 or (part['kind']=='capsule' and size[2]<size[0])):
            errors.append('axial parts require equal X/Y diameter and capsule total length >= diameter')
        if not vector(part.get('position',[0,0,0])) or not quaternion(part.get('orientation_wxyz',[1,0,0,0])):errors.append('part needs metric position and normalized quaternion')
        if 'collision' in part and type(part['collision']) is not bool:errors.append('part collision must be boolean')
        if 'visible' in part and type(part['visible']) is not bool:errors.append('part visible must be boolean')
        if not vector(part.get('color',[1,1,1])) or any(not 0<=v<=1 for v in part.get('color',[1,1,1])):errors.append('invalid part color')
        if 'material' in part:
            from .scene import validate
            errors.extend(x['message'] for x in validate({'objects':{'part':{'kind':'box','material':part['material']}}}))
    if obj.get('dynamic') and obj.get('collision',True) and not any(p.get('collision',True) for p in parts if isinstance(p,dict)):
        errors.append('dynamic compound requires at least one colliding part')
    return errors

def validate_physics(obj):
    cfg=obj.get('physics')
    fields={'static_friction','dynamic_friction','restitution','linear_damping','angular_damping','sleep_threshold','contact_offset_m','rest_offset_m','solver_position_iterations','solver_velocity_iterations','enable_ccd'}
    if obj.get('kind') not in GEOMETRY or not isinstance(cfg,dict) or set(cfg)-fields:
        return ['physics requires primitive/compound geometry and supported passive settings']
    errors=[]
    if not obj.get('dynamic') and any(k in cfg for k in ('linear_damping','angular_damping','sleep_threshold','solver_position_iterations','solver_velocity_iterations','enable_ccd')):
        errors.append('body damping, sleep, solver and CCD settings require a dynamic body')
    for key,value in cfg.items():
        if key=='enable_ccd':ok=type(value) is bool
        elif key.startswith('solver_'):ok=type(value) is int and 1<=value<=255
        else:ok=finite(value) and (0<=value<=1 if key=='restitution' else 0<=value<=1000)
        if not ok:errors.append('invalid passive physics '+key)
    if cfg.get('contact_offset_m',.02)<=cfg.get('rest_offset_m',0):errors.append('contact offset must exceed rest offset')
    return errors

def validate_joint(scene,obj):
    cfg=obj.get('joint');errors=[]
    allowed={'type','body0','body1','local_pos0','local_pos1','local_rot0_wxyz','local_rot1_wxyz','axis','lower_limit','upper_limit','enabled','collision_enabled','dof_limits'}
    if obj.get('kind')!='joint' or not isinstance(cfg,dict) or set(cfg)-allowed or cfg.get('type') not in JOINT_TYPES:
        return ['joint requires a supported passive type; drives/targets are not supported']
    for key in ('body0','body1'):
        name=cfg.get(key)
        if name is None and key=='body0':continue
        body=scene['objects'].get(name,{}) if isinstance(name,str) else {}
        if not isinstance(body,dict):body={}
        if body.get('kind') not in GEOMETRY or not body.get('dynamic') or body.get('spawn_step',0):errors.append(key+' must reference an initially present dynamic body (body0 may be null/world)')
        if body.get('kind') in ('box','sphere'):
            size=body.get('size',[1,1,1])
            if vector(size) and not size[0]==size[1]==size[2]:errors.append('scaled legacy body needs a baked compound body for metric joint frames')
    if cfg.get('body0')==cfg.get('body1'):errors.append('joint endpoints must differ')
    for i in (0,1):
        if not vector(cfg.get('local_pos'+str(i),[0,0,0])) or not quaternion(cfg.get('local_rot'+str(i)+'_wxyz',[1,0,0,0])):errors.append('joint frames require finite positions and normalized quaternions')
    for key in ('enabled','collision_enabled'):
        if key in cfg and type(cfg[key]) is not bool:errors.append(key+' must be boolean')
    moving=cfg['type'] in ('revolute','prismatic')
    if moving:
        if cfg.get('axis','X') not in ('X','Y','Z'):errors.append('joint axis must be X, Y or Z')
        if ('lower_limit' in cfg)!=('upper_limit' in cfg):errors.append('joint limits must be paired')
        if 'lower_limit' in cfg and (not finite(cfg['lower_limit']) or not finite(cfg['upper_limit']) or cfg['lower_limit']>cfg['upper_limit']):errors.append('joint limits must be ordered finite values (degrees or metres)')
    elif any(k in cfg for k in ('axis','lower_limit','upper_limit')):errors.append('axis/limits require revolute or prismatic joint')
    if cfg['type']=='d6':
        from .d6 import validate_limits
        errors.extend(validate_limits(cfg.get('dof_limits')))
    elif 'dof_limits' in cfg:errors.append('dof_limits requires a d6 joint')
    return errors

def shape(stage,path,obj):
    """Baked primitive dimensions below an unscaled rigid frame."""
    from pxr import UsdGeom,Gf
    kind=obj['kind'];size=obj.get('size',[1,1,1])
    if kind=='box':
        entity=UsdGeom.Cube.Define(stage,path);entity.CreateSizeAttr(1.)
        UsdGeom.Xformable(entity).AddScaleOp().Set(Gf.Vec3f(*size))
    elif kind=='sphere':
        entity=UsdGeom.Sphere.Define(stage,path);entity.CreateRadiusAttr(.5)
        UsdGeom.Xformable(entity).AddScaleOp().Set(Gf.Vec3f(*size))
    else:
        schema=UsdGeom.Cylinder if kind=='cylinder' else UsdGeom.Capsule
        entity=schema.Define(stage,path);entity.CreateRadiusAttr(size[0]/2);entity.CreateHeightAttr(size[2] if kind=='cylinder' else size[2]-size[0]);entity.CreateAxisAttr('Z')
    if 'color' in obj:entity.CreateDisplayColorAttr([Gf.Vec3f(*obj['color'])])
    return entity

def compound(stage,path,obj):
    from pxr import UsdGeom,UsdPhysics,Gf
    root=UsdGeom.Xform.Define(stage,path)
    for i,part in enumerate(obj['parts']):
        child=UsdGeom.Xform.Define(stage,path+'/part_'+str(i));xf=UsdGeom.Xformable(child)
        xf.AddTranslateOp().Set(Gf.Vec3d(*part.get('position',[0,0,0])))
        q=part.get('orientation_wxyz',[1,0,0,0]);xf.AddOrientOp().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
        geometry=shape(stage,str(child.GetPath())+'/Shape',{'color':obj.get('color',[1,1,1]),**part})
        if not part.get('visible',True):UsdGeom.Imageable(geometry.GetPrim()).MakeInvisible()
        if obj.get('collision',obj.get('dynamic',False)) and part.get('collision',True):UsdPhysics.CollisionAPI.Apply(geometry.GetPrim())
        if 'material' in part:
            from .materials import apply_material
            apply_material(stage,geometry.GetPrim(),path.rsplit('/',1)[-1]+'_part_'+str(i),part['material'])
    return root

def author_joint(stage,path,cfg):
    from pxr import UsdPhysics,Gf
    schemas={'fixed':UsdPhysics.FixedJoint,'revolute':UsdPhysics.RevoluteJoint,'prismatic':UsdPhysics.PrismaticJoint,'spherical':UsdPhysics.SphericalJoint,'d6':UsdPhysics.Joint}
    joint=schemas[cfg['type']].Define(stage,path)
    for i in (0,1):
        name=cfg.get('body'+str(i))
        if name:getattr(joint,'CreateBody'+str(i)+'Rel')().SetTargets(['/World/'+name.replace('-','_')])
        getattr(joint,'CreateLocalPos'+str(i)+'Attr')().Set(Gf.Vec3f(*cfg.get('local_pos'+str(i),[0,0,0])))
        q=cfg.get('local_rot'+str(i)+'_wxyz',[1,0,0,0]);getattr(joint,'CreateLocalRot'+str(i)+'Attr')().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
    joint.CreateJointEnabledAttr().Set(cfg.get('enabled',True));joint.CreateCollisionEnabledAttr().Set(cfg.get('collision_enabled',False))
    joint.CreateExcludeFromArticulationAttr().Set(True)
    if cfg['type'] in ('revolute','prismatic'):
        joint.CreateAxisAttr().Set(cfg.get('axis','X'))
        if 'lower_limit' in cfg:joint.CreateLowerLimitAttr().Set(cfg['lower_limit']);joint.CreateUpperLimitAttr().Set(cfg['upper_limit'])
    elif cfg['type']=='d6':
        from .d6 import author_limits
        author_limits(joint,cfg['dof_limits'])
    return joint

def author_physics(stage,prim,name,obj):
    """Standard USD contact material plus explicitly named PhysX extension attrs.

    The latter remain in USD even when exported with standalone usd-core; the
    Isaac schema plugin resolves them on opening the stage.
    """
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade,Sdf
    cfg=obj.get('physics',{})
    if not cfg:return
    contact={k:cfg[k] for k in ('static_friction','dynamic_friction','restitution') if k in cfg}
    if contact:
        mat=UsdShade.Material.Define(stage,'/World/Looks/'+name.replace('-','_')+'_physics');api=UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
        for key,value in contact.items():getattr(api,{'static_friction':'CreateStaticFrictionAttr','dynamic_friction':'CreateDynamicFrictionAttr','restitution':'CreateRestitutionAttr'}[key])().Set(float(value))
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat,materialPurpose='physics')
    body_fields={'linear_damping':('linearDamping',Sdf.ValueTypeNames.Float),'angular_damping':('angularDamping',Sdf.ValueTypeNames.Float),'sleep_threshold':('sleepThreshold',Sdf.ValueTypeNames.Float),'solver_position_iterations':('solverPositionIterationCount',Sdf.ValueTypeNames.Int),'solver_velocity_iterations':('solverVelocityIterationCount',Sdf.ValueTypeNames.Int),'enable_ccd':('enableCCD',Sdf.ValueTypeNames.Bool)}
    for key,(attribute,dtype) in body_fields.items():
        if key in cfg:
            prim.AddAppliedSchema('PhysxRigidBodyAPI');prim.CreateAttribute('physxRigidBody:'+attribute,dtype,custom=False).Set(cfg[key])
    for child in Usd.PrimRange(prim):
        if not child.HasAPI(UsdPhysics.CollisionAPI):continue
        for key,attribute in (('contact_offset_m','contactOffset'),('rest_offset_m','restOffset')):
            if key in cfg:child.AddAppliedSchema('PhysxCollisionAPI');child.CreateAttribute('physxCollision:'+attribute,Sdf.ValueTypeNames.Float,custom=False).Set(float(cfg[key]))
