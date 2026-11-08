"""SDK-only layer construction: immutable source snapshot and local derived package."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from .profiles import PreparationError,validate_parameters,preparation_key,source_identity,PROFILE_VERSION
from .glb_convert import CONVERTER,validate_glb,convert,probe,predecode_glb


def _sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _json(path, data):
    Path(path).write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf8')


def _safe_relative(value):
    path=Path(value)
    if not isinstance(value,str) or not value or path.is_absolute() or '..' in path.parts or '\\' in value:
        raise PreparationError('verification_failed','unsafe acquired file path')
    return path


def _snapshot(acquired, output):
    raw=acquired.get('root') or acquired.get('asset_path') or acquired.get('local_path')
    if not raw:raise PreparationError('source_unavailable','acquired root required')
    source=Path(raw).resolve(strict=True)
    if source.is_dir():
        entry=acquired.get('entry_path') or acquired.get('path')
        if not entry:raise PreparationError('source_unavailable','directory root requires entry_path')
        source=(source/_safe_relative(entry)).resolve(strict=True)
    files=acquired.get('files',[])
    base=source.parent;root_relative=Path(source.name)
    for item in files:
        rel=_safe_relative(item['path'])
        if tuple(source.parts[-len(rel.parts):])==rel.parts:
            root_relative=rel;base=source
            for _ in rel.parts:base=base.parent
            break
    copied=[]
    if not files:files=[{'path':source.name,'sha256':_sha(source)}]
    for item in files:
        rel=_safe_relative(item['path']);original=(base/rel).resolve(strict=True)
        if not original.is_relative_to(base) or not original.is_file():
            raise PreparationError('verification_failed','acquired closure escaped source package')
        actual=_sha(original)
        if item.get('sha256') and item['sha256']!=actual:
            raise PreparationError('verification_failed',f'acquired file hash changed: {rel}')
        expected_size=item.get('size_bytes',item.get('size'))
        if expected_size is not None and expected_size!=original.stat().st_size:
            raise PreparationError('verification_failed',f'acquired file size changed: {rel}')
        destination=output/'source'/rel;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,destination)
        copied.append({'path':rel.as_posix(),'sha256':actual,'size_bytes':destination.stat().st_size})
    root=output/'source'/root_relative
    if not root.is_file():raise PreparationError('dependency_missing','acquired files omit root')
    actual=_sha(source)
    expected=acquired.get('source_sha256') or acquired.get('sha256')
    if expected and actual!=expected:raise PreparationError('verification_failed','acquired source hash changed')
    _json(output/'source'/'acquired.json',acquired)
    (output/'licenses').mkdir(exist_ok=True)
    _json(output/'licenses'/'source-license.json',{'license':acquired.get('license','unknown'),'source_ref':acquired.get('source_ref'),
                                                'provenance':acquired.get('provenance'),'metadata':acquired.get('metadata')})
    closure_hash=hashlib.sha256(json.dumps(sorted(copied,key=lambda item:item['path']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return root,actual,closure_hash


def _strip_physics(stage):
    from pxr import Usd,UsdPhysics
    for prim in list(stage.Traverse()):
        if prim.IsA(UsdPhysics.Joint):
            prim.SetActive(False);continue
        for schema in list(prim.GetAppliedSchemas()):
            if schema.lower().startswith(('physics','physx')):
                prim.RemoveAPI(schema)
        for prop in list(prim.GetProperties()):
            if prop.GetName().startswith(('physics:','physx')):prim.RemoveProperty(prop.GetName())


def _localize_flattened(source_stage, destination, output):
    """Flatten compositions, then snapshot every resolved material/texture asset."""
    from pxr import Usd,Sdf
    source_stage.Flatten().Export(str(destination))
    stage=Usd.Stage.Open(str(destination));runtime=[]
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            if attr.GetTypeName() not in (Sdf.ValueTypeNames.Asset,Sdf.ValueTypeNames.AssetArray):continue
            if attr.GetNumTimeSamples():raise PreparationError('physics_profile_unsupported','animated asset dependencies unsupported')
            value=attr.Get();values=list(value) if attr.GetTypeName()==Sdf.ValueTypeNames.AssetArray and value else [value]
            changed=[]
            for asset in values:
                if not asset or not asset.path:changed.append(asset);continue
                resolved=asset.resolvedPath
                source=Path(resolved) if resolved else Path(asset.path)
                if source.suffix.lower()=='.mdl' and (not resolved or '/data/omniverse/' in str(source)):
                    runtime.append({'attribute':str(attr.GetPath()),'asset':asset.path,'kind':'target_runtime_mdl'});changed.append(asset);continue
                if not source.is_file():
                    raise PreparationError('dependency_missing',f'unresolved USD dependency: {asset.path}')
                if source.suffix.lower()=='.mdl':
                    raise PreparationError('dependency_missing','custom MDL requires an explicitly localized module closure')
                digest=_sha(source);dest=output/'derived'/'textures'/(digest+source.suffix.lower());dest.parent.mkdir(exist_ok=True)
                if not dest.exists():shutil.copyfile(source,dest)
                changed.append(Sdf.AssetPath('./textures/'+dest.name))
            if values and values[0] is not None:
                attr.Set(changed if attr.GetTypeName()==Sdf.ValueTypeNames.AssetArray else changed[0])
    stage.GetRootLayer().Save()
    return stage,runtime


def _material(stage, root, parameters):
    from pxr import UsdPhysics,UsdShade
    material=UsdShade.Material.Define(stage,'/Asset/PhysicsMaterial');api=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    api.CreateStaticFrictionAttr(parameters['static_friction']);api.CreateDynamicFrictionAttr(parameters['dynamic_friction']);api.CreateRestitutionAttr(parameters['restitution'])
    UsdShade.MaterialBindingAPI.Apply(root).Bind(material,materialPurpose='physics')


def _proxy_covers_surfaces(proxy,surfaces,tolerance):
    from simscene.placement import rotate
    q=proxy['orientation_wxyz'];normal=rotate(q,[0,0,1])
    if abs(normal[2]-1)>1e-6:
        raise PreparationError('physics_profile_unsupported','M1 support proxy must have horizontal upward top')
    inverse=[q[0],-q[1],-q[2],-q[3]];size=proxy['size_m'];position=proxy['position_m'];errors=[]
    for name,region in surfaces.items():
        for x in [region['min_xy'][0],region['max_xy'][0]]:
            for y in [region['min_xy'][1],region['max_xy'][1]]:
                local=rotate(inverse,[x-position[0],y-position[1],region['z_m']-position[2]])
                if abs(local[0])>size[0]/2+tolerance or abs(local[1])>size[1]/2+tolerance or abs(local[2]-size[2]/2)>tolerance:
                    raise PreparationError('physics_profile_unsupported',f'proxy does not align with measured support {name}')
                errors.append(abs(local[2]-size[2]/2))
    return max(errors)


def prepare_acquired(acquired, profile, parameters, target, output_dir, *, app=None):
    if profile=='environment_v1':
        from .environment_layer import prepare_environment
        return prepare_environment(acquired,parameters,target,output_dir)
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade,Gf,PhysxSchema
    from .inspect import inspect_stage,hull_fidelity,validate_support
    parameters=validate_parameters(profile,parameters)
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise PreparationError('verification_failed','preparation output must be empty')
    root,source_hash,closure_hash=_snapshot(acquired,output)
    derived=output/'derived';derived.mkdir()
    is_glb=root.suffix.lower()=='.glb';conversion=None
    if is_glb:
        admission=validate_glb(root,rigid=profile=='rigid_prop_v1')
        converter_input=root;predecode=None
        if set(admission['extensions']) & {'EXT_meshopt_compression','KHR_mesh_quantization'}:
            converter_input=derived/'decoded.glb'
            predecode=predecode_glb(root,converter_input,prefix=target.get('converter_tools_prefix'),allowed_root=output/'source')
        conversion=convert(converter_input,derived/'converted.usda',app=app)
        if predecode is not None:conversion['predecode']=predecode
        source_stage=Usd.Stage.Open(str(derived/'converted.usda'))
    elif root.suffix.lower() in {'.usd','.usda','.usdc'}:
        source_stage=Usd.Stage.Open(str(root))
    else:raise PreparationError('unsupported_codec','M1 supports GLB or native USD root')
    if not source_stage:raise PreparationError('conversion_failed','USD open failed')
    original=inspect_stage(source_stage)
    physics=bool(original['rigid_bodies'] or original['colliders'] or original['joints'] or original['articulations'])
    if parameters['source_physics_policy']=='reject_if_physics' and physics:
        raise PreparationError('physics_profile_unsupported','source contains physics')
    if profile=='rigid_prop_v1' and (original['rigid_bodies'] or original['joints'] or original['articulations'] or original['motion_attributes']):
        raise PreparationError('physics_profile_unsupported','rigid source must be a single passive visual with no motion/joints/bodies')
    if profile=='static_fixture_v1' and original['motion_attributes']:
        raise PreparationError('physics_profile_unsupported','static support cannot contain time-sampled motion')
    if profile=='static_fixture_v1' and parameters['collision_method']=='preserve':
        if not original['colliders'] or original['rigid_bodies'] or original['joints'] or original['articulations'] or original['motion_attributes']:
            raise PreparationError('physics_profile_unsupported','native static collision requires colliders and no dynamic/jointed/moving source')
        if parameters['scale_mode']!='preserve':raise PreparationError('physics_profile_unsupported','native static physics cannot be rescaled')
        for path in original['colliders']:
            if not UsdPhysics.CollisionAPI(source_stage.GetPrimAtPath(path)).GetCollisionEnabledAttr().Get():
                raise PreparationError('physics_profile_unsupported','disabled native collider cannot qualify as preserved support')
    if profile=='articulated_prop_v1':
        if is_glb:
            raise PreparationError('physics_profile_unsupported','articulated profile requires a native USD joint, not GLB extras')
        from .articulation import inspect_articulation
        inspect_articulation(source_stage)
    visual,runtime=_localize_flattened(source_stage,derived/'visual.usda',output)
    if profile=='visual_prop_v1' and physics and parameters['source_physics_policy']!='replace_visual_only':
        raise PreparationError('physics_profile_unsupported','visual profile must explicitly replace source physics')
    if parameters['source_physics_policy']=='replace_visual_only':
        _strip_physics(visual);visual.GetRootLayer().Save()
    source_axis='Y' if is_glb else original['up_axis'];source_units=1.0 if is_glb else original['meters_per_unit']
    if source_axis not in {'Y','Z'}:raise PreparationError('verification_failed','unsupported source up axis')
    stage=Usd.Stage.CreateNew(str(output/'main.usda'));asset=UsdGeom.Xform.Define(stage,'/Asset');stage.SetDefaultPrim(asset.GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    joint_map={};articulation_report=None;container_report=None
    body_map={};visual_path='/Asset/Body/Visual' if profile=='rigid_prop_v1' else '/Asset/Visual'
    if profile=='rigid_prop_v1':UsdGeom.Xform.Define(stage,'/Asset/Body')
    if profile=='articulated_prop_v1':
        visual_path='/Asset/Native'
    visual_xf=UsdGeom.Xform.Define(stage,visual_path)
    if source_axis=='Y':visual_xf.AddRotateXOp(opSuffix='sourceYUpToZUp').Set(90)
    scale_op=None
    if profile!='articulated_prop_v1':
        scale_op=visual_xf.AddScaleOp(opSuffix='canonicalUnitsAndSize');scale_op.Set(Gf.Vec3f(source_units))
    source_prim=visual_xf.GetPrim() if profile=='articulated_prop_v1' else UsdGeom.Xform.Define(stage,visual_path+'/Source').GetPrim()
    source_prim.GetReferences().AddReference('./derived/visual.usda')
    before=inspect_stage(stage);factor=1.0
    if parameters['scale_mode']=='fit_longest':factor=parameters['target_longest_extent_m']/max(before['bounds']['dimensions'])
    if scale_op is not None:scale_op.Set(Gf.Vec3f(source_units*factor))
    measured=inspect_stage(stage);shape_report=None;support_report=None
    if profile=='articulated_prop_v1':
        articulation_report=inspect_articulation(stage)
        body_map=articulation_report['body_map'];joint_map=articulation_report['joint_map']
    elif profile=='container_v1':
        from .container import check_geometry,author_walls
        container_report=check_geometry(stage,parameters['container_proxy'],parameters['proxy_tolerance_m'])
        body_map=author_walls(stage,parameters['container_proxy'],parameters)
    elif profile=='rigid_prop_v1':
        shape_report=hull_fidelity(stage,parameters['proxy_tolerance_m'])
        body=stage.GetPrimAtPath('/Asset/Body');UsdPhysics.RigidBodyAPI.Apply(body).CreateRigidBodyEnabledAttr(True)
        UsdPhysics.MassAPI.Apply(body).CreateMassAttr(parameters['mass_kg'])
        PhysxSchema.PhysxRigidBodyAPI.Apply(body).CreateEnableCCDAttr(parameters['ccd'])
        colliders=[]
        for mesh in measured['meshes']:
            prim=stage.GetPrimAtPath(mesh['path']);UsdPhysics.CollisionAPI.Apply(prim).CreateCollisionEnabledAttr(True)
            UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexHull');colliders.append(mesh['path'].removeprefix('/Asset/'))
        _material(stage,body,parameters)
        body_map={'main':{'relative_prim_path':'Body','role':'rigid','visual_relative_prim_paths':['Body/Visual'],'collider_relative_prim_paths':colliders}}
    elif profile=='static_fixture_v1':
        support_report=validate_support(stage,parameters['support_surfaces'],parameters['proxy_tolerance_m'])
        if parameters['collision_method']=='box_proxy':
            proxy=parameters['static_proxy'];alignment=_proxy_covers_surfaces(proxy,parameters['support_surfaces'],parameters['proxy_tolerance_m'])
            cube=UsdGeom.Cube.Define(stage,'/Asset/Proxy');cube.CreateSizeAttr(1)
            cube.AddTranslateOp().Set(Gf.Vec3d(*proxy['position_m']));q=proxy['orientation_wxyz'];cube.AddOrientOp().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])));cube.AddScaleOp().Set(Gf.Vec3f(*proxy['size_m']))
            cube.CreateVisibilityAttr('invisible');UsdPhysics.CollisionAPI.Apply(cube.GetPrim()).CreateCollisionEnabledAttr(True);_material(stage,cube.GetPrim(),parameters)
            body_map={'main':{'relative_prim_path':'Proxy','role':'static','visual_relative_prim_paths':['Visual'],'collider_relative_prim_paths':['Proxy']}}
            support_report['proxy_height_error_m']=alignment
        else:
            support_report['native_collision_coverage']=validate_support(stage,parameters['support_surfaces'],parameters['proxy_tolerance_m'],collision_only=True)
            colliders=[p.removeprefix('/Asset/') for p in inspect_stage(stage)['colliders']]
            body_map={'main':{'relative_prim_path':'Visual','role':'static','visual_relative_prim_paths':['Visual'],'collider_relative_prim_paths':colliders}}
    stage.GetRootLayer().Save()
    final=inspect_stage(stage)
    _json(output/'inspection.json',{'source':original,'normalized':measured,'prepared':final,'hull_fidelity':shape_report,'support':support_report})
    selected=CONVERTER if is_glb else {'backend':'openusd','version':'.'.join(map(str,Usd.GetVersion()))}
    identity=preparation_key(source_identity(acquired,closure_hash),profile,parameters,target,selected)
    report={'schema':'simscene.prepared_asset.v1','schema_version':1,'prepared_id':identity,'profile_id':profile,'profile_version':PROFILE_VERSION,
            'root':str(output),'asset_path':str(output/'main.usda'),'main':'main.usda','default_prim':'/Asset','parameters':parameters,'target':target,
            'source_ref':acquired.get('source_ref',acquired.get('asset_ref')),'source_sha256':source_hash,'source_closure_sha256':closure_hash,
            'source_manifest_sha256':acquired.get('manifest_sha256',acquired.get('source_manifest_hash')),'license':acquired.get('license','unknown'),
            'provenance':acquired.get('provenance'),'toolchain':selected,'body_map':body_map,'bounds':measured['bounds'],
            'source_to_output':{'source_axis':source_axis,'rotation_x_degrees':90 if source_axis=='Y' else 0,'source_meters_per_unit':source_units,
                                'uniform_size_scale':factor,'total_uniform_scale':source_units*factor},
            'runtime_dependencies':runtime,'collision_report':shape_report,'support_report':support_report,'support_surfaces':parameters.get('support_surfaces',{}),
            'physical_material_assumption':'experimental recipe values; not manufacturer facts','inertia':{'status':'runtime_check_required','method':'engine computes from collision geometry and explicit mass'},
            'runtime_verification':'unverified','runtime_validation':{'status':'not_run','physical_steps':0},'physical_steps':0,'conversion':conversion}
    if profile=='articulated_prop_v1':
        report.update(joint_map=joint_map,articulation_report=articulation_report,physical_material_assumption='preserved native source values; no material or mass rewrite',inertia={'status':'native_mass_preserved_inertia_authored_or_engine_computed_runtime_check_required'})
    elif profile=='container_v1':
        report.update(container_report=container_report)
    report['files']=[{'path':f.relative_to(output).as_posix(),'size_bytes':f.stat().st_size,'sha256':_sha(f)} for f in sorted(output.rglob('*')) if f.is_file()]
    _json(output/'manifest.json',report)
    return dict(report,manifest_path=str(output/'manifest.json'),manifest_sha256=_sha(output/'manifest.json'))
