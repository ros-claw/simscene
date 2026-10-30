"""Rebuild a recipe's selected online assets and verify its pinned content lock."""
import argparse,json
from pathlib import Path
from simscene.assets import USDSearch
from simscene.cache import AssetCache
p=argparse.ArgumentParser();p.add_argument('lock');p.add_argument('--cache',required=True);p.add_argument('--catalog-output',required=True);p.add_argument('--max-bytes',type=int,default=4*1024**3)
a=p.parse_args();lock=json.load(open(a.lock));cache=AssetCache(USDSearch(),a.cache,a.max_bytes);catalog={}
for role,selection in lock['assets'].items():
 provider=selection.get('provider','usd-search')
 if provider=='huggingface':
  from simscene.huggingface_cache import acquire
  result=acquire(selection['repository'],selection['revision'],selection['path'],a.cache,a.max_bytes)
  if result['source']!=selection['source']:raise RuntimeError('selected source and pinned Hugging Face identity differ: '+role)
 elif provider=='usd-search':result=cache.acquire(selection['source'])
 else:raise ValueError('unsupported selected-asset provider: '+str(provider))
 expected={f['path']:(f['size'],f['sha256']) for f in selection['files']};actual={f['path']:(f['size'],f['sha256']) for f in result['files']}
 if actual!=expected:raise RuntimeError('selected source content changed: '+role)
 if result.get('unresolved_dependencies'):raise RuntimeError('unresolved selected dependencies: '+role)
 catalog[role]=result
 print(json.dumps({'role':role,'dependency_status':result['dependency_status'],'files':len(result['files'])}),flush=True)
Path(a.catalog_output).write_text(json.dumps(catalog,indent=2))
