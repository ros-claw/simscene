"""Apply ordinary editable operations with separately rebuilt pinned asset roles.

Preparation and applying a scene never reuse an old physical verdict. Freeze a
new acceptance case against the rebuilt bindings before each new physics run.
"""
import argparse
import json
from pathlib import Path


def apply(recipe,scene_id,catalog,save_directory,*,lock=None,store=None):
    from simscene.recipes.io import resolve_operations
    from simscene.scene import SceneStore
    if store is None:store=SceneStore()
    operations=resolve_operations(recipe,catalog,selections=lock['assets'] if lock else None)
    scene=store.open(scene_id)
    result=store.apply(scene_id,scene['revision'],'recipe-'+str(scene['revision']),operations)
    root=Path(save_directory);root.mkdir(parents=True,exist_ok=True)
    (root/'resolved-operations.json').write_text(json.dumps(operations,indent=2)+'\n')
    (root/'scene.json').write_text(json.dumps(store.get(scene_id),indent=2)+'\n')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('recipe');p.add_argument('--scene-id')
    p.add_argument('--asset-catalog');p.add_argument('--asset-lock');p.add_argument('--save-directory',required=True)
    p.add_argument('--operations-only',action='store_true',help='resolve ordinary operations without applying them')
    a=p.parse_args(argv)
    recipe=json.loads(Path(a.recipe).read_text())
    catalog=json.loads(Path(a.asset_catalog).read_text()) if a.asset_catalog else {}
    lock=json.loads(Path(a.asset_lock).read_text()) if a.asset_lock else None
    if a.operations_only:
        from simscene.recipes.io import resolve_operations
        operations=resolve_operations(recipe,catalog,selections=lock['assets'] if lock else None)
        root=Path(a.save_directory);root.mkdir(parents=True,exist_ok=True)
        output=root/'resolved-operations.json'
        with output.open('x',encoding='utf8') as stream:json.dump(operations,stream,indent=2);stream.write('\n')
        result={'operations_path':str(output),'operation_count':len(operations),'physical_verification':'not_run'}
    else:
        if not a.scene_id:p.error('--scene-id is required unless --operations-only is used')
        result=apply(recipe,a.scene_id,catalog,a.save_directory,lock=lock)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
