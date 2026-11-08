"""Portable prepared-role contracts. Pure CPU; no downloads, jobs or scene writes."""
from copy import deepcopy
import json
import re

from ..catalog.models import AssetRef
from ..physics_binding import validate_asset_binding
from ..preparation.profiles import validate_parameters

SCHEMA='simscene.selected_assets.v2'


def portable(value):
    """Reject local locators rather than silently dropping actual recipe inputs."""
    json.dumps(value,allow_nan=False)
    def check(item):
        if isinstance(item,str) and not item.startswith(('/World/','/Asset')) and (item.startswith(('/','~','file:')) or re.match(r'^[A-Za-z]:[\\/]',item)):
            raise ValueError('portable recipe cannot contain a local absolute path')
        if isinstance(item,dict):
            for child in item.values():check(child)
        if isinstance(item,list):
            for child in item:check(child)
    check(value)
    return deepcopy(value)


def _files(files):
    if not isinstance(files,list) or not 0<len(files)<=4096:raise ValueError('bounded source file table required')
    result=[];seen=set()
    for item in files:
        path=item['path'];size=item.get('size_bytes',item.get('size'))
        if (not isinstance(path,str) or not path or path.startswith('/') or '\\' in path or any(p in ('','.','..') for p in path.split('/'))
                or path in seen or type(size) is not int or size<0 or not re.fullmatch('[0-9a-f]{64}',str(item.get('sha256','')))):
            raise ValueError('invalid portable source file inventory')
        seen.add(path);result.append({'path':path,'size_bytes':size,'sha256':item['sha256']})
    if not result:raise ValueError('complete source file hashes required')
    return sorted(result,key=lambda item:item['path'])


def _generation_intent(identity,provenance):
    if not isinstance(identity,dict) or type(identity.get('seed')) is not int or identity['seed']!=0:
        raise ValueError('unsupported generated source: explicit trusted recipe and seed 0 required')
    from ..generation.sand3d import parameters,COMMIT
    if not re.fullmatch('[0-9a-f]{64}',str(identity.get('template_sha256',''))):raise ValueError('trusted template content pin required')
    recipe=identity.get('recipe_id');p=parameters(recipe,identity.get('parameters'))
    runtime=identity.get('toolchain') or {}
    if provenance.get('generator')!='sand3d' or provenance.get('reviewed_commit')!=COMMIT or runtime.get('reviewed_commit')!=COMMIT:
        raise ValueError('unsupported generated source runtime')
    # Python executable locations are runtime configuration, not portable intent.
    observed=runtime.get('observed',{})
    return portable({'generator':'sand3d','recipe_id':recipe,'parameters':p,'seed':0,
        'reviewed_commit':COMMIT,'template_sha256':identity.get('template_sha256'),
        'toolchain_intent':{key:value for key,value in observed.items() if key not in ('python','executable','python_executable','path')}})


def prepared_selection(manifest,acquired,*,manifest_sha256):
    """Export validated caller data; historical package pins are informational."""
    ref=AssetRef.from_dict(manifest['source_ref']);ref.validate_selection()
    if ref.revision.lower() in ('unknown','main','master','latest','head'):raise ValueError('immutable source revision required')
    parameters=validate_parameters(manifest['profile_id'],manifest['parameters'])
    result={'provider':'prepared','source_ref':ref.to_dict(),'profile_id':manifest['profile_id'],
        'profile_version':manifest['profile_version'],'parameters':parameters,'target':manifest['target'],
        'toolchain':manifest['toolchain'],'source_sha256':manifest['source_sha256'],
        'source_closure_sha256':manifest['source_closure_sha256'],'source_files':_files(acquired['files']),
        'previous_preparation':{'prepared_id':manifest['prepared_id'],'manifest_sha256':manifest_sha256,
            'source_manifest_sha256':manifest.get('source_manifest_sha256'),'scope':'informational; rebuild may change absolute provenance; no physics verdict reused'}}
    if acquired.get('source_ref')!=manifest['source_ref']:raise ValueError('source attribution differs from prepared manifest')
    if ref.source_id=='local-sand3d':
        provenance=manifest.get('provenance') or {}
        result['generation']=_generation_intent(provenance.get('identity'),provenance)
        if ref.asset_id!=result['generation']['recipe_id']:raise ValueError('generated source reference differs from trusted recipe')
    else:
        metadata=acquired.get('metadata')
        if not isinstance(metadata,dict) or metadata.get('ref')!=manifest['source_ref']:
            raise ValueError('prepared source metadata missing; use full project export')
        # Only fields required to reconstruct an ordinary immutable asset plan.
        result['source_record']={key:deepcopy(metadata[key]) for key in ('ref','title','format','entry_path','license','availability','provenance') if key in metadata}
    return portable(result)


