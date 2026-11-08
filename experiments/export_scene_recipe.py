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
    from simscene.recipes.io import prepared_selection,portable,SCHEMA,exported_member
    from simscene.physics_binding import validate_asset_binding
    roles={};selected={};has_prepared=False;has_member=False;objects=copy.deepcopy(scene['objects'])
    for name,obj in objects.items():
        if obj.get('pose_follower'):raise ValueError('controller scenes need the full model/project exporter')
        if obj['kind']!='asset':continue
        entry=asset_lock[name]
        if entry['kind']=='prepared_snapshot':
            binding=obj.get('asset_binding');manifest=validate_asset_binding(binding,asset_path=obj['asset_path'])
            expected=entry.get('manifest_sha256')
            if binding['manifest_sha256']!=expected:raise ValueError('prepared snapshot pin differs from scene')
            key=('prepared',expected)
            if key not in roles:
                role=name;roles[key]=role
                acquired_path=Path(binding['manifest_path']).parent/'source/acquired.json'
                acquired=json.loads(acquired_path.read_text())
                selected[role]=prepared_selection(manifest,acquired,manifest_sha256=expected)
            obj.pop('asset_path');obj.pop('asset_binding');obj['asset_role']=roles[key];has_prepared=True
            continue
        if entry['kind']!='snapshot':raise ValueError('authored local USD needs a separately published source or full project')
        source=entry['source']
        relative=Path(obj['asset_path']).absolute().relative_to(run/'assets')
        if len(relative.parts)<2:raise ValueError('selected legacy asset lacks a frozen package member')
        package=run/'assets'/relative.parts[0]
        meta=json.loads((package/'simscene-lock.json').read_text())
        if meta['source']!=source or meta.get('package_sha256')!=entry['package_sha256']:raise ValueError('asset source mismatch')
        member,selected_member=exported_member(package,meta,obj['asset_path'])
        key=('legacy',source,member)
        if key not in roles:
            role=name;roles[key]=role
            value={key:meta[key] for key in ('source','package_sha256','files','license','dependency_status') if key in meta}
            if meta.get('repository'):
                value.update(provider='huggingface',repository=meta['repository'],revision=meta['revision'],path=next(f['path'] for f in meta['files'] if f['url']==source))
            else:value['provider']='usd-search'
            if selected_member is not None:value['selected_member']=selected_member;has_member=True
            selected[role]=value
        obj['asset_path']='asset://'+roles[key]
    operations=[{'op':'add','id':name,'object':obj} for name,obj in objects.items()]
    if scene.get('presentation'):operations.append({'op':'set_presentation','presentation':scene['presentation']})
    if scene.get('observation'):operations.append({'op':'set_observation','observation':scene['observation']})
    recipe={'description':'Editable ordinary operations exported after the independent scene-composition experiment; not supplied as an answer to that agent.','source_run_id':run.name,'source_run_lock_sha256':hashlib.sha256((run/'run-lock.json').read_bytes()).hexdigest(),'operations':operations}
    if has_prepared or has_member:
        recipe['schema']='simscene.scene_recipe.v2'
        portable(recipe);portable(selected)
    destination.mkdir(parents=True);(destination/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n');(destination/'assets.lock.json').write_text(json.dumps({'schema':SCHEMA if has_prepared or has_member else 'simscene.selected_assets.v1','assets':selected},indent=2)+'\n')
    print(json.dumps({'directory':str(destination),'objects':len(objects),'selected_sources':len(selected),'selected_bytes':sum(f.get('size',f.get('size_bytes',0)) for value in selected.values() for f in value.get('files',value.get('source_files',[])))}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('destination');a=p.parse_args();export(a.run,a.destination)
