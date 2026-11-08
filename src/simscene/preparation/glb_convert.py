"""The single spike-verified SDK converter; imports remain worker-local."""
import asyncio
import hashlib
import os
import shutil
import subprocess
import json
import math
import struct
import time
from pathlib import Path
from .profiles import PreparationError

PREDECODE_SCRIPT = r"""
import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import {MeshoptDecoder} from 'meshoptimizer';
import fs from 'node:fs';
import crypto from 'node:crypto';
await MeshoptDecoder.ready;
const [input,output]=process.argv.slice(1);
const before=fs.readFileSync(input);
const io=new NodeIO().setAllowNetwork(false).registerExtensions(ALL_EXTENSIONS)
 .registerDependencies({'meshopt.decoder':MeshoptDecoder});
const document=await io.read(input);
const attributes=new Set(document.getRoot().listMeshes().flatMap(mesh=>mesh.listPrimitives().flatMap(primitive=>
 [...primitive.listAttributes(),...primitive.listTargets().flatMap(target=>target.listAttributes())])));
let dequantized=0;
for(const accessor of attributes){
 if(accessor.getComponentType()===5126)continue;
 const values=new Float32Array(accessor.getCount()*accessor.getElementSize());const element=[];
 for(let i=0;i<accessor.getCount();i++){accessor.getElement(i,element);values.set(element,i*accessor.getElementSize());}
 accessor.setArray(values).setNormalized(false);dequantized++;
}
for(const extension of document.getRoot().listExtensionsUsed())
 if(['EXT_meshopt_compression','KHR_mesh_quantization'].includes(extension.extensionName))extension.dispose();
await io.write(output,document);
if(!before.equals(fs.readFileSync(input)))throw new Error('source changed during predecode');
console.log(JSON.stringify({source_sha256:crypto.createHash('sha256').update(before).digest('hex'),
 output_sha256:crypto.createHash('sha256').update(fs.readFileSync(output)).digest('hex'),
 dequantized_attribute_accessors:dequantized,source_unchanged:true}));
"""
PREDECODER = {'backend':'gltf-transform-meshopt','core_version':'4.5.1','extensions_version':'4.5.1',
              'meshoptimizer_version':'1.3.0','node_version':'v22.23.2',
              'package_lock_sha256':'bac0ab1332c821de5680b887f828014d86a71eb930b14d91fd938e36c45bdff0',
              'node_modules_sha256':'3bfdef144f9a32d73ab5147f5be0dcd2e9e731a28b56f9ae7e521a46e590c302',
              'script_sha256':hashlib.sha256(PREDECODE_SCRIPT.encode()).hexdigest(),
              'max_decoded_bytes':256*1024**2}
CONVERTER = {'backend':'omni.kit.asset_converter','version':'6.1.0','usd_version':'0.25.11',
             'canonicalization':'explicit_Rx90_once','codec_policy_version':2,'predecoder':PREDECODER}



def validate_glb(path, *, rigid=False):
    from simscene.acquisition.glb import inspect_glb
    try:
        report = inspect_glb(path)
        with Path(path).open('rb') as stream:
            stream.seek(12);length,kind=struct.unpack('<II',stream.read(8))
            doc=json.loads(stream.read(length))
    except (ValueError,OSError,struct.error) as error:
        raise PreparationError('conversion_failed',f'invalid GLB: {error}') from error
    def finite_json(value):
        if isinstance(value,float) and not math.isfinite(value):
            raise PreparationError('verification_failed','nonfinite GLB JSON value')
        if isinstance(value,dict):
            for item in value.values():finite_json(item)
        elif isinstance(value,list):
            for item in value:finite_json(item)
    finite_json(doc)
    # No optional codec is inferred from a linked library or vendor documentation.
    allowed={'KHR_materials_unlit','KHR_texture_transform','KHR_materials_pbrSpecularGlossiness',
             'KHR_materials_ior','KHR_materials_clearcoat','KHR_materials_emissive_strength',
             'EXT_meshopt_compression','EXT_texture_webp','KHR_mesh_quantization'}
    rejected=set(report['extensions'])-allowed
    if rejected or report['unknown_chunks']:
        raise PreparationError('unsupported_codec',f'unverified GLB extensions/chunks: {sorted(rejected)}')
    for image in doc.get('images',[]):
        mime=image.get('mimeType','')
        uri=image.get('uri','').lower()
        if mime and mime not in {'image/png','image/jpeg','image/webp'} or uri.endswith(('.ktx','.ktx2')):
            raise PreparationError('unsupported_codec','only PNG/JPEG/WebP texture inputs are admitted')
    if rigid and (doc.get('skins') or doc.get('animations') or any('skin' in n for n in doc.get('nodes',[]))):
        raise PreparationError('physics_profile_unsupported','rigid source cannot contain skinning or animation')
    def physics(node):
        if isinstance(node,dict):
            return any(str(k).lower() in {'physics','rigidbody','rigid_body','joint','joints','articulation'} or physics(v) for k,v in node.items())
        if isinstance(node,list):return any(physics(v) for v in node)
        return False
    if rigid and physics(doc):
        raise PreparationError('physics_profile_unsupported','rigid source declares physics/joints')
    return report