def validate_rebuilt(selection,binding):
    """Verify complete new package and original geometry/profile, not old paths."""
    manifest=validate_asset_binding(binding['asset_binding'],asset_path=binding['asset_path'])
    for key in ('profile_id','profile_version','parameters','target','toolchain','source_sha256','source_closure_sha256'):
        expected=selection[key]
        actual=validate_parameters(manifest['profile_id'],manifest['parameters']) if key=='parameters' else manifest.get(key)
        if actual!=expected:raise ValueError('rebuilt prepared role differs: '+key)
    if 'generation' not in selection:
        if manifest.get('source_ref')!=selection['source_ref']:raise ValueError('rebuilt source reference differs')
    else:
        actual_ref=AssetRef.from_dict(manifest.get('source_ref'))
        if actual_ref.source_id!='local-sand3d' or actual_ref.asset_id!=selection['generation']['recipe_id']:
            raise ValueError('rebuilt generated source attribution differs')
        provenance=manifest.get('provenance') or {}
        if _generation_intent(provenance.get('identity'),provenance)!=selection['generation']:
            raise ValueError('rebuilt generator recipe/runtime differs')
    source_files=_files([dict(f,path=f['path'][7:]) for f in manifest['files'] if f['path'].startswith('source/') and f['path']!='source/acquired.json'])
    if source_files!=selection['source_files']:raise ValueError('rebuilt source file content changed')
    return manifest


def resolve_operations(recipe,catalog,*,selections=None):
    """Resolve new typed roles and retain legacy asset:// string substitution."""
    def legacy(value):
        if isinstance(value,str) and value.startswith('asset://'):
            entry=catalog[value[8:]]
            return entry['root'] if isinstance(entry,dict) else entry
        if isinstance(value,dict):return {key:legacy(child) for key,child in value.items()}
        if isinstance(value,list):return [legacy(child) for child in value]
        return value
    operations=deepcopy(recipe['operations'])
    for operation in operations:
        obj=operation.get('object')
        if not isinstance(obj,dict) or 'asset_role' not in obj:continue
        role=obj.pop('asset_role')
        if obj.get('kind')!='asset' or 'asset_path' in obj or 'asset_binding' in obj:
            raise ValueError('prepared asset_role must have exactly one binding source')
        binding=catalog[role]
        if not isinstance(binding,dict) or set(binding)!={'asset_path','asset_binding'} or set(binding['asset_binding'])!={'manifest_path','manifest_sha256'}:
            raise ValueError('prepared role requires asset_path and exact two-key asset_binding')
        if selections is None or selections[role].get('provider')!='prepared':
            raise ValueError('prepared role requires its portable selection lock')
        validate_rebuilt(selections[role],binding)
        obj.update(deepcopy(binding))
    return legacy(operations)


def member_path(value):
    """A literal package-relative filename, with no URI or traversal encoding."""
    if (not isinstance(value,str) or not value or value.startswith('/') or '\\' in value
            or any(c in value for c in ('%','?', '#', ':')) or any(ord(c)<32 for c in value)
            or any(part in ('','.','..') for part in value.split('/'))):
        raise ValueError('unsafe selected package member path')
    return value


def exported_member(package,metadata,asset_path):
    """Identify a selected legacy submember without changing its source lock."""
    from pathlib import Path
    from ..cache import _sha256
    package=Path(package).absolute();selected=Path(asset_path).absolute()
    try:relative=member_path(selected.relative_to(package).as_posix())
    except ValueError as error:raise ValueError('selected asset is outside its frozen package') from error
    files={item['path']:item for item in metadata['files']}
    if relative not in files:raise ValueError('selected member is outside the source file closure')
    raw=metadata.get('root');primary=None
    if raw:
        root=Path(raw)
        try:primary=member_path(root.relative_to(package).as_posix())
        except ValueError:
            matches=[i for i,part in enumerate(root.parts) if part==metadata.get('package_sha256')]
            if len(matches)!=1:raise ValueError('legacy source root cannot be relocated unambiguously')
            primary=member_path('/'.join(root.parts[matches[0]+1:]))
    else:
        matches=[item['path'] for item in metadata['files'] if item.get('url')==metadata['source']]
        if len(matches)==1:primary=member_path(matches[0])
        elif len(files)==1:primary=member_path(next(iter(files)))
        else:raise ValueError('legacy source root is missing from package lock')
    if primary not in files:raise ValueError('legacy source root is outside the source closure')
    if relative==primary:return relative,None
    expected=files[relative]
    if (not selected.is_file() or any(p.is_symlink() for p in (selected,*selected.parents))
            or not selected.resolve().is_relative_to(package.resolve())
            or selected.stat().st_size!=expected.get('size_bytes',expected.get('size'))
            or _sha256(selected)!=expected['sha256']):
        raise ValueError('selected package member bytes changed')
    return relative,{'path':relative,'sha256':expected['sha256']}


def resolve_member(selection,acquired,package):
    """Return a relocated result copy after verifying the selected closure member."""
    from pathlib import Path
    from ..cache import _sha256
    member=selection.get('selected_member')
    if member is None:return acquired
    if not isinstance(member,dict) or set(member)!={'path','sha256'} or not re.fullmatch('[0-9a-f]{64}',str(member.get('sha256',''))):
        raise ValueError('selected member requires exact path and SHA256')
    relative=member_path(member['path']);files={item['path']:item for item in acquired['files']}
    if relative not in files or files[relative]['sha256']!=member['sha256']:
        raise ValueError('selected member is not pinned by the verified source closure')
    package=Path(package).absolute();selected=package/relative;expected=files[relative]
    if (not selected.is_file() or any(p.is_symlink() for p in (selected,*selected.parents))
            or not selected.resolve().is_relative_to(package.resolve())
            or selected.stat().st_size!=expected.get('size_bytes',expected.get('size'))
            or _sha256(selected)!=member['sha256']):
        raise ValueError('selected package member is missing or changed')
    return dict(acquired,root=str(selected))
