"""Prepare a selected HDRI as a self-contained light-only USD package."""
from pathlib import Path

from .profiles import PreparationError, number, preparation_key, source_identity, PROFILE_VERSION


def validate_environment_parameters(value):
    if not isinstance(value,dict) or set(value)-{'intensity','exposure','texture_format'}:
        raise PreparationError('physics_profile_unsupported','environment_v1 accepts intensity,exposure,texture_format only')
    p=dict(value)
    p['intensity']=number(p.get('intensity',300),'intensity',nonnegative=True)
    p['exposure']=number(p.get('exposure',0),'exposure')
    p.setdefault('texture_format','latlong')
    if p['intensity']>100000 or not -10<=p['exposure']<=10 or p['texture_format']!='latlong':
        raise PreparationError('physics_profile_unsupported','environment bounds or texture format unsupported')
    return p


def prepare_environment(acquired, parameters, target, output_dir):
    from pxr import Usd,UsdGeom,UsdLux,Sdf,UsdUtils
    from .usd_layers import _snapshot,_json,_sha
    p=validate_environment_parameters(parameters)
    if acquired.get('asset_type')!='hdri' or Path(acquired.get('root','')).suffix.lower() not in {'.exr','.hdr'}:
        raise PreparationError('physics_profile_unsupported','environment_v1 requires one selected HDRI, not arbitrary image/material geometry')
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise PreparationError('verification_failed','environment preparation output must be empty')
    source,source_hash,closure_hash=_snapshot(acquired,output)
    stage=Usd.Stage.CreateNew(str(output/'main.usda'))
    root=UsdGeom.Xform.Define(stage,'/Asset');stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    dome=UsdLux.DomeLight.Define(stage,'/Asset/Environment')
    dome.CreateTextureFileAttr(Sdf.AssetPath('./'+source.relative_to(output).as_posix()))
    dome.CreateTextureFormatAttr(p['texture_format']);dome.CreateIntensityAttr(p['intensity']);dome.CreateExposureAttr(p['exposure'])
    stage.GetRootLayer().Save()
    layers,assets,missing=UsdUtils.ComputeAllDependencies(str(output/'main.usda'))
    if missing or not assets:
        raise PreparationError('dependency_missing','prepared HDRI dependency closure is unresolved')
    for asset in assets:
        dependency=Path(str(asset)).resolve()
        if not dependency.is_relative_to(output) or not dependency.is_file():
            raise PreparationError('dependency_missing','environment dependency escapes the hashed package')
    toolchain={'backend':'openusd','version':'.'.join(map(str,Usd.GetVersion()))}
    identity=preparation_key(source_identity(acquired,closure_hash),'environment_v1',p,target,toolchain)
    report={'schema':'simscene.prepared_asset.v1','schema_version':1,'prepared_id':identity,
        'profile_id':'environment_v1','profile_version':PROFILE_VERSION,'parameters':p,'target':target,'toolchain':toolchain,
        'root':str(output),'asset_path':str(output/'main.usda'),'main':'main.usda','default_prim':'/Asset',
        'source_ref':acquired.get('source_ref'),'source_sha256':source_hash,'source_closure_sha256':closure_hash,
        'source_manifest_sha256':acquired.get('manifest_sha256'),'license':acquired.get('license'),
        'provenance':acquired.get('provenance'),'bounds':None,'body_map':{},'joint_map':{},'support_surfaces':{},
        'runtime_dependencies':[],'material_report':{'inspected_material_count':0},'collision_report':None,'support_report':None,
        'environment_report':{'texture_path':source.relative_to(output).as_posix(),'texture_sha256':source_hash,
            'role':'non-geometric dome illumination','render_validation':'not_run','physics_authored':False},
        'runtime_validation':{'status':'not_run','physical_steps':0},'runtime_verification':'unverified','physical_steps':0}
    _json(output/'inspection.json',report['environment_report'])
    report['files']=[{'path':file.relative_to(output).as_posix(),'size_bytes':file.stat().st_size,'sha256':_sha(file)} for file in sorted(output.rglob('*')) if file.is_file()]
    _json(output/'manifest.json',report)
    return dict(report,manifest_path=str(output/'manifest.json'),manifest_sha256=_sha(output/'manifest.json'))