def probe(prefix=None):
    import omni.kit.app
    manager=omni.kit.app.get_app().get_extension_manager()
    manager.set_extension_enabled_immediate('omni.kit.asset_converter',True)
    extension=manager.get_enabled_extension_id('omni.kit.asset_converter')
    from pxr import Usd
    actual={'backend':'omni.kit.asset_converter','version':extension.rsplit('-',1)[-1],
            'usd_version':'.'.join(str(v) for v in Usd.GetVersion()),
            'canonicalization':'explicit_Rx90_once','codec_policy_version':2,'predecoder':PREDECODER}
    if actual != CONVERTER:
        raise PreparationError('plan_environment_changed',f'converter environment changed: {actual}')
    configured_prefix=prefix or os.environ.get('SIMSCENE_GLTF_TRANSFORM_PREFIX')
    configuration=predecoder_fingerprint(configured_prefix) if configured_prefix else None
    return dict(actual,available=True,verified_codecs=['uncompressed_glTF2','PNG','WebP'],
                predecoder_available=configuration is not None,predecoder_configuration=configuration,
                verified_predecode_codecs=['EXT_meshopt_compression','KHR_mesh_quantization'],jpeg='documented')


async def convert_glb(input_path, output_path):
    probe()
    import omni.kit.asset_converter as converter
    context=converter.AssetConverterContext()
    for name,value in {'use_meter_as_world_unit':True,'convert_stage_up_z':True,
                       'export_preview_surface':True,'ignore_animations':True,
                       'ignore_camera':True,'ignore_light':True,'create_world_as_default_root_prim':True}.items():
        setattr(context,name,value)
    task=converter.get_instance().create_converter_task(str(input_path),str(output_path),lambda a,b:None,context)
    success=await task.wait_until_finished()
    report={'success':success,'status':str(task.get_status()),'error':task.get_error_message(),'converter':CONVERTER}
    if not success or report['error']:
        raise PreparationError('conversion_failed',f'conversion incomplete: {report}')
    return report


def convert(input_path, output_path, *, app=None, timeout_seconds=180):
    """Called on the SDK main thread; no simulation timeline or physical steps."""
    import omni.kit.app
    update=app.update if app is not None else omni.kit.app.get_app().update
    future=asyncio.ensure_future(convert_glb(input_path,output_path));deadline=time.monotonic()+timeout_seconds
    try:
        while not future.done():
            if time.monotonic()>deadline:
                future.cancel()
                raise PreparationError('conversion_failed','converter deadline exceeded')
            update()
        return future.result()
    except BaseException:
        if not future.done():future.cancel()
        raise

class Converter:
    probe=staticmethod(probe)
    convert=staticmethod(convert)


