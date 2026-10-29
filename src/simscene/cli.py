import argparse
import json
import sys
from pathlib import Path
from .assets import USDSearch, SearchError
from .scene import SceneError

def _load(path):
    path=Path(path)
    if path.suffix.lower() in ('.yaml','.yml'):
        import yaml
        try:
            with path.open(encoding='utf8') as file:return yaml.safe_load(file)
        except yaml.YAMLError as error:
            raise ValueError(f'invalid YAML: {error}') from error
    with path.open(encoding='utf8') as file:return json.load(file)

def _scene_spec(path):
    scene=_load(path)
    if not isinstance(scene,dict) or not isinstance(scene.get('objects'),dict):raise ValueError('scene spec must contain an objects mapping')
    world=scene.get('world',{})
    if not isinstance(world,dict) or world.get('units','m')!='m' or world.get('up_axis','Z')!='Z':
        raise ValueError('scene world must use metres and Z up')
    return scene

def main():
    parser = argparse.ArgumentParser(prog="simscene")
    parser.add_argument("--search-url")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("asset_url")
    acquire = commands.add_parser("acquire")
    acquire.add_argument("asset_url")
    acquire.add_argument("--cache")
    acquire.add_argument("--max-bytes", type=int)
    acquire.add_argument("--refresh", action="store_true")
    hf_search=commands.add_parser('hf-search');hf_search.add_argument('query');hf_search.add_argument('--limit',type=int,default=20)
    hf_list=commands.add_parser('hf-list');hf_list.add_argument('repo');hf_list.add_argument('revision');hf_list.add_argument('--limit',type=int,default=100);hf_list.add_argument('--cursor');hf_list.add_argument('--path',default='')
    hf_acquire=commands.add_parser('hf-acquire');hf_acquire.add_argument('repo');hf_acquire.add_argument('revision');hf_acquire.add_argument('path');hf_acquire.add_argument('--cache');hf_acquire.add_argument('--max-bytes',type=int)
    mcp = commands.add_parser("mcp")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--port", type=int, default=8765)
    local = commands.add_parser("inspect-local")
    local.add_argument("asset_path")
    profile=commands.add_parser('prepare-profile')
    profile.add_argument('model',choices=['kawasaki_rs007l_rg2','franka_panda','ur10_short_suction']);profile.add_argument('asset_path')
    commands.add_parser("doctor")
    configure=commands.add_parser('configure')
    configure.add_argument('--isaac-python');configure.add_argument('--data-directory');configure.add_argument('--cache-directory');configure.add_argument('--cache-bytes',type=int);configure.add_argument('--usd-search-url')
    build=commands.add_parser('build')
    build.add_argument('--spec',required=True);build.add_argument('--output',required=True)
    load=commands.add_parser('import-scene')
    load.add_argument('--spec',required=True);load.add_argument('--scene',required=True)
    run=commands.add_parser('run')
    run.add_argument('--scene',required=True,help='scene ID in SIMSCENE_HOME');run.add_argument('--steps',type=int,default=120);run.add_argument('--seed',type=int);run.add_argument('--case',help='snapshot and hash a JSON/YAML case')
    run.add_argument('--request-id',help='stable ID for retrying the same simulation request without launching a duplicate')
    run.add_argument('--continue-on-controller-error',action='store_true',help='continue physics after controller failure; task remains failed')
    run.add_argument('--archive-verified-objects',action='store_true',help='experimentally reclaim objects only after pinned per-item case checks')
    verify=commands.add_parser('verify')
    verify.add_argument('--run',required=True);verify.add_argument('--case',help='independent JSON/YAML case; defaults to a case snapshotted in a run directory')
    verify.add_argument('--type',choices=['contact','suction','moving','repeated','domino','parallel','stream'],help='case type; inferred for stream or parallel cases')
    verify.add_argument('--spec',help='saved run spec, required for parallel and stream cases')
    suite=commands.add_parser('verify-suite')
    suite.add_argument('--case',required=True);suite.add_argument('--run',required=True,action='append');suite.add_argument('--long-run',required=True)
    verify_lock=commands.add_parser('verify-lock');verify_lock.add_argument('--run',required=True,help='run directory')
    verify_evidence=commands.add_parser('verify-evidence');verify_evidence.add_argument('--run',required=True,help='run directory')
    args = parser.parse_args()
    if args.command == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main(transport=args.transport, port=args.port)
        return 0
    try:
        client = USDSearch(args.search_url)
        if args.command == "search":
            result = client.search(args.query, args.limit)
        elif args.command == "inspect":
            result = client.inspect(args.asset_url)
        elif args.command == "inspect-local":
            from .asset_inspect import inspect_local
            result = inspect_local(args.asset_path)
        elif args.command=='prepare-profile':
            from .robotics.profiles import prepare
            result=prepare(args.model,args.asset_path)
        elif args.command == "acquire":
            from .cache import AssetCache
            from .settings import get
            result = AssetCache(client,args.cache or get('cache_directory','~/.cache/simscene/assets'),args.max_bytes if args.max_bytes is not None else int(get('cache_bytes',2*1024**3))).acquire(args.asset_url, refresh=args.refresh)
        elif args.command=='hf-search':
            from .huggingface_assets import search_datasets
            result=search_datasets(args.query,args.limit)
        elif args.command=='hf-list':
            from .huggingface_assets import list_files
            result=list_files(args.repo,args.revision,args.limit,args.cursor,args.path)
        elif args.command=='hf-acquire':
            from .huggingface_cache import acquire
            from .settings import get
            result=acquire(args.repo,args.revision,args.path,args.cache or get('cache_directory','~/.cache/simscene/assets'),args.max_bytes if args.max_bytes is not None else int(get('cache_bytes',2*1024**3)))
        elif args.command=='configure':
            from .settings import update
            result=update({key:getattr(args,key) for key in ('isaac_python','data_directory','cache_directory','cache_bytes','usd_search_url') if getattr(args,key) is not None})
        elif args.command=='build':
            from .usd_export import export_scene
            scene=_scene_spec(args.spec)
            scene.setdefault('revision',0)
            result=export_scene(scene,args.output)
        elif args.command=='import-scene':
            from .scene import SceneStore
            scene=_scene_spec(args.spec)
            store=SceneStore();existing=store.open(args.scene)
            if existing['revision']!=0 or existing['objects']:raise SceneError('destination scene already contains edits')
            operations=[{'op':'add','id':name,'object':obj} for name,obj in scene['objects'].items()]
            result=store.apply(args.scene,0,'import',operations)
            result['scene_id']=args.scene
        elif args.command=='run':
            import time
            from .jobs import start,status,cancel
            job=start(args.scene,args.steps,args.seed,args.case,args.continue_on_controller_error,args.archive_verified_objects,request_id=args.request_id)
            try:
                while True:
                    result=status(job['job_id'])
                    if result['state'] not in ('queued','running','paused'):break
                    time.sleep(.5)
            except KeyboardInterrupt:
                cancel(job['job_id'])
                print('simulation cancellation requested',file=sys.stderr)
                return 130
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['state']=='completed' and result['result'].get('task_status')!='failed' else 1
        elif args.command=='verify':
            from .verification.case_runner import evaluate
            result=evaluate(args.run,args.case,args.type,args.spec)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['passed'] else 1
        elif args.command=='verify-lock':
            from .run_integrity import verify as verify_inputs
            result=verify_inputs(args.run)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['passed'] else 1
        elif args.command=='verify-suite':
            from .verification.acceptance import evaluate
            result=evaluate(args.run,args.long_run,args.case)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['passed'] else 1
        elif args.command=='verify-evidence':
            from .evidence_integrity import verify
            result=verify(args.run)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['passed'] else 1
        else:
            from .environment import probe
            result = probe()
            result["usd_search_url"] = client.base_url
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SearchError, SceneError, ValueError, OSError, KeyError, TypeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
