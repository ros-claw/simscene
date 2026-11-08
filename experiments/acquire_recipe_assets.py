"""Rebuild selected closures and prepared roles through ordinary durable jobs.

Imports perform no network, runtime setup or model execution. Source-cache
capacity, scene transfer, per-asset transfer, unpacking and staging are separate.
"""
import argparse
import json
from pathlib import Path
import time
import uuid


class RecipeAcquireError(ValueError):
    def __init__(self,message,*,record=None):
        super().__init__(message);self.record=record


def wait_job(receipt,module,config,timeout):
    stop=time.monotonic()+timeout
    while True:
        record=module.status(receipt['job_id'],config=config)
        if record['state']=='completed':return record
        if record['state'] in ('failed','cancelled','uncertain'):
            raise RecipeAcquireError('durable recipe job did not complete: '+str(record.get('error',record['state'])),record=record)
        if time.monotonic()>=stop:
            module.cancel(receipt['job_id'],config=config)
            raise RecipeAcquireError('recipe job timeout; cancellation requested, final cost unknown',record=record)
        time.sleep(.2)


def _prepared(selection,config,limits,timeout,receipts):
    from simscene.catalog.models import AssetRecord
    from simscene.acquisition.plans import make_plan
    from simscene.preparation import jobs
    from simscene.recipes.io import validate_rebuilt
    ref=selection['source_ref'];record=None
    if 'generation' in selection:
        from simscene.generation import jobs as generation
        intent=selection['generation']
        if intent.get('generator')!='sand3d' or intent.get('seed')!=0:
            raise ValueError('unsupported generated recipe; only reviewed trusted Sand3D templates supported')
        # No programs from the lock are executable. jobs.start validates the one
        # shipped recipe and requires an explicitly configured reviewed runtime.
        receipt=generation.start(intent['recipe_id'],intent['parameters'],'recipe-generate-'+uuid.uuid4().hex,config=config)
        receipts.append(dict(receipt,role_phase='generation'))
        generated=wait_job(receipt,generation,config,timeout)
        ref=generated['result']['asset_ref']
    else:
        record=AssetRecord.from_dict(selection['source_record'])
        if record.ref.to_dict()!=ref:raise ValueError('portable source metadata differs from selection')
    plan=make_plan(ref,selection['profile_id'],selection['parameters'],selection['target'],limits,record=record,config=config)
    if not plan['ready_to_fetch']:raise RecipeAcquireError('recipe asset plan blocked: '+json.dumps(plan['blocking_reasons']))
    receipt=jobs.start(plan['plan_id'],'recipe-prepare-'+uuid.uuid4().hex,config=config)
    receipts.append(dict(receipt,role_phase='preparation'))
    completed=wait_job(receipt,jobs,config,timeout)
    result=completed['result']
    binding={'asset_path':result['root'],'asset_binding':{'manifest_path':result['manifest_path'],'manifest_sha256':result['manifest_sha256']}}
    # Account before validation: a changed downloaded source is still a cost.
    cost=completed.get('actual_download_bytes',result.get('actual_download_bytes'))
    if type(cost) is not int or cost<0:raise RecipeAcquireError('recipe transfer cost unknown',record=completed)
    try:validate_rebuilt(selection,binding)
    except ValueError as error:raise RecipeAcquireError(str(error),record=completed) from error
    return binding,cost


