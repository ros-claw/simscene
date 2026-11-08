"""Extend the gallery guide using a separately generated/prepared replacement.

This edits ordinary portable operations. It runs no physics, conversion or
network request and never copies a previous physical verdict.
"""
import argparse
import json
from pathlib import Path

from simscene.recipes.io import prepared_selection, portable
from simscene.physics_binding import validate_asset_binding

ROLE = 'chain_generated_guide'


def edit(base, completed, destination):
    base=Path(base);destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    recipe=json.loads((base/'recipe.json').read_text());lock=json.loads((base/'assets.lock.json').read_text())
    case=json.loads((base/'case.json').read_text())
    record=json.loads(Path(completed).read_text());result=record.get('result',record)
    manifest=validate_asset_binding({'manifest_path':result['manifest_path'],'manifest_sha256':result['manifest_sha256']},asset_path=result['root'])
    acquired=json.loads((Path(result['manifest_path']).parent/'source/acquired.json').read_text())
    selected=prepared_selection(manifest,acquired,manifest_sha256=result['manifest_sha256'])
    previous=lock['assets'][ROLE]
    if selected.get('generation',{}).get('recipe_id')!='guide_plate_v1' or selected['profile_id']!='static_fixture_v1':
        raise ValueError('a normally generated/prepared guide_plate_v1 static fixture is required')
    old=previous['generation']['parameters'];new=selected['generation']['parameters']
    if set(old)!=set(new) or any(old[k]!=new[k] for k in old if k!='length_m'):
        raise ValueError('this variant changes length only')
    delta=new['length_m']-old['length_m']
    if not 0<delta<=.3:raise ValueError('measured example permits an extension of at most 0.3 m; run a new case')
    objects={op['id']:op['object'] for op in recipe['operations'] if op.get('op')=='add'}
    q=objects[ROLE].get('orientation_wxyz',[1,0,0,0]);w,x,y,z=q
    if abs(sum(v*v for v in q)-1)>1e-6:raise ValueError('normalized guide orientation required')
    direction=[1-2*(y*y+z*z),2*(x*y+w*z),2*(x*z-w*y)]
    if abs(direction[2])>.15:raise ValueError('this measured guide recipe supports a shallow slope only')
    for name in (ROLE,'chain_guide_wall_1','chain_guide_wall_minus1'):
        obj=objects[name];obj['position']=[p+delta*.5*d for p,d in zip(obj['position'],direction)]
        if 'size' in obj:obj['size'][0]=new['length_m']
    translation=[delta*direction[0],delta*direction[1],0]
    for name,obj in objects.items():
        if name.startswith('chain_receiver'):
            obj['position']=[p+d for p,d in zip(obj['position'],translation)]
    for obj in objects.values():
        if obj.get('kind')=='camera' and 'camera_path' in obj:
            for point in obj['camera_path']:
                if obj is objects.get('chain_follow') and point['time_s']>=3.5:
                    for field in ('position','target'):
                        point[field]=[p+d for p,d in zip(point[field],translation)]
    def bounds(node):
        if isinstance(node,dict):
            if node.get('schema')=='simscene.handoff_chain.v1':
                for side in ('min','max'):
                    node['target_bounds'][side]=[p+d for p,d in zip(node['target_bounds'][side],translation)]
                for i,d in enumerate(translation):
                    node['trajectory_bounds']['max' if d>=0 else 'min'][i]+=d
            else:
                for value in node.values():bounds(value)
        elif isinstance(node,list):
            for value in node:bounds(value)
    bounds(case);lock['assets'][ROLE]=selected
    recipe.pop('source_run_id',None);recipe.pop('source_run_lock_sha256',None)
    recipe['description']='Length variant; separately freeze new case pins and run all physical checks.'
    ledger={'parameter':{'guide_length_m':{'before':old['length_m'],'after':new['length_m']}},
      'placement_rule':'hold guide entry fixed; translate centre/walls by half extension; translate receiver/supports horizontally by full extension',
      'other_mechanisms':'unchanged declared schedules and physical properties',
      'physical_verification':'not_run; previous verdict is not reused',
      'model_tokens':None,'token_note':'no per-edit provider usage is measured by this CPU compiler'}
    for value in (recipe,lock,case,ledger):portable(value)
    destination.mkdir(parents=True)
    for name,value in [('recipe.json',recipe),('assets.lock.json',lock),('case.json',case),('change-ledger.json',ledger)]:
        (destination/name).write_text(json.dumps(value,indent=2)+'\n')
    return {'directory':str(destination),'length_m':new['length_m'],'physical_verification':'not_run'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('base');parser.add_argument('completed_preparation');parser.add_argument('destination')
    args=parser.parse_args();print(json.dumps(edit(args.base,args.completed_preparation,args.destination)))
