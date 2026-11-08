"""Freeze a new acceptance template against rebuilt, content-checked roles."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .io import validate_rebuilt

MARKER=re.compile(r'^\$\{([A-Za-z0-9_-]+)\.(manifest_sha256|source_ref)\}$')


def freeze_case(template, bindings, selections):
    """Resolve whole-value pin markers only; never mutate an existing verdict."""
    if not isinstance(template,dict) or not isinstance(bindings,dict) or not isinstance(selections,dict):
        raise ValueError('case template, bindings and selection map are required')
    if len(json.dumps(template,allow_nan=False).encode())>256*1024:
        raise ValueError('case template exceeds bounded size')
    resolved={};pins={};count=0
    def visit(value):
        nonlocal count
        if isinstance(value,dict):return {key:visit(child) for key,child in value.items()}
        if isinstance(value,list):return [visit(child) for child in value]
        if not isinstance(value,str):return deepcopy(value)
        match=MARKER.fullmatch(value)
        if match:
            role,field=match.groups()
            if role not in resolved:
                if role not in bindings or role not in selections:
                    raise ValueError('missing prepared role for acceptance marker: '+role)
                manifest=validate_rebuilt(selections[role],bindings[role])
                resolved[role]={'manifest_sha256':bindings[role]['asset_binding']['manifest_sha256'],
                                'source_ref':manifest['source_ref']}
                pins[role]=dict(resolved[role],prepared_id=manifest['prepared_id'])
            count+=1
            return deepcopy(resolved[role][field])
        if '${' in value:raise ValueError('unsupported or incomplete case marker: '+value[:128])
        return value
    result=visit(template)
    if count==0:
        raise ValueError('new recipe case requires explicit binding markers; do not relabel an old frozen case')
    return {'case':result,'binding_pins':pins,'markers_resolved':count,'physical_verification':'not_run'}


def freeze_case_file(template_path,bindings_path,lock_path,output):
    template=json.loads(Path(template_path).read_text())
    bindings=json.loads(Path(bindings_path).read_text())
    lock=json.loads(Path(lock_path).read_text())
    result=freeze_case(template,bindings,lock['assets'])
    output=Path(output).expanduser().resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8') as stream:
        json.dump(result['case'],stream,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return {'case_path':str(output),'case_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'template_sha256':hashlib.sha256(Path(template_path).read_bytes()).hexdigest(),
            'binding_pins':result['binding_pins'],'physical_verification':'not_run'}