def acquire(lock,cache,*,max_bytes=4*1024**3,download_bytes=2*1024**3,asset_download_bytes=512*1024**2,
            unpacked_bytes=4*1024**3,staging_bytes=4*1024**3,wait_seconds=600,config=None,catalog_output=None):
    from simscene.acquisition.transfer import TransferBudget,transfer_scope
    if lock.get('schema') not in ('simscene.selected_assets.v1','simscene.selected_assets.v2'):
        raise ValueError('unsupported selected asset lock')
    for value in (max_bytes,download_bytes,asset_download_bytes,unpacked_bytes,staging_bytes,wait_seconds):
        if type(value) is not int or value<=0:raise ValueError('positive separate budgets and timeout required')
    catalog={};report={'actual_download_bytes':0,'download_bytes_known':True,'roles':[],'receipts':[],
        'cache_capacity_bytes':max_bytes,'scene_download_limit':download_bytes,'asset_download_limit':asset_download_bytes,
        'unpacked_limit':unpacked_bytes,'staging_limit':staging_bytes,'physical_verification':'not_run; freeze and evaluate a new case for rebuilt bindings'}
    def save():
        if catalog_output:
            target=Path(catalog_output);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(catalog,indent=2)+'\n')
            target.with_name(target.name+'.report.json').write_text(json.dumps(report,indent=2)+'\n')
    for role,selection in lock['assets'].items():
        remaining=download_bytes-report['actual_download_bytes']
        if remaining<=0:raise RecipeAcquireError('scene transfer budget exhausted')
        limits={'download_bytes':min(asset_download_bytes,remaining),'unpacked_bytes':unpacked_bytes,'staging_bytes':staging_bytes}
        transaction=None;role_cost=None;accounted=False
        try:
            if selection.get('provider')=='prepared':
                if config is None:
                    from simscene.catalog.config import read
                    config=read()
                configured=dict(config,asset_cache_directory=str(Path(cache).expanduser().resolve()),asset_cache_capacity_bytes=max_bytes)
                result,role_cost=_prepared(selection,configured,limits,wait_seconds,report['receipts'])
            else:
                from simscene.acquisition.dispatch import _BudgetUSDSearch
                from simscene.cache import AssetCache
                transaction=TransferBudget(**limits)
                with transfer_scope(transaction):
                    provider=selection.get('provider','usd-search')
                    if provider=='huggingface':
                        from simscene.huggingface_cache import acquire as hf_acquire
                        result=hf_acquire(selection['repository'],selection['revision'],selection['path'],cache,max_bytes)
                        if result['source']!=selection['source']:raise ValueError('selected source differs from HF identity: '+role)
                    elif provider=='usd-search':result=AssetCache(_BudgetUSDSearch(transaction),cache,max_bytes).acquire(selection['source'])
                    else:raise ValueError('unsupported selected-asset provider: '+str(provider))
                role_cost=transaction.actual_download_bytes
                expected={f['path']:(f.get('size_bytes',f.get('size')),f['sha256']) for f in selection['files']}
                actual={f['path']:(f.get('size_bytes',f.get('size')),f['sha256']) for f in result['files']}
                if actual!=expected:raise ValueError('selected source content changed: '+role)
                if result.get('unresolved_dependencies'):raise ValueError('unresolved selected dependencies: '+role)
                if selection.get('selected_member') is not None:
                    from simscene.recipes.io import resolve_member
                    result=resolve_member(selection,result,Path(cache)/result['package_sha256'])
            report['actual_download_bytes']+=role_cost;accounted=True
            report['roles'].append({'role':role,'state':'completed','actual_download_bytes':role_cost})
            catalog[role]=result;save()
        except Exception as error:
            if transaction is not None:role_cost=transaction.actual_download_bytes
            elif isinstance(error,RecipeAcquireError) and error.record:
                record=error.record;role_cost=record.get('actual_download_bytes',(record.get('result') or {}).get('actual_download_bytes'))
            if type(role_cost) is int and role_cost>=0:
                if not accounted:report['actual_download_bytes']+=role_cost
            else:role_cost=None;report['download_bytes_known']=False
            report['roles'].append({'role':role,'state':'failed','error':str(error),'actual_download_bytes':role_cost})
            save()
            failure=RecipeAcquireError('recipe role failed: '+role+': '+str(error),record=getattr(error,'record',None))
            failure.report=report;failure.catalog=catalog;raise failure from error
    save();return catalog


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('lock');p.add_argument('--cache',required=True);p.add_argument('--catalog-output',required=True)
    for key,default in [('max-bytes',4*1024**3),('download-bytes',2*1024**3),('asset-download-bytes',512*1024**2),('unpacked-bytes',4*1024**3),('staging-bytes',4*1024**3),('wait-seconds',600)]:
        p.add_argument('--'+key,type=int,default=default)
    a=p.parse_args(argv)
    try:catalog=acquire(json.loads(Path(a.lock).read_text()),a.cache,**{key:getattr(a,key) for key in ('max_bytes','download_bytes','asset_download_bytes','unpacked_bytes','staging_bytes','wait_seconds','catalog_output')})
    except RecipeAcquireError as error:
        print(json.dumps({'status':'failed','error':str(error),'report':getattr(error,'report',None)}));return 1
    print(json.dumps({'status':'completed','roles':list(catalog),'physical_verification':'not_run'}));return 0


if __name__=='__main__':raise SystemExit(main())
