"""Hash saved outputs to detect later changes; not a cryptographic signature."""
import hashlib,json,os,tempfile
from pathlib import Path

def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def _artifacts(root,result_name):
    if result_name not in ('result.json','partial-result.json'):raise ValueError('invalid result name')
    result=json.loads((root/result_name).read_text());paths=[root/result_name]
    for value in (result.get('images') or {}).values():paths.append(Path(value))
    for value in (result.get('videos') or {}).values():
        paths.append(Path(value['path']))
        if value.get('encoder_log'):paths.append(Path(value['encoder_log']))
    if result.get('archived_objects'):
        paths.append(root/'archive-ledger.jsonl')
    result_paths={}
    for path in paths:
        if path.is_symlink() or path.resolve().parent!=root or not path.is_file():raise ValueError('artifact is missing or outside the run directory')
        name=path.name
        if name in result_paths:raise ValueError('duplicate artifact path')
        result_paths[name]=path
    return result_paths

def seal(directory,result_name='result.json'):
    root=Path(directory).resolve();paths=_artifacts(root,result_name)
    data={'result_file':result_name,'partial':result_name!='result.json',
          'artifacts':{name:{'size':path.stat().st_size,'sha256':_sha(path)} for name,path in paths.items()}}
    with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=root,prefix='.evidence-',delete=False) as file:
        temp=file.name
        try:
            json.dump(data,file,indent=2);file.flush();os.fsync(file.fileno());os.replace(temp,root/'evidence-lock.json')
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return data

def verify(directory):
    root=Path(directory).resolve();errors=[];checks={}
    try:
        manifest=json.loads((root/'evidence-lock.json').read_text());name=manifest['result_file']
        paths=_artifacts(root,name);entries=manifest['artifacts']
        if not isinstance(entries,dict) or set(entries)!=set(paths):raise ValueError('artifact list does not match result')
        for artifact,path in paths.items():
            record=entries[artifact]
            checks[artifact]=path.stat().st_size==record['size'] and _sha(path)==record['sha256']
            if not checks[artifact]:errors.append('artifact missing or changed: '+artifact)
        partial=manifest.get('partial') is True
        if partial!=(name=='partial-result.json'):raise ValueError('inconsistent partial flag')
        return {'passed':all(checks.values()),'partial':partial,'checks':checks,'errors':errors,'scope':'saved artifact hashes; not a signature or proof of task success'}
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        return {'passed':False,'partial':None,'checks':checks,'errors':errors+[str(error)],'scope':'saved artifact hashes; not a signature or proof of task success'}
