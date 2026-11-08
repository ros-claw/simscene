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
    catalog=commands.add_parser('catalog',help='bounded online metadata catalog')
    catalog.add_argument('action',choices=['sources','refresh','search','validate','build-list','discover','audit'])
    catalog.add_argument('query',nargs='?',default='');catalog.add_argument('--source',action='append')
    catalog.add_argument('--filters');catalog.add_argument('--limit',type=int,default=8);catalog.add_argument('--cursor');catalog.add_argument('--output')
    catalog.add_argument('--budget',help='discovery budget JSON file')
    recipe=commands.add_parser('recipe',help='compile editable role-based scene operations without running physics')
    recipe.add_argument('action',choices=['list','compile']);recipe.add_argument('identifier',nargs='?')
    recipe.add_argument('--parameters');recipe.add_argument('--bindings');recipe.add_argument('--scene');recipe.add_argument('--output')
    generation=commands.add_parser('generate',help='optional trusted Sand3D template jobs in an independent runtime')
    generation.add_argument('action',choices=['probe','start','status','cancel']);generation.add_argument('identifier',nargs='?')
    generation.add_argument('--python',dest='generation_python');generation.add_argument('--output');generation.add_argument('--parameters');generation.add_argument('--request-id')
    asset=commands.add_parser('asset',help='immutable plans and durable preparation jobs')
    asset.add_argument('action',choices=['plan','prepare','probe','status','cancel','setup-decoder'])
    asset.add_argument('identifier',nargs='?');asset.add_argument('--ref');asset.add_argument('--parameters')
    asset.add_argument('--profile',default='visual_prop_v1');asset.add_argument('--budget-bytes',type=int);asset.add_argument('--request-id')
    asset.add_argument('--output')
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
    mechanism=commands.add_parser('mechanism',help='compile/apply editable passive modules')
    mechanism.add_argument('action',choices=['compile','apply'])
    mechanism.add_argument('--definition');mechanism.add_argument('--output');mechanism.add_argument('--plan')
    mechanism.add_argument('--sha256');mechanism.add_argument('--scene');mechanism.add_argument('--base-revision',type=int)
    mechanism.add_argument('--request-id')
    diagnose=commands.add_parser('diagnose',help='compact first failed handoff from a retained report')
    diagnose.add_argument('--report',required=True);diagnose.add_argument('--case',required=True);diagnose.add_argument('--output',required=True)
    wait=commands.add_parser('wait',help='machine-side wait for an existing job; no restart')
    wait.add_argument('--job',required=True);wait.add_argument('--receipt',required=True);wait.add_argument('--timeout-s',type=float,default=1800)
    replay=commands.add_parser('replay',help='new camera renders from exact recorded rigid poses')
    replay.add_argument('action',choices=['prepare','render','status']);replay.add_argument('--run');replay.add_argument('--shots')
    replay.add_argument('--output');replay.add_argument('--request');replay.add_argument('--isaac-python');replay.add_argument('--wait',action='store_true')
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
    verify.add_argument('--type',choices=['contact','suction','moving','repeated','domino','parallel','stream','mechanism','passive_network','rigid_asset_smoke'],help='case type; inferred for passive, stream or parallel cases')
    verify.add_argument('--spec',help='saved run spec, required for parallel and stream cases')
    verify.add_argument('--mode',choices=['positive','detached_drawer','no_trigger','broken_rope','locked_door'],default='positive',help='read-only paired passive verification mode')
    verify.add_argument('--reference-run',help='matching completed positive run directory for a detached mechanism control')
    suite=commands.add_parser('verify-suite')
    suite.add_argument('--case',required=True);suite.add_argument('--run',required=True,action='append');suite.add_argument('--long-run',required=True)
    passive_suite=commands.add_parser('verify-passive-suite')
    passive_suite.add_argument('--positive-run',required=True);passive_suite.add_argument('--case')
    passive_suite.add_argument('--control',action='append',default=[],metavar='MODE=RUN',help='matching no_trigger, broken_rope or locked_door run directory')
    verify_lock=commands.add_parser('verify-lock');verify_lock.add_argument('--run',required=True,help='run directory')
    verify_evidence=commands.add_parser('verify-evidence');verify_evidence.add_argument('--run',required=True,help='run directory')
    args = parser.parse_args()
    if args.command == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main(transport=args.transport, port=args.port)
        return 0
    try:
        client = USDSearch(args.search_url)
        if args.command == 'catalog':
            from .catalog import service
            if args.action in ('sources','validate'):
                result=service.sources()
                if args.action=='validate':result={'valid':True,'source_count':len(result['sources']),'scope':'registry schema, not runtime acceptance'}
            elif args.action=='refresh':result=service.refresh(args.query)
            elif args.action=='discover':result=service.discover(args.query,_load(args.budget) if args.budget else None,args.cursor)
            elif args.action=='audit':
                from .catalog.audit import audit_source
                result=audit_source(_load(args.query)).to_dict()
            elif args.action=='build-list':
                if not args.output:raise ValueError('build-list requires --output')
                text=service.source_list()
                with Path(args.output).expanduser().open('x',encoding='utf8') as stream:stream.write(text)
                result={'output':str(Path(args.output).expanduser().resolve()),'scope':'curated registry; no network or runtime validation'}
            else:
                filters=_load(args.filters) if args.filters else {}
                if args.source:filters['source_ids']=args.source
                result=service.search(args.query,filters,args.limit,args.cursor)
        elif args.command=='generate':
            from .generation import jobs as generation_jobs
            if args.action=='probe':
                if not args.generation_python or not args.output:raise ValueError('probe requires --python and a new --output')
                from .generation.sand3d import probe_runtime
                result=probe_runtime(args.generation_python,args.output)
            elif args.action=='start':
                if not args.identifier:raise ValueError('start requires a registered template ID')
                result=generation_jobs.start(args.identifier,_load(args.parameters) if args.parameters else {},args.request_id)
            else:
                if not args.identifier:raise ValueError('status/cancel requires job ID')
                result=getattr(generation_jobs,args.action)(args.identifier)
        elif args.command=='recipe':
            if args.action=='list':
                from .recipes.registry import list_recipes
                result=list_recipes()
            else:
                if not all([args.identifier,args.parameters,args.bindings,args.scene,args.output]):
                    raise ValueError('compile requires identifier --parameters --bindings --scene --output')
                from .recipes.compile import compile_recipe
                result=compile_recipe(args.identifier,_load(args.parameters),_load(args.bindings),_load(args.scene))
                from .preparation.jobs import write
                write(args.output,result)
        elif args.command == 'asset':
            if args.action=='plan':
                if not args.ref:raise ValueError('plan requires --ref JSON file')
                from .acquisition.plans import make_plan
                result=make_plan(_load(args.ref),args.profile,_load(args.parameters) if args.parameters else None,
                                 budgets={'download_bytes':args.budget_bytes} if args.budget_bytes is not None else None)
            elif args.action=='setup-decoder':
                if not args.output:raise ValueError('setup-decoder requires a new --output directory')
                from .preparation.toolchain_setup import setup_predecoder
                result=setup_predecoder(args.output)
            elif args.action=='probe':
                from .preparation.environment import probe_runtime
                result=probe_runtime()
            else:
                from .preparation import jobs as prep_jobs
                if not args.identifier:raise ValueError('plan/job ID required')
                if args.action=='prepare':result=prep_jobs.start(args.identifier,args.request_id)
                else:result=getattr(prep_jobs,args.action)(args.identifier)
        elif args.command == 'mechanism':
            from .mechanism_modules import compile_plan,save_plan,apply_plan
            if args.action=='compile':
                if not args.definition or not args.output:raise ValueError('compile requires --definition and --output')
                definition=_load(args.definition)
                if set(definition)!={'kind','prefix','parameters'}:raise ValueError('definition requires exactly kind,prefix,parameters')
                result=save_plan(compile_plan(**definition),args.output)
            else:
                if not all([args.plan,args.sha256,args.scene,args.request_id]) or args.base_revision is None:raise ValueError('apply requires --plan --sha256 --scene --base-revision --request-id')
                result=apply_plan(args.scene,args.plan,args.sha256,args.base_revision,args.request_id)
        elif args.command=='replay':
            from . import replay
            if args.action=='prepare':
                if not all([args.run,args.shots,args.output]):raise ValueError('prepare requires --run --shots --output')
                result=replay.prepare(args.run,args.shots,args.output)
            elif args.action=='render':
                from .settings import get
                sdk=args.isaac_python or get('isaac_python')
                if not args.request or not sdk:raise ValueError('render requires --request and an Isaac launcher')
                result=replay.launch(args.request,sdk,not args.wait)
            else:
                if not args.request:raise ValueError('status requires --request')
                result=replay.status(args.request)
        elif args.command=='wait':
            from .workflows import wait_job
            result=wait_job(args.job,args.receipt,args.timeout_s)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['state']=='completed' and ((result['exit_code']==0 and result['exit_code_observed']) or result.get('completion_confirmed') is True) else 1
        elif args.command=='diagnose':
            from .diagnostics import write_diagnosis
            result=write_diagnosis(args.report,args.case,args.output)
        elif args.command == "search":
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
            if scene.get('observation'):operations.append({'op':'set_observation','observation':scene['observation']})
            if scene.get('presentation'):operations.append({'op':'set_presentation','presentation':scene['presentation']})
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
            result=evaluate(args.run,args.case,args.type,args.spec,mode=args.mode,reference_run=args.reference_run)
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
        elif args.command=='verify-passive-suite':
            from .verification.passive_network import MODES
            from .verification.case_runner import verify_passive_suite as verify_suite
            controls={}
            for value in args.control:
                mode,separator,directory=value.partition('=')
                if not separator or mode not in MODES[1:] or not directory or mode in controls:raise ValueError('controls require distinct MODE=RUN entries')
                controls[mode]=directory
            result=verify_suite(args.positive_run,controls,args.case)
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
