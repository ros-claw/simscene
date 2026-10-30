"""Export lightweight ordinary operations and fixed selected-asset content locks.

Downloaded geometry stays local. Controller/model scenes need the full project
exporter; this lightweight format covers primitives and selected remote props.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import verify as outputs


def export(run, destination):
    run=Path(run).resolve();destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    if not inputs(run)['passed'] or not outputs(run)['passed']:raise ValueError('source run integrity failed')
    scene=json.loads((run/'spec.json').read_text());asset_lock=json.loads((run/'asset-lock.json').read_text())
    roles={};selected={};objects=copy.deepcopy(scene['objects'])
    for name,obj in objects.items():
        if obj.get('pose_follower'):raise ValueError('controller scenes need the full model/project exporter')
        if obj['kind']!='asset':continue
        entry=asset_lock[name]
        if entry['kind']!='snapshot':raise ValueError('authored local USD needs a separately published source or full project')
        source=entry['source']
        if source not in roles:
            role=name;roles[source]=role
            meta=json.loads((run/'assets'/entry['package_sha256']/'simscene-lock.json').read_text())
            if meta['source']!=source:raise ValueError('asset source mismatch')
            value={key:meta[key] for key in ('source','package_sha256','files','license','dependency_status') if key in meta}
            if meta.get('repository'):
                value.update(provider='huggingface',repository=meta['repository'],revision=meta['revision'],path=next(f['path'] for f in meta['files'] if f['url']==source))
            else:value['provider']='usd-search'
            selected[role]=value
        obj['asset_path']='asset://'+roles[source]
    operations=[{'op':'add','id':name,'object':obj} for name,obj in objects.items()]
    if scene.get('presentation'):operations.append({'op':'set_presentation','presentation':scene['presentation']})
    recipe={'description':'Editable ordinary operations exported after the independent scene-composition experiment; not supplied as an answer to that agent.','source_run_id':run.name,'source_run_lock_sha256':hashlib.sha256((run/'run-lock.json').read_bytes()).hexdigest(),'operations':operations}
    destination.mkdir(parents=True);(destination/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n');(destination/'assets.lock.json').write_text(json.dumps({'schema':'simscene.selected_assets.v1','assets':selected},indent=2)+'\n')
    print(json.dumps({'directory':str(destination),'objects':len(objects),'selected_sources':len(selected),'selected_bytes':sum(f['size'] for value in selected.values() for f in value['files'])}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('destination');a=p.parse_args();export(a.run,a.destination)
