"""Launch experimental Isaac jobs in a separate process."""
import json
import hashlib
import shutil
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .scene import SceneStore, SceneError
from .usd_export import export_scene

# Download futures live only in this process. Simulation workers record enough
# identity to reconnect without mistaking a reused PID for the original job.
_jobs = {}
_downloads = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="simscene-download")

def _process_identity(pid):
    try:
        if type(pid) is not int or pid<=0:return None
        proc=Path('/proc')/str(pid)
        if proc.stat().st_uid!=os.getuid():return None
        raw=(proc/'stat').read_text();fields=raw[raw.rfind(')')+2:].split()
        if fields[0] in ('Z','X'):return None
        return {'start_ticks':int(fields[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError,ValueError,IndexError):return None

def _recorded_exit(directory,pid):
    try:
        record=json.loads((directory/'process-exit.json').read_text());code=record.get('exit_code')
        if (record.get('schema')=='simscene.process_exit.v1' and record.get('run_id')==directory.name
                and type(record.get('queue_pid')) is int and record['queue_pid']==pid
                and type(code) is int and -255<=code<=255):
            return code
    except (OSError,ValueError,TypeError):pass
    return None

class _RecoveredProcess:
    def __init__(self,pid,identity,directory):
        self.pid=pid;self.identity=identity;self.directory=directory
        self.exit_code_recorded=False
    def poll(self):
        if self.identity and _process_identity(self.pid)==self.identity:return None
        self.exit_code_recorded=False
        code=_recorded_exit(self.directory,self.pid)
        if code is not None:
            self.exit_code_recorded=True
            return code
        # Older jobs do not have a durable exit code; retain a clearly marked
        # inference for compatibility rather than claiming it was observed.
        try:
            result=json.loads((self.directory/'result.json').read_text())
            return 0 if isinstance(result,dict) else -1
        except (OSError,ValueError):return -1

def _job(job_id):
    if job_id in _jobs:return _jobs[job_id]
    if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):
        raise SceneError('job not found')
    root=SceneStore().path/'runs'
    if root.is_dir():
        for metadata in root.glob('*/job.json'):
            try:
                directory=metadata.parent
                if directory.is_symlink() or directory.resolve().parent!=root.resolve():continue
                info=json.loads(metadata.read_text());lock=json.loads((directory/'run-lock.json').read_text())
                if info['job_id']!=job_id or lock['job_id']!=job_id or info['run_id']!=directory.name or lock['run_id']!=directory.name:continue
                process=_RecoveredProcess(info['pid'],info.get('identity'),directory)
                job={'process':process,'directory':directory,'revision':lock['scene_revision'],'run_id':directory.name,'recovered':True}
                _jobs[job_id]=job
                return job
            except (OSError,KeyError,TypeError,ValueError):continue
    raise SceneError('job not found')

def _lock_external_asset(path):
    """Hash the local USD dependency set without claiming it is copied."""
    from .cache import _sha256
    try:
        from pxr import UsdUtils
        layers,assets,unresolved=UsdUtils.ComputeAllDependencies(str(path))
    except ImportError as error:
        raise SceneError('USD Python bindings required to lock external assets') from error
    except RuntimeError as error:
        raise SceneError(f'cannot inspect asset dependencies: {path}: {error}') from error
    paths={path.resolve()}
    for layer in layers:
        value=getattr(layer,'realPath','')
        if value and Path(value).is_file():paths.add(Path(value).resolve())
    for asset in assets:
        value=str(asset)
        if value and Path(value).is_file():paths.add(Path(value).resolve())
    files=[{'path':str(file),'size':file.stat().st_size,'sha256':_sha256(file)} for file in sorted(paths)]
    from .runtime_dependencies import classify
    deps=classify(unresolved)
    return {'kind':'external','path':str(path),'files':files,'unresolved_dependencies':deps['unresolved'],
            'runtime_provided_dependencies':deps['runtime_provided'],
            'runtime_dependency_sha256':{name:_sha256(Path(filename)) for name,filename in deps['runtime_provided'].items()}, 'license':'unknown'}

def _snapshot_cached_assets(scene, run):
    """Copy verified cache packages into a run while holding the cache lock.

    Other local assets remain external references; their presence here is not
    evidence that a run is portable. Package copies are immutable run records,
    not cache entries and therefore do not count against the cache limit.
    """
    import fcntl
    import re
    from .cache import AssetCache,_sha256
    snapshots = {}
    records = {}
    for name, obj in scene['objects'].items():
        if obj.get('kind') != 'asset': continue
        if obj.get('asset_binding'):
            from .physics_binding import validate_asset_binding
            if not Path(obj['asset_binding']['manifest_path']).expanduser().is_file():
                from .cache_restore import restore_prepared_reference
                restored=restore_prepared_reference(obj['asset_binding'],obj['asset_path'],home=SceneStore().path)
                obj.update(restored)
            binding=obj['asset_binding']; original=Path(binding['manifest_path']).expanduser().resolve()
            package=original.parent; key='prepared:'+str(package)
            # The same lock protects prepared-cache eviction and publication.
            with (package.parent/'.prepared.lock').open('a') as lockfile:
                fcntl.flock(lockfile,fcntl.LOCK_EX)
                metadata=validate_asset_binding(binding,require_dynamic=obj.get('dynamic',False),asset_path=obj['asset_path'])
                if key not in snapshots:
                    target=run/'assets'/('prepared-'+binding['manifest_sha256'])
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copytree(package,target)
                    snapshots[key]=target
                target=snapshots[key]
                relocated={'manifest_path':str(target/'manifest.json'),'manifest_sha256':binding['manifest_sha256']}
                validate_asset_binding(relocated,require_dynamic=obj.get('dynamic',False),asset_path=str(target/metadata['main']))
            obj['asset_path']=str(target/metadata['main']);obj['asset_binding']=relocated
            records[name]={'kind':'prepared_snapshot','prepared_id':metadata['prepared_id'],
                           'root_relative_to_run':str((target/metadata['main']).relative_to(run)),
                           'manifest_relative_to_run':str((target/'manifest.json').relative_to(run)),
                           'manifest_sha256':relocated['manifest_sha256'],'source_ref':metadata.get('source_ref'),
                           'license':metadata.get('license'),'runtime_dependencies':metadata.get('runtime_dependencies',[])}
            from .preparation.snapshots import pin_prepared_runtime
            from .settings import get
            records[name].update(pin_prepared_runtime(target,metadata,get('isaac_python')))
            continue
        path = Path(obj['asset_path']).expanduser().resolve()
        if not path.is_file():
            from .cache_restore import restore_reference
            from .assets import SearchError
            try:path=restore_reference(path)
            except SearchError as error:raise SceneError(f'cannot restore cached asset {name}: {error}') from error
            obj['asset_path']=str(path)
        package = next((p for p in path.parents if re.fullmatch(r'[0-9a-f]{64}', p.name) and (p/'simscene-lock.json').is_file()), None)
        if package is None:
            if not path.is_file():raise SceneError(f'asset path does not exist: {name}')
            records[name] = _lock_external_asset(path)
            continue
        relative = path.relative_to(package)
        cache_dir = package.parent
        key = str(package)
        with (cache_dir/'.cache.lock').open('a') as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            if key not in snapshots:
                try:
                    metadata = json.loads((package/'simscene-lock.json').read_text())
                    source = metadata['source']
                    # The client is not used for a local integrity check.
                    verified=AssetCache(None, cache_dir)._verified_cached(package, package.name, source)
                    target = run/'assets'/package.name
                    if target.exists():
                        # Separate caches can hold different repaired
                        # dependencies under the same downloaded archive hash.
                        suffix=1
                        while (run/'assets'/f'{package.name}-{suffix}').exists():suffix+=1
                        target=run/'assets'/f'{package.name}-{suffix}'
                    target.mkdir(parents=True)
                    for item in metadata['files']:
                        relative_file = Path(item['path'])
                        destination = target/relative_file
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(package/relative_file, destination)
                    (target/'simscene-lock.json').write_text(json.dumps(metadata, indent=2))
                    AssetCache(None, target.parent)._verified_cached(target, package.name, source)
                except (OSError, ValueError, KeyError) as error:
                    raise SceneError(f'cannot snapshot cached asset {name}: {error}') from error
                snapshots[key] = (target, metadata, verified)
            target, metadata, verified = snapshots[key]
            if relative.as_posix() not in {item['path'] for item in metadata['files']}:
                raise SceneError(f'cached asset is not covered by its integrity lock: {name}')
            resolved = target/relative
            if not resolved.is_file(): raise SceneError(f'cached asset is missing: {name}')
            obj['asset_path'] = str(resolved)
            records[name] = {'kind':'snapshot', 'source':metadata['source'], 'package_sha256':package.name,
                             'root_relative_to_run':str(resolved.relative_to(run)), 'dependency_status':verified.get('dependency_status'),
                             'license':metadata.get('license','unknown'),
                             'runtime_provided_dependencies':verified.get('runtime_provided_dependencies',{}),
                             'runtime_dependency_sha256':{key:_sha256(Path(value)) for key,value in verified.get('runtime_provided_dependencies',{}).items()}}
            from .snapshot_integrity import pin_snapshot
            from .settings import get
            try:
                records[name].update(pin_snapshot(target, get('isaac_python'), records[name]['runtime_provided_dependencies']))
            except (OSError, ValueError, KeyError) as error:
                raise SceneError(f'cannot pin complete cached asset closure {name}: {error}') from error
    return records

def _recover_job_request(root,request_id,digest):
    """Find an already launched request; None means the outcome is uncertain."""
    runs=Path(root)/'runs'
    if not runs.exists():return False
    found=[]
    try:
        for lockfile in runs.glob('*/run-lock.json'):
            if lockfile.parent.is_symlink() or lockfile.parent.resolve().parent!=runs.resolve():continue
            lock=json.loads(lockfile.read_text())
            if lock.get('request_id')!=request_id:continue
            if lock.get('request_payload_sha256')!=digest:return None
            info=json.loads((lockfile.parent/'job.json').read_text())
            if (info.get('job_id')!=lock.get('job_id') or info.get('run_id')!=lock.get('run_id')
                    or info.get('run_id')!=lockfile.parent.name):return None
            found.append({'job_id':info['job_id'],'run_id':info['run_id'],'revision':lock['scene_revision']})
    except (OSError,ValueError,KeyError,TypeError):return None
    return found[0] if len(found)==1 else (False if not found else None)

def start(scene_id, steps=120, seed=None, case_path=None, continue_on_controller_error=False, archive_verified_objects=False, case=None, request_id=None):
    if request_id is None:
        return _start(scene_id,steps,seed,case_path,continue_on_controller_error,archive_verified_objects,case)
    if case_path is not None and case is not None:
        raise SceneError('supply either case_path or an inline case, not both')
    expected_case_sha=None
    if case_path is not None:
        if not isinstance(case_path,str) or not case_path:raise SceneError('case_path must name a local JSON or YAML file')
        path=Path(case_path).expanduser().resolve()
        if path.suffix.lower() not in ('.json','.yaml','.yml') or not path.is_file():raise SceneError('case_path must name a local JSON or YAML file')
        with path.open('rb') as stream:data=stream.read(5*1024*1024+1)
        if len(data)>5*1024*1024:raise SceneError('acceptance case exceeds 5 MiB')
        expected_case_sha=hashlib.sha256(data).hexdigest();case_path=str(path)
    if case is not None:
        try:
            serialized=json.dumps(case,sort_keys=True,separators=(',',':'),allow_nan=False)
            if len(serialized.encode('utf-8'))>5*1024*1024:raise SceneError('acceptance case exceeds 5 MiB')
            case=json.loads(serialized)
        except (ValueError,TypeError,OverflowError,RecursionError) as error:raise SceneError(f'invalid inline case: {error}') from error
    payload={'scene_id':scene_id,'steps':steps,'seed':seed,'case_path':case_path,'case_path_sha256':expected_case_sha,
             'case':case,'continue_on_controller_error':continue_on_controller_error,'archive_verified_objects':archive_verified_objects}
    from .request_registry import invoke
    root=SceneStore().path
    return invoke(root,request_id,payload,
                  lambda name,digest:_start(scene_id,steps,seed,case_path,continue_on_controller_error,archive_verified_objects,case,
                                            request_identity=(name,digest),expected_case_sha=expected_case_sha),
                  lambda name,digest:_recover_job_request(root,name,digest))

def _start(scene_id, steps=120, seed=None, case_path=None, continue_on_controller_error=False, archive_verified_objects=False, case=None, request_identity=None, expected_case_sha=None):
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 72000:
        raise SceneError('steps must be between 1 and 72000')
    if seed is not None and (type(seed) is not int or not 0<=seed<2**32):
        raise SceneError('seed must be an integer from 0 through 2^32-1')
    if type(continue_on_controller_error) is not bool:raise SceneError('continue_on_controller_error must be boolean')
    if type(archive_verified_objects) is not bool:raise SceneError('archive_verified_objects must be boolean')
    physics_device=os.getenv('SIMSCENE_PHYSICS_DEVICE','cpu').lower()
    if physics_device not in ('default','cpu','gpu'):
        raise SceneError('SIMSCENE_PHYSICS_DEVICE must be default, cpu, or gpu')
    case_snapshot=None
    if case_path is not None and case is not None:
        raise SceneError('supply either case_path or an inline case, not both')
    if case is not None:
        if not isinstance(case,dict):raise SceneError('inline case must be a mapping')
        try:
            data=json.dumps(case,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
            parsed=json.loads(data)
        except (ValueError,TypeError,OverflowError,RecursionError) as error:
            raise SceneError(f'invalid inline case: {error}') from error
        if len(data)>5*1024*1024:raise SceneError('acceptance case exceeds 5 MiB')
        case_snapshot=(data,'.json')
    if case_path is not None:
        if not isinstance(case_path,str) or not case_path:raise SceneError('case_path must name a local JSON or YAML file')
        path=Path(case_path).expanduser()
        if path.suffix.lower() not in ('.json','.yaml','.yml') or not path.is_file():raise SceneError('case_path must name a local JSON or YAML file')
        with path.open('rb') as f:data=f.read(5*1024*1024+1)
        if len(data)>5*1024*1024:raise SceneError('acceptance case exceeds 5 MiB')
        if expected_case_sha is not None and hashlib.sha256(data).hexdigest()!=expected_case_sha:
            raise SceneError('case file changed while the job request was being prepared')
        try:
            if path.suffix.lower()=='.json':parsed=json.loads(data)
            else:
                import yaml
                parsed=yaml.safe_load(data)
        except Exception as error:raise SceneError(f'invalid acceptance case: {error}') from error
        if not isinstance(parsed,dict):raise SceneError('acceptance case must be a mapping')
        case_snapshot=(data,path.suffix.lower())
    from .settings import get
    executable = get('isaac_python')
    if not executable or not Path(executable).is_file():
        raise SceneError('set SIMSCENE_ISAAC_PYTHON to the Isaac Sim python.sh path')
    scene = SceneStore().get(scene_id)
    if case_snapshot and parsed.get('schema') in ('simscene.articulated_asset_smoke.v1','simscene.container_asset_smoke.v1','simscene.asset_gallery.v1','simscene.handoff_chain.v1'):
        from importlib import import_module
        module={'simscene.articulated_asset_smoke.v1':'articulated_asset_smoke','simscene.container_asset_smoke.v1':'container_asset_smoke','simscene.asset_gallery.v1':'asset_gallery','simscene.handoff_chain.v1':'handoff_chain'}[parsed['schema']]
        try:
            checker=import_module('.verification.'+module,__package__)
            checker.validate_case(parsed)
            if module=='handoff_chain':checker.verify_selection(scene,parsed)
        except (ValueError,TypeError,KeyError) as error:raise SceneError(str(error)) from error
    if case_snapshot:
        from .verification.collision_preflight import validate as validate_collision_case
        try:validate_collision_case(scene,parsed)
        except (ValueError,TypeError,KeyError) as error:raise SceneError(str(error)) from error
    if archive_verified_objects:
        if not case_snapshot:raise SceneError('archiving verified objects requires a pinned stream case')
        from .verification.archive_candidate import validate_case
        try:validate_case(scene,parsed)
        except (ValueError,TypeError,KeyError) as error:raise SceneError(str(error)) from error
    source_hash=hashlib.sha256(json.dumps(scene,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if case_snapshot and 'source_scene_sha256' in parsed and parsed['source_scene_sha256']!=source_hash:
        raise SceneError('case was prepared for a different scene revision or content')
    run_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    run = (SceneStore().path / 'runs' / run_id).resolve()
    run.mkdir(parents=True)
    asset_lock = _snapshot_cached_assets(scene, run)
    (run/'asset-lock.json').write_text(json.dumps(asset_lock, indent=2))
    # Freeze the control files used by this run; asset packages still require
    # separate pinning and are deliberately not claimed to be self-contained.
    runtime_lock = {}
    for name,obj in scene['objects'].items():
        config=obj.get('pose_follower')
        if not config: continue
        source=Path(config['model_directory']).expanduser().resolve()
        target=run/'models'/name
        target.mkdir(parents=True)
        hashes={}
        for filename in ('robot.urdf','robot.xrdf','rmp_flow.yaml'):
            file=source/filename
            if not file.is_file(): raise SceneError(f'missing robot control file: {file}')
            copy=target/filename
            shutil.copyfile(file,copy)
            hashes[filename]=hashlib.sha256(copy.read_bytes()).hexdigest()
        # cuMotion requires the damping region not to exceed its velocity cap.
        # Reject impossible phase limits before launching a long physical run.
        import yaml
        rmp=yaml.safe_load((target/'rmp_flow.yaml').read_text())
        params=rmp.get('rmp_params',{}) if isinstance(rmp,dict) else {}
        velocity=params.get('joint_velocity_cap_rmp',{}) if isinstance(params,dict) else {}
        damping=velocity.get('velocity_damping_region') if isinstance(velocity,dict) else None
        limits=[config.get('max_joint_speed')]+[phase.get('rmp_max_joint_speed') for phase in config.get('sequence',[]) if isinstance(phase,dict)]
        if isinstance(damping,(int,float)) and not isinstance(damping,bool):
            for limit in limits:
                if limit is not None and limit<damping:
                    raise SceneError(f'{name}: RMPflow velocity cap {limit} is below its damping region {damping}')
        original_gripper=Path(config.get('gripper_urdf','')).expanduser().resolve() if config.get('gripper_urdf') else None
        if original_gripper == source/'robot.urdf': config['gripper_urdf']=str(target/'robot.urdf')
        elif original_gripper:
            if not original_gripper.is_file(): raise SceneError('gripper URDF not found')
            shutil.copyfile(original_gripper,target/'gripper.urdf')
            hashes['gripper.urdf']=hashlib.sha256((target/'gripper.urdf').read_bytes()).hexdigest()
            config['gripper_urdf']=str(target/'gripper.urdf')
        config['model_directory']=str(target)
        runtime_lock[name]={'source':str(source),'files_sha256':hashes}
    (run/'runtime-lock.json').write_text(json.dumps(runtime_lock,indent=2))
    # The worker imports shared SimScene modules at runtime. Snapshot the
    # complete package so a later checkout or plugin update cannot change a
    # running job or silently change its recorded implementation.
    worker_package=run/'runtime'/'simscene'
    shutil.copytree(Path(__file__).parent,worker_package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    worker_hashes={str(path.relative_to(worker_package)):hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in worker_package.rglob('*') if path.is_file()}
    if case_snapshot:
        case_name='acceptance-case'+case_snapshot[1]
        (run/case_name).write_bytes(case_snapshot[0])
    stage = run / 'scene.usda'
    exported=export_scene(scene, stage)
    (run / 'spec.json').write_text(json.dumps(scene, indent=2))
    from datetime import datetime,timezone
    runtime=Path(executable).expanduser().resolve()
    queue_python=Path(sys.executable).expanduser().resolve()
    version=runtime.parent/'VERSION'
    manifest={'run_id':run_id,'job_id':job_id,'scene_id':scene_id,'scene_revision':scene['revision'],'source_scene_sha256':source_hash,
              'spec_sha256':hashlib.sha256((run/'spec.json').read_bytes()).hexdigest(),
              'stage_sha256':hashlib.sha256(stage.read_bytes()).hexdigest(),
              'asset_lock_sha256':hashlib.sha256((run/'asset-lock.json').read_bytes()).hexdigest(),
              'runtime_lock_sha256':hashlib.sha256((run/'runtime-lock.json').read_bytes()).hexdigest(),
              'worker_code_sha256':worker_hashes,
              'runtime_python':str(runtime),'runtime_python_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
              'queue_launcher_python':str(queue_python),'queue_launcher_python_sha256':hashlib.sha256(queue_python.read_bytes()).hexdigest(),
              'gpu_queue_policy':'one active simulator per user on this host',
              'runtime_version':version.read_text().strip() if version.is_file() else None,
              'asset_normalizations':exported.get('normalized_visual_assets',{}) if isinstance(exported,dict) else {},
              'gpu_selection':{'simscene_gpu':os.getenv('SIMSCENE_GPU','0'),'cuda_visible_devices':os.getenv('CUDA_VISIBLE_DEVICES')},
              'physics_dt_s':1/60,'physics_device':physics_device,'continue_on_controller_error':continue_on_controller_error,'archive_verified_objects':archive_verified_objects,'requested_physics_steps':steps,'seed':seed,'created_at_utc':datetime.now(timezone.utc).isoformat()}
    if isinstance(exported,dict) and exported.get('body_bindings'):
        manifest['body_bindings']=exported['body_bindings']
    if case_snapshot:
        manifest['acceptance_case_file']=case_name
        manifest['acceptance_case_sha256']=hashlib.sha256(case_snapshot[0]).hexdigest()
    if request_identity:
        manifest['request_id'],manifest['request_payload_sha256']=request_identity
    SceneStore()._write(run/'run-lock.json',manifest)
    # Persist the reservation before the worker can be launched. After a
    # crash, an incomplete run can then be recognized without a duplicate.
    for directory in (run,run.parent,run.parent.parent):
        descriptor=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    script = worker_package / 'worker' / 'isaac_run.py'
    queue_script = worker_package / 'worker' / 'gpu_queue.py'
    queue_state = run / 'gpu-queue.json'
    SceneStore()._write(queue_state,{'state':'queued'})
    with (run / 'worker.log').open('wb') as log:
        command=[str(queue_python),str(queue_script),str(queue_state),executable,str(script),str(stage),str(run / 'result.json'), '--steps', str(steps), '--spec', str(run / 'spec.json'), '--physics-device',physics_device]
        if seed is not None:command.extend(['--seed',str(seed)])
        if continue_on_controller_error:command.append('--continue-on-controller-error')
        if archive_verified_objects:command.extend(['--archive-case',str(run/case_name)])
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    metadata={'job_id':job_id,'run_id':run_id,'pid':process.pid,'identity':_process_identity(process.pid)}
    try:
        SceneStore()._write(run/'job.json',metadata)
        descriptor=os.open(run,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    except Exception:
        import signal
        if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
        raise
    _jobs[job_id] = {'process':process, 'directory':run, 'revision':scene['revision'],'run_id':run_id}
    return {'job_id':job_id, 'run_id':run_id, 'revision':scene['revision']}

def acquire_start(asset_url, refresh=False):
    from .assets import USDSearch
    from .cache import AssetCache
    from .settings import get
    cache_dir = get('cache_directory','~/.cache/simscene/assets')
    capacity = int(get('cache_bytes',2 * 1024**3))
    job_id = uuid.uuid4().hex
    future = _pool.submit(AssetCache(USDSearch(timeout=300), cache_dir, capacity).acquire, asset_url, refresh)
    _downloads[job_id] = future
    return {'job_id':job_id}

def huggingface_acquire_start(repo_id, revision, path):
    from .huggingface_cache import acquire
    from .settings import get
    cache_dir=get('cache_directory','~/.cache/simscene/assets')
    capacity=int(get('cache_bytes',2*1024**3))
    job_id=uuid.uuid4().hex
    _downloads[job_id]=_pool.submit(acquire,repo_id,revision,path,cache_dir,capacity)
    return {'job_id':job_id}

def robot_profile_start(model, asset_path):
    from .robotics.profiles import prepare
    job_id=uuid.uuid4().hex
    _downloads[job_id]=_pool.submit(prepare,model,asset_path)
    return {'job_id':job_id}

def status(job_id):
    from .generation import jobs as generation_jobs
    if generation_jobs.owns(job_id):return generation_jobs.status(job_id)
    from .preparation import jobs as preparation_jobs
    if preparation_jobs.owns(job_id):return preparation_jobs.status(job_id)
    future = _downloads.get(job_id)
    if future is not None:
        if future.cancelled(): return {'job_id':job_id, 'state':'cancelled'}
        if not future.done(): return {'job_id':job_id, 'state':'running' if future.running() else 'queued'}
        try:
            return {'job_id':job_id, 'state':'completed', 'result':future.result()}
        except Exception as error:
            return {'job_id':job_id, 'state':'failed', 'error':str(error)}
    job = _job(job_id)
    code = job['process'].poll()
    if code is not None and not job.get('recovered'):
        recorded=_recorded_exit(job['directory'],job['process'].pid)
        if recorded is not None:code=recorded
    result_path = job['directory'] / 'result.json'
    state = 'running' if code is None else ('completed' if code == 0 and result_path.is_file() else 'failed')
    result = None
    failure_reason = None
    if state == 'completed':
        try:
            result = json.loads(result_path.read_text())
            if not isinstance(result, dict):
                raise ValueError('result is not an object')
            requested = result.get('requested_physics_steps')
            actual = result.get('actual_physics_steps')
            lock_path = job['directory'] / 'run-lock.json'
            locked_steps = None
            if lock_path.is_file():
                run_lock = json.loads(lock_path.read_text())
                if not isinstance(run_lock, dict):raise ValueError('run lock is not an object')
                locked_steps = run_lock.get('requested_physics_steps')
            if locked_steps is not None and (type(locked_steps) is not int or requested != locked_steps):
                state = 'failed'
                failure_reason = f'result requested {requested} physics steps, but the run locked {locked_steps}'
            elif requested is not None and (type(requested) is not int or type(actual) is not int or actual != requested):
                state = 'failed'
                failure_reason = f'simulation stopped after {actual} of {requested} requested physics steps'
        except (OSError,ValueError,TypeError) as error:
            state = 'failed'
            result = None
            failure_reason = f'cannot read simulation result: {error}'
    if state=='running':
        try:
            if json.loads((job['directory']/'gpu-queue.json').read_text()).get('state')=='queued':state='queued'
        except (OSError,ValueError,TypeError):pass
    cancel_requested=(job['directory']/'cancel-request.json').is_file()
    if state=='failed' and cancel_requested:state='cancelled'
    control_path=job['directory']/'control-state.json'
    if state in ('running','queued') and control_path.is_file():
        control=json.loads(control_path.read_text())
        if control.get('state')=='paused':state='paused'
    if result is not None:
        samples = result.pop('samples', [])
        result['sample_count'] = len(samples)
        for field in ('contact_counts','robot_contacts','overlap_counts'):
            if isinstance(result.get(field),dict):
                entries=result[field]
                result[field+'_total']=len(entries)
                result[field+'_excerpted']=len(entries)>100
                if len(entries)>100:result[field]=dict(list(entries.items())[:100])
    partial_path=job['directory']/'partial-result.json'
    progress=None;last_observation_utc=None
    live=job['directory']/'latest-observation.json'
    try:
        from datetime import datetime,timezone
        observation=json.loads(live.read_text())
        last_observation_utc=datetime.fromtimestamp(live.stat().st_mtime,timezone.utc).isoformat()
        total=json.loads((job['directory']/'run-lock.json').read_text()).get('requested_physics_steps')
        progress={'physics_steps':observation.get('physics_steps'),'requested_physics_steps':total,
                  'simulation_time_s':observation.get('simulation_time_s')}
    except (OSError,ValueError,TypeError):pass
    stalled_reason=None
    if state=='running':
        try:
            heartbeat=live if live.is_file() else (job['directory']/'gpu-queue.json')
            if not heartbeat.is_file():heartbeat=job['directory']/'job.json'
            age=time.time()-heartbeat.stat().st_mtime
            if age>300:
                state='stalled';stalled_reason=f'worker is alive but has produced no observation for {int(age)} seconds'
        except OSError:pass
    return {'job_id':job_id, 'run_id':job.get('run_id'), 'state':state, 'exit_code':code, 'exit_code_inferred':bool(job.get('recovered') and code is not None and not getattr(job['process'],'exit_code_recorded',False)), 'cancel_requested':cancel_requested, 'revision':job['revision'], 'result':result,
            'progress':progress,'last_observation_utc':last_observation_utc,
            'stalled_reason':stalled_reason,'failure_reason':failure_reason,
            'result_file':str(result_path) if result is not None else None,
            'partial_result_file':str(partial_path) if state in ('failed','cancelled') and partial_path.is_file() else None,
            'log':str(job['directory'] / 'worker.log')}

def sample(job_id, index=-1):
    job = _job(job_id)
    state=status(job_id)['state']
    if state in ('running','paused','stalled','failed','cancelled'):
        if index!=-1:raise SceneError('only the latest observation is available while running or after failure')
        live=job['directory']/'latest-observation.json'
        if not live.is_file():raise SceneError('first live observation is not ready')
        observation=json.loads(live.read_text())
        observation['evidence_state']={'failed':'partial_after_failure','cancelled':'partial_after_cancellation'}.get(state,state)
        return observation
    if state != 'completed': raise SceneError('job is not completed')
    result = json.loads((job['directory'] / 'result.json').read_text())
    samples = result.get('samples', [])
    try:
        observation=samples[index]
        observation['evidence_state']='completed'
        return observation
    except IndexError as error: raise SceneError('sample index out of range') from error

def camera_image(job_id, camera):
    job=_job(job_id)
    result=status(job_id)
    if result['state']=='completed':
        path=result['result'].get('images',{}).get(camera)
        if not path:raise SceneError('camera image not found in run')
        return path
    if result['state'] not in ('running','paused','stalled','failed','cancelled'):raise SceneError('job is not running, paused, stalled, failed, cancelled, or completed')
    spec=json.loads((job['directory']/'spec.json').read_text())
    config=spec['objects'].get(camera,{})
    if config.get('kind')!='camera' or not (config.get('preview_fps') or config.get('record_fps')):
        raise SceneError('camera does not have live preview enabled')
    path=job['directory']/('camera_'+camera+'_live.png')
    if not path.is_file():raise SceneError('first live camera frame is not ready')
    return str(path)

def verify_lock(job_id):
    job=_job(job_id)
    from .run_integrity import verify
    return verify(job['directory'])

def verify_task(job_id,case_path=None,case_type=None,mode='positive',reference_job_id=None):
    job=_job(job_id)
    if status(job_id)['state']!='completed':raise SceneError('physical verification requires a completed result')
    from .verification.case_runner import evaluate
    reference=None
    if reference_job_id is not None:
        if status(reference_job_id)['state']!='completed':raise SceneError('paired reference requires a completed positive run')
        reference=_job(reference_job_id)['directory']
    return evaluate(job['directory'],case_path,case_type,mode=mode,reference_run=reference)

def verify_passive_suite(positive_job_id,control_job_ids,case_path=None):
    """Read a complete passive-network run and its frozen isolated controls."""
    from .verification.passive_network import MODES
    from .verification.case_runner import verify_passive_suite as verify_suite
    if not isinstance(control_job_ids,dict) or set(control_job_ids)-set(MODES[1:]) or any(not isinstance(v,str) for v in control_job_ids.values()):
        raise SceneError('control_job_ids must map passive control modes to job IDs')
    ids=[positive_job_id,*control_job_ids.values()]
    if len(set(ids))!=len(ids):raise SceneError('positive and isolated control jobs must be distinct')
    for job_id in ids:
        if status(job_id)['state']!='completed':raise SceneError('passive suite requires completed positive and control results')
    return verify_suite(_job(positive_job_id)['directory'],{mode:_job(job_id)['directory'] for mode,job_id in control_job_ids.items()},case_path)

def verify_evidence(job_id):
    job=_job(job_id)
    from .evidence_integrity import verify
    return verify(job['directory'])

def synchronize_plan(scene_id, job_id, ids):
    """Use intact observations from a completed run to propose new spawn times."""
    from .scene_edits.synchronize import synchronize
    if status(job_id)['state'] != 'completed':
        raise SceneError('synchronization requires a completed run')
    job = _job(job_id)
    if not verify_lock(job_id).get('passed') or not verify_evidence(job_id).get('passed'):
        raise SceneError('run input and output integrity checks must pass')
    try:
        run = json.loads((job['directory']/'result.json').read_text())
        case = json.loads((job['directory']/'acceptance-case.json').read_text())
    except (OSError, ValueError) as error:
        raise SceneError('run needs a pinned stream case and complete observation') from error
    scene = SceneStore().get(scene_id)
    result = synchronize(scene, run, case, ids)
    result['base_revision'] = scene['revision']
    return result

def set_paused(job_id, paused):
    job=_job(job_id)
    if job['process'].poll() is not None:raise SceneError('job is not running')
    if type(paused) is not bool:raise SceneError('paused must be boolean')
    request={'action':'pause' if paused else 'resume','request_id':uuid.uuid4().hex}
    import tempfile
    with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=job['directory'],prefix='.control-',delete=False) as file:
        name=file.name
        try:
            json.dump(request,file);file.flush();os.replace(name,job['directory']/'control-request.json')
        finally:
            if os.path.exists(name):os.unlink(name)
    return {'job_id':job_id,'requested':request['action'],'request_id':request['request_id']}

def contacts_page(job_id, category='contact_counts', offset=0, limit=100):
    if category not in ('contact_counts','robot_contacts','overlap_counts'):
        raise SceneError('invalid contact category')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200:
        raise SceneError('offset must be nonnegative and limit between 1 and 200')
    job=_job(job_id)
    if status(job_id)['state']!='completed':raise SceneError('job is not completed')
    result=json.loads((job['directory']/'result.json').read_text())
    entries=list(result.get(category,{}).items())
    return {'category':category,'offset':offset,'total':len(entries),
            'contacts':dict(entries[offset:offset+limit]),
            'next_offset':offset+limit if offset+limit<len(entries) else None,
            'contacts_truncated':(result.get('overlap_diagnostics') or {}).get('truncated') if category=='overlap_counts' else result.get('contacts_truncated')}

def video_chunk(job_id, camera, offset=0, length=262144):
    import base64
    if type(offset) is not int or offset<0 or type(length) is not int or not 1<=length<=262144:
        raise SceneError('offset must be nonnegative and length between 1 and 262144')
    job=_job(job_id)
    result=status(job_id)
    if result['state'] in ('failed','cancelled') and result['partial_result_file']:
        video_data=json.loads(Path(result['partial_result_file']).read_text());partial=True
    elif result['state']=='completed':
        video_data=result['result'];partial=False
    else:raise SceneError('job has no completed or partial recording')
    entry=video_data.get('videos',{}).get(camera)
    if not entry:raise SceneError('video not found for camera')
    directory=job['directory'].resolve()
    path=Path(entry['path'])
    if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
        raise SceneError('invalid recorded video path')
    total=path.stat().st_size
    if offset>total:raise SceneError('offset exceeds video size')
    with path.open('rb') as file:
        file.seek(offset)
        data=file.read(length)
    return {'camera':camera,'partial':partial,'offset':offset,'total_bytes':total,'data_base64':base64.b64encode(data).decode('ascii'),
            'chunk_sha256':hashlib.sha256(data).hexdigest(), 'next_offset':offset+len(data) if offset+len(data)<total else None}

def cancel(job_id):
    from .generation import jobs as generation_jobs
    if generation_jobs.owns(job_id):return generation_jobs.cancel(job_id)
    from .preparation import jobs as preparation_jobs
    if preparation_jobs.owns(job_id):return preparation_jobs.cancel(job_id)
    import signal
    future = _downloads.get(job_id)
    if future is not None:
        cancelled = future.cancel()
        result = status(job_id)
        result['cancel_requested'] = cancelled
        if not cancelled and not future.done(): result['message'] = 'Active background task cannot be interrupted'
        return result
    job = _job(job_id)
    if job.get('recovered') and job['process'].poll() is None:
        if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
            raise SceneError('safe cancellation of a reconnected process requires Linux pidfd support')
        process=job['process'];marker=job['directory']/'cancel-request.json'
        try:fd=os.pidfd_open(process.pid,0)
        except OSError as error:raise SceneError(f'could not safely reconnect to worker: {error}') from error
        try:
            if _process_identity(process.pid)!=process.identity:
                raise SceneError('worker process identity changed; cancellation was not sent')
            SceneStore()._write(marker,{'job_id':job_id})
            try:
                # Freeze the verified session leader before addressing its
                # process group, so its PID cannot disappear or be reused
                # between identity validation and group termination.
                signal.pidfd_send_signal(fd,signal.SIGSTOP)
                if (_process_identity(process.pid)!=process.identity or
                        os.getpgid(process.pid)!=process.pid or os.getsid(process.pid)!=process.pid):
                    raise SceneError('reconnected worker is not its recorded session leader')
                os.killpg(process.pid,signal.SIGTERM)
                os.killpg(process.pid,signal.SIGCONT)
            except (OSError,SceneError):
                try:signal.pidfd_send_signal(fd,signal.SIGCONT)
                except OSError:pass
                marker.unlink(missing_ok=True)
                raise
        finally:os.close(fd)
        return status(job_id)
    if job['process'].poll() is None:
        marker=job['directory']/'cancel-request.json'
        SceneStore()._write(marker,{'job_id':job_id})
        try:os.killpg(job['process'].pid, signal.SIGTERM)
        except ProcessLookupError:marker.unlink(missing_ok=True)
        except OSError:
            marker.unlink(missing_ok=True)
            raise
    return status(job_id)