def predecoder_fingerprint(prefix=None):
    """CPU-only optional environment probe; execution never installs packages."""
    prefix=prefix or os.environ.get('SIMSCENE_GLTF_TRANSFORM_PREFIX')
    if not prefix or not Path(prefix).is_dir():
        raise PreparationError('dependency_missing','meshopt requires frozen converter_tools_prefix or SIMSCENE_GLTF_TRANSFORM_PREFIX')
    prefix=Path(prefix).resolve();node=shutil.which('node')
    if not node:raise PreparationError('dependency_missing','isolated meshopt predecoder requires Node.js')
    try:
        version=subprocess.run([node,'--version'],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        lock=hashlib.sha256((prefix/'package-lock.json').read_bytes()).hexdigest()
        modules=prefix/'node_modules';files=[]
        for file in sorted(modules.rglob('*')):
            if file.is_file():files.append({'path':file.relative_to(modules).as_posix(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        tree=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        versions=[json.loads((modules/name/'package.json').read_text())['version'] for name in ['@gltf-transform/core','@gltf-transform/extensions','meshoptimizer']]
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        raise PreparationError('dependency_missing','meshopt predecoder installation is incomplete') from error
    if version!=PREDECODER['node_version'] or lock!=PREDECODER['package_lock_sha256'] or tree!=PREDECODER['node_modules_sha256'] or versions!=['4.5.1','4.5.1','1.3.0']:
        raise PreparationError('plan_environment_changed','meshopt predecoder version/content fingerprint changed')
    return dict(PREDECODER,prefix=str(prefix),node_path=node)


def predecode_glb(input_path, output_path, *, prefix=None, allowed_root=None):
    """Bounded, immutable-source meshopt decode before the selected USD converter."""
    input_path=Path(input_path).resolve();output_path=Path(output_path).resolve()
    validate_glb(input_path)
    with input_path.open('rb') as stream:
        stream.seek(12);length,_=struct.unpack('<II',stream.read(8));doc=json.loads(stream.read(length))
    limit=PREDECODER['max_decoded_bytes'];estimated=0
    for buffer in doc.get('buffers',[]):
        size=buffer.get('byteLength')
        if type(size) is not int or size<0:raise PreparationError('conversion_failed','invalid decoded buffer size')
        estimated+=size
    elements={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT2':4,'MAT3':9,'MAT4':16}
    for accessor in doc.get('accessors',[]):
        count=accessor.get('count');width=elements.get(accessor.get('type'))
        if type(count) is not int or count<0 or width is None:raise PreparationError('conversion_failed','invalid decoded accessor count')
        estimated+=count*width*4
    if estimated>limit:raise PreparationError('budget_exceeded','meshopt decoded allocation budget exceeded')
    allowed_root=Path(allowed_root).resolve() if allowed_root else input_path.parent
    from simscene.acquisition.glb import inspect_glb
    for dependency in inspect_glb(input_path)['dependencies']:
        uri=dependency['uri']
        if uri.startswith('data:'):continue
        from urllib.parse import urlsplit,unquote
        if urlsplit(uri).scheme or uri.startswith('/') or '\\' in uri or '%' in uri or '?' in uri or '#' in uri:
            raise PreparationError('dependency_missing','predecoder dependencies must be local package paths')
        resolved=(input_path.parent/unquote(uri)).resolve()
        if not resolved.is_relative_to(allowed_root) or not resolved.is_file():
            raise PreparationError('dependency_missing','predecoder dependency escaped/is missing from source package')
    configuration=predecoder_fingerprint(prefix);before=hashlib.sha256(input_path.read_bytes()).hexdigest()
    command=[configuration['node_path'],'--max-old-space-size=512','--input-type=module','-e',PREDECODE_SCRIPT,str(input_path),str(output_path)]
    try:
        process=subprocess.run(command,cwd=configuration['prefix'],capture_output=True,text=True,timeout=90)
    except (OSError,subprocess.SubprocessError) as error:
        raise PreparationError('conversion_failed','meshopt predecoder process failed/timed out') from error
    log={'exit_code':process.returncode,'stdout':process.stdout,'stderr':process.stderr,'toolchain':PREDECODER,'estimated_decoded_bytes':estimated}
    output_path.with_suffix('.predecode.json').write_text(json.dumps(log,indent=2)+'\n')
    if hashlib.sha256(input_path.read_bytes()).hexdigest()!=before:
        raise PreparationError('verification_failed','source bytes changed during predecode')
    if process.returncode or not output_path.is_file():
        raise PreparationError('conversion_failed','meshopt predecoder failed; process log retained')
    if output_path.stat().st_size>limit:raise PreparationError('budget_exceeded','predecoded GLB exceeds byte budget')
    decoded=validate_glb(output_path)
    if any(ext in decoded['extensions'] for ext in ['EXT_meshopt_compression','KHR_mesh_quantization']):
        raise PreparationError('conversion_failed','predecode left compressed/quantized input')
    return dict(log,source_sha256=before,output_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),source_unchanged=True)
