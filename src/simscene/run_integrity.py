"""Recheck persisted run inputs against their recorded content hashes."""
import json
from pathlib import Path,PurePosixPath
from .cache import AssetCache,_sha256

def verify(directory):
    root=Path(directory).expanduser().resolve()
    manifest=json.loads((root/'run-lock.json').read_text())
    checks={};errors=[]
    for filename,key in [('spec.json','spec_sha256'),('scene.usda','stage_sha256'),('asset-lock.json','asset_lock_sha256'),('runtime-lock.json','runtime_lock_sha256')]:
        path=root/filename;checks[filename]=bool(path.is_file() and _sha256(path)==manifest.get(key))
        if not checks[filename]:errors.append(f'{filename} missing or changed')
    if not all(checks.values()):return {'passed':False,'checks':checks,'errors':errors,'scope':'run input integrity, not physical task success'}
    case_file=manifest.get('acceptance_case_file');case_hash=manifest.get('acceptance_case_sha256')
    if case_file is not None or case_hash is not None:
        valid=case_file in ('acceptance-case.json','acceptance-case.yaml','acceptance-case.yml') and isinstance(case_hash,str)
        path=root/case_file if valid else None
        valid=bool(valid and path.is_file() and _sha256(path)==case_hash)
        checks['acceptance_case']=valid
        if not valid:errors.append('acceptance case missing or changed')
    asset_lock=json.loads((root/'asset-lock.json').read_text())
    runtime_lock=json.loads((root/'runtime-lock.json').read_text())
    spec=json.loads((root/'spec.json').read_text());objects=spec.get('objects',{})
    if not isinstance(objects,dict) or not isinstance(asset_lock,dict) or not isinstance(runtime_lock,dict):
        return {'passed':False,'checks':checks,'errors':errors+['invalid spec or lock structure'],'scope':'run input integrity, not physical task success'}
    asset_names={name for name,obj in objects.items() if isinstance(obj,dict) and obj.get('kind')=='asset'}
    controller_names={name for name,obj in objects.items() if isinstance(obj,dict) and obj.get('pose_follower')}
    checks['asset_lock_coverage']=asset_names==set(asset_lock)
    checks['controller_lock_coverage']=controller_names==set(runtime_lock)
    if not checks['asset_lock_coverage']:errors.append('asset lock does not cover the scene assets')
    if not checks['controller_lock_coverage']:errors.append('runtime lock does not cover the scene controllers')
    for name,record in asset_lock.items():
        try:
            configured=Path(objects[name]['asset_path']).expanduser().resolve()
            if record.get('kind')=='external':
                if not record.get('files'):raise ValueError('external asset has no file hashes')
                if configured!=Path(record['path']).resolve() or str(configured) not in {item['path'] for item in record['files']}:
                    raise ValueError('external root asset is not the locked path')
                for item in record['files']:
                    path=Path(item['path'])
                    if not path.is_file() or path.stat().st_size!=item['size'] or _sha256(path)!=item['sha256']:raise ValueError('external dependency missing or changed: '+str(path))
            elif record.get('kind')=='prepared_snapshot':
                from .physics_binding import validate_asset_binding
                relative=PurePosixPath(record['manifest_relative_to_run'])
                if relative.is_absolute() or '..' in relative.parts or len(relative.parts)!=3 or relative.parts[0]!='assets':
                    raise ValueError('invalid prepared snapshot path')
                bound=objects[name].get('asset_binding')
                expected={'manifest_path':str(root/relative),'manifest_sha256':record['manifest_sha256']}
                if bound!=expected or configured!=(root/record['root_relative_to_run']).resolve():
                    raise ValueError('prepared scene path does not match locked snapshot')
                prepared=validate_asset_binding(bound,require_dynamic=objects[name].get('dynamic',False),asset_path=str(configured))
                if prepared['prepared_id']!=record['prepared_id']:raise ValueError('prepared identity changed')
                from .preparation.snapshots import verify_prepared_runtime
                verify_prepared_runtime((root/relative).parent,prepared,record,manifest.get('runtime_python'))
            elif record.get('kind')=='snapshot':
                relative=PurePosixPath(record['root_relative_to_run'])
                if relative.is_absolute() or '..' in relative.parts or len(relative.parts)<3 or relative.parts[0]!='assets':raise ValueError('invalid snapshot path')
                package=root/'assets'/relative.parts[1]
                if not package.is_dir():raise ValueError('snapshot package missing')
                if configured!=(root/relative).resolve():raise ValueError('scene asset path does not point to the snapshot')
                AssetCache(None,root/'assets')._verified_cached(package,record['package_sha256'],record['source'],touch=False)
                from .snapshot_integrity import PIN_FIELDS, verify_snapshot
                if PIN_FIELDS & set(record):
                    verify_snapshot(package, record, root, manifest.get('runtime_python'))
            else:raise ValueError('unknown asset lock kind')
            runtime_deps=record.get('runtime_provided_dependencies',{})
            runtime_hashes=record.get('runtime_dependency_sha256',{})
            if set(runtime_deps)!=set(runtime_hashes):raise ValueError('runtime dependency hashes incomplete')
            for key,digest in runtime_hashes.items():
                path=Path(runtime_deps[key])
                if not path.is_file() or _sha256(path)!=digest:raise ValueError('runtime dependency missing or changed: '+str(path))
            checks['asset:'+name]=True
        except Exception as error:
            checks['asset:'+name]=False;errors.append(f'asset {name}: {error}')
    for name,record in runtime_lock.items():
        from .scene import _id
        try:
            _id(name);hashes=record.get('files_sha256');valid=isinstance(hashes,dict) and bool(hashes)
            config=objects[name]['pose_follower'];model_dir=(root/'models'/name).resolve()
            valid=valid and Path(config['model_directory']).expanduser().resolve()==model_dir
            if config.get('gripper_urdf'):
                gripper=Path(config['gripper_urdf']).expanduser().resolve()
                valid=valid and gripper.parent==model_dir and gripper.name in hashes
        except (ValueError,TypeError):valid=False
        except (KeyError,OSError):valid=False
        for filename,digest in (hashes if valid else {}).items():
            if Path(filename).name!=filename:valid=False;break
            path=root/'models'/name/filename
            if not path.is_file() or not path.resolve().is_relative_to((root/'models').resolve()) or _sha256(path)!=digest:valid=False;break
        checks['controller:'+name]=valid
        if not valid:errors.append('controller files missing or changed: '+name)
    if 'worker_code_sha256' in manifest:
        hashes=manifest['worker_code_sha256'];package=root/'runtime'/'simscene'
        valid=isinstance(hashes,dict) and bool(hashes) and package.is_dir()
        if valid:
            actual={str(path.relative_to(package)) for path in package.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc'}
            valid=actual==set(hashes)
            for name,digest in hashes.items():
                relative=PurePosixPath(name)
                if relative.is_absolute() or '..' in relative.parts or not relative.parts or not isinstance(digest,str):valid=False;break
                path=package.joinpath(*relative.parts)
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(package.resolve()) or _sha256(path)!=digest:
                    valid=False;break
        checks['worker_code_snapshot']=valid
        if not valid:errors.append('worker code snapshot missing or changed')
    executable=Path(manifest.get('runtime_python',''))
    checks['runtime_launcher']=bool(executable.is_file() and _sha256(executable)==manifest.get('runtime_python_sha256'))
    if not checks['runtime_launcher']:errors.append('runtime launcher missing or changed')
    if 'queue_launcher_python' in manifest:
        queue_python=Path(manifest['queue_launcher_python'])
        checks['queue_launcher']=bool(queue_python.is_file() and _sha256(queue_python)==manifest.get('queue_launcher_python_sha256'))
        if not checks['queue_launcher']:errors.append('queue launcher missing or changed')
    return {'passed':all(checks.values()),'checks':checks,'errors':errors,'scope':'recorded run input integrity; external files may change after this check and physics success is not established'}
