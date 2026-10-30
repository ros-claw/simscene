"""Apply editable ordinary scene operations with separately acquired asset bindings."""
import argparse,json
from pathlib import Path
from simscene.scene import SceneStore
p=argparse.ArgumentParser();p.add_argument('recipe');p.add_argument('--scene-id',required=True);p.add_argument('--asset-catalog');p.add_argument('--save-directory',required=True)
a=p.parse_args();recipe=json.loads(Path(a.recipe).read_text());catalog=json.loads(Path(a.asset_catalog).read_text()) if a.asset_catalog else {}
def resolve(value):
 if isinstance(value,str) and value.startswith('asset://'):
  entry=catalog[value[8:]];return entry['root'] if isinstance(entry,dict) else entry
 if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
 if isinstance(value,list):return [resolve(v) for v in value]
 return value
store=SceneStore();scene=store.open(a.scene_id);operations=resolve(recipe['operations']);result=store.apply(a.scene_id,scene['revision'],'recipe-'+str(scene['revision']),operations)
root=Path(a.save_directory);root.mkdir(parents=True,exist_ok=True)
(root/'resolved-operations.json').write_text(json.dumps(operations,indent=2));(root/'scene.json').write_text(json.dumps(store.get(a.scene_id),indent=2))
print(json.dumps(result))
