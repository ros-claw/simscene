"""Export supported primitives as a USD stage, without claiming physics validation."""
from pathlib import Path
import math
from .scene import validate, SceneError

def export_scene(scene, destination):
    issues = validate(scene)
    if issues: raise SceneError(str(issues))
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics
    except ImportError as e:
        raise SceneError('USD Python bindings required for export') from e
    names = [name.replace('-', '_') for name in scene['objects']]
    if len(set(names)) != len(names):
        raise SceneError('object IDs collide after USD path conversion')
    normalizations={}
    for name, obj in scene['objects'].items():
        if obj['kind'] == 'asset':
            asset_path = Path(obj['asset_path']).expanduser().resolve()
            if not asset_path.is_file():
                from .cache_restore import restore_reference
                from .assets import SearchError
                try:asset_path=restore_reference(asset_path)
                except SearchError as error:raise SceneError(f'cannot restore cached asset {name}: {error}') from error
                obj['asset_path']=str(asset_path)
            if not asset_path.is_file():
                raise SceneError(f'asset path does not exist: {name}')
            from pxr import UsdUtils
            asset_stage = Usd.Stage.Open(str(asset_path))
            if not asset_stage:
                raise SceneError(f'cannot open USD asset: {name}')
            if not asset_stage.HasAuthoredMetadata('metersPerUnit') or not asset_stage.HasAuthoredMetadata('upAxis'):
                raise SceneError(f'asset {name} has unspecified unit or up axis')
            meters=UsdGeom.GetStageMetersPerUnit(asset_stage);axis=UsdGeom.GetStageUpAxis(asset_stage)
            if not math.isfinite(meters) or not 1e-9<=meters<=1e9 or axis not in (UsdGeom.Tokens.y,UsdGeom.Tokens.z):
                raise SceneError(f'asset {name} has invalid units or up axis')
            if abs(meters-1.0)>1e-9 or axis!=UsdGeom.Tokens.z:
                # Uniform unit/up-axis conversion is safe here only for purely
                # visual assets. Physics schemas and variant sets need their
                # own calibrated import rather than transformed assumptions.
                prims=list(asset_stage.TraverseAll())
                has_physics=any(prim.HasAPI(UsdPhysics.RigidBodyAPI) or prim.HasAPI(UsdPhysics.CollisionAPI) or prim.HasAPI(UsdPhysics.ArticulationRootAPI) or prim.IsA(UsdPhysics.Joint) for prim in prims)
                has_variants=bool(obj.get('variants')) or any(prim.GetVariantSets().GetNames() for prim in prims)
                if has_physics or has_variants or obj.get('pose_follower'):
                    raise SceneError(f'asset {name} needs unit/up-axis conversion but has physics, variants, or a controller; import and validate it separately')
                normalizations[name]=(meters,axis)
            _, _, unresolved = UsdUtils.ComputeAllDependencies(str(asset_path))
            from .runtime_dependencies import classify
            dependencies = classify(unresolved)
            if dependencies['unresolved']:
                raise SceneError(f"asset {name} has unresolved dependencies: {dependencies['unresolved']}")
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SceneError('destination already exists')
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    # Give every stage the full supported job duration, not only scenes with
    # animated cameras. Isaac 6.2 warns when a timeline has no duration;
    # actual sensor readiness is checked separately by the running worker.
    stage.SetTimeCodesPerSecond(60);stage.SetFramesPerSecond(60)
    stage.SetStartTimeCode(0);stage.SetEndTimeCode(72600)
    root = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(root.GetPrim())
    for name, obj in scene['objects'].items():
        if obj.get('spawn_step',0)>0: continue
        prim_path = '/World/' + name.replace('-', '_')
        kind = obj['kind']
        if kind == 'box' and 'conveyor' in obj:
            # Bake size into points: scaled surface-velocity prims scale the
            # PhysX velocity as well, so a 3 m belt could move at 3x speed.
            entity = UsdGeom.Mesh.Define(stage, prim_path)
            hx, hy, hz = [v / 2 for v in obj.get('size', [1,1,1])]
            entity.CreatePointsAttr([Gf.Vec3f(x*hx, y*hy, z*hz) for x,y,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]])
            entity.CreateFaceVertexCountsAttr([4] * 6)
            entity.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7])
            entity.CreateSubdivisionSchemeAttr('none')
            entity.CreateExtentAttr([Gf.Vec3f(-hx,-hy,-hz), Gf.Vec3f(hx,hy,hz)])
        elif kind == 'box':
            entity = UsdGeom.Cube.Define(stage, prim_path)
            size=obj.get('size',[1,1,1])
            entity.CreateSizeAttr(size[0] if size[0]==size[1]==size[2] else 1.0)
        elif kind == 'sphere':
            entity = UsdGeom.Sphere.Define(stage, prim_path)
            size=obj.get('size',[1,1,1])
            entity.CreateRadiusAttr(size[0]/2 if size[0]==size[1]==size[2] else 0.5)
        elif kind == 'camera': entity = UsdGeom.Camera.Define(stage, prim_path)
        elif kind == 'counter':
            from .display import create
            config=obj['counter'];entity=create(stage,prim_path,config.get('digits',3),config.get('color',[.05,1,.1]))
            if config['source']=='verified_archives':UsdGeom.Imageable(entity.GetPrim()).MakeInvisible()
        elif kind == 'light':
            cfg=obj.get('light',{}); light_types={'distant':UsdLux.DistantLight,'dome':UsdLux.DomeLight,'sphere':UsdLux.SphereLight,'rect':UsdLux.RectLight}
            style=cfg.get('type','distant');entity=light_types[style].Define(stage,prim_path)
            entity.CreateIntensityAttr(float(obj.get('intensity', 1000)))
            if 'color' in cfg:entity.CreateColorAttr(Gf.Vec3f(*cfg['color']))
            if 'exposure' in cfg:entity.CreateExposureAttr(float(cfg['exposure']))
            if style=='sphere' and 'radius_m' in cfg:entity.CreateRadiusAttr(float(cfg['radius_m']))
            if style=='rect':
                if 'width_m' in cfg:entity.CreateWidthAttr(float(cfg['width_m']))
                if 'height_m' in cfg:entity.CreateHeightAttr(float(cfg['height_m']))
        elif kind == 'asset':
            entity = UsdGeom.Xform.Define(stage, prim_path)
            referenced = stage.OverridePrim(prim_path + '/Asset')
            asset = Path(obj['asset_path']).expanduser().resolve()
            try:
                # Assets snapshotted into the run remain relocatable with it.
                reference = './' + asset.relative_to(path.parent).as_posix()
            except ValueError:
                reference = str(asset)
            referenced.GetReferences().AddReference(reference)
            for set_name,choice in obj.get('variants',{}).items():
                variant=referenced.GetVariantSet(set_name)
                if choice not in variant.GetVariantNames():
                    raise SceneError(f'unknown variant {set_name}={choice} on {name}')
                variant.SetVariantSelection(choice)
            grip=obj.get('pose_follower',{}).get('gripper_physics')
            if grip is not None:
                from .gripper_physics import apply as apply_gripper_physics
                try:
                    apply_gripper_physics(stage,prim_path,grip)
                except ValueError as error:
                    # A bad model must not leave a misleading partial export.
                    stage.GetRootLayer().Clear()
                    path.unlink(missing_ok=True)
                    raise SceneError(f'asset {name}: {error}') from error
        xform = UsdGeom.Xformable(entity.GetPrim())
        if 'material' in obj:
            from .materials import apply_material
            apply_material(stage,entity.GetPrim(),name,obj['material'])
        elif 'indicator' in obj:
            from .materials import apply_material
            apply_material(stage,entity.GetPrim(),name,{'color':[.2,.2,.2],'emissive':[.2,.2,.2]})
        translate=xform.AddTranslateOp()
        translate.Set(Gf.Vec3d(*obj.get('position', [0,0,0])))
        q = obj.get('orientation_wxyz', [1,0,0,0])
        orient=xform.AddOrientOp()
        orient.Set(Gf.Quatf(q[0], Gf.Vec3f(*q[1:])))
        if kind=='counter' and obj['counter'].get('scale',1)!=1:
            scale=float(obj['counter']['scale']);xform.AddScaleOp().Set(Gf.Vec3f(scale,scale,scale))
        if kind=='camera' and 'camera_orbit' in obj:
            from .geometry import camera_orientation
            orbit=obj['camera_orbit'];center=orbit['center'];turns=orbit.get('turns',1);count=max(16,math.ceil(turns*64));previous=None
            for i in range(count+1):
                fraction=i/count;angle=orbit.get('start_angle_rad',0)+2*math.pi*turns*fraction
                position=[center[0]+orbit['radius_m']*math.cos(angle),center[1]+orbit['radius_m']*math.sin(angle),center[2]+orbit['height_m']]
                rotation=camera_orientation(position,center);time=Usd.TimeCode(orbit['duration_s']*60*fraction)
                if previous is not None and sum(a*b for a,b in zip(previous,rotation))<0:rotation=[-x for x in rotation]
                previous=rotation
                translate.Set(Gf.Vec3d(*position),time);orient.Set(Gf.Quatf(rotation[0],Gf.Vec3f(*rotation[1:])),time)
                if i==0:
                    translate.Set(Gf.Vec3d(*position));orient.Set(Gf.Quatf(rotation[0],Gf.Vec3f(*rotation[1:])))
        if kind=='asset' and name in normalizations:
            meters,axis=normalizations[name]
            if axis==UsdGeom.Tokens.y:xform.AddRotateXOp().Set(90.0)
            if abs(meters-1.0)>1e-9:xform.AddScaleOp().Set(Gf.Vec3f(meters,meters,meters))
        if kind in ('box', 'sphere'):
            size=obj.get('size',[1,1,1])
            if 'conveyor' not in obj and not size[0]==size[1]==size[2]:
                xform.AddScaleOp().Set(Gf.Vec3f(*size))
            if 'color' in obj:
                entity.CreateDisplayColorAttr([Gf.Vec3f(*obj['color'])])
            if obj.get('collision') or obj.get('dynamic'):
                UsdPhysics.CollisionAPI.Apply(entity.GetPrim())
            if obj.get('dynamic'):
                UsdPhysics.RigidBodyAPI.Apply(entity.GetPrim())
                if 'mass_kg' in obj: UsdPhysics.MassAPI.Apply(entity.GetPrim()).CreateMassAttr(obj['mass_kg'])
    stage.GetRootLayer().Save()
    return {'path':str(path), 'revision':scene['revision'], 'physics_validation':'not run',
            'normalized_visual_assets':{name:{'source_meters_per_unit':meters,'source_up_axis':str(axis)} for name,(meters,axis) in normalizations.items()}}
