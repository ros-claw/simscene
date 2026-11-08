"""Detached, checkpointed acquisition/preparation supervisor. No MCP-owned Future."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from .jobs import write


class Cancelled(Exception): pass


def check_cancel(root):
    if (root/'cancel-request.json').exists(): raise Cancelled('cancelled at a safe checkpoint')


def terminate_group(process):
    """Confirm SDK descendants exited, even if the queue wrapper exits first."""
    def alive():
        try: os.killpg(process.pid, 0); return True
        except ProcessLookupError: return False
    for sig, grace in ((signal.SIGTERM,10), (signal.SIGKILL,5)):
        try: os.killpg(process.pid,sig)
        except ProcessLookupError: break
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline:
            process.poll()
            if not alive():break
            time.sleep(.1)
        if not alive():break
    process.wait()
    if alive():raise RuntimeError('cancellation_unconfirmed: SDK process group still exists')


def run_sdk(root, task, config):
    from ..settings import get
    selected = task.get('plan',{}).get('toolchain_requirements',{}).get('isaac_launcher') or get('isaac_python')
    executable = Path(selected).expanduser().resolve()
    task_file = root/'sdk-task.json'; write(task_file, task)
    env = dict(os.environ, SIMSCENE_PROBE_SDK_ROOT=str(executable.parent))
    if config.get('converter_tools_prefix'):
        env['SIMSCENE_GLTF_TRANSFORM_PREFIX'] = config['converter_tools_prefix']
    queue = Path(__file__).parents[1]/'worker'/'gpu_queue.py'
    script = Path(__file__).with_name('sdk_worker.py')
    command = [sys.executable, str(queue), str(root/'gpu-queue.json'), str(executable), str(script), str(task_file)]
    with (root/'sdk.log').open('ab') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            started = time.monotonic()
            while process.poll() is None:
                check_cancel(root)
                if time.monotonic()-started > 1800: raise TimeoutError('SDK preparation exceeded 1800 seconds')
                output = task.get('output_directory')
                if output:
                    used = sum(p.stat().st_size for base in (Path(output),root/'source') for p in base.rglob('*') if p.is_file())
                    if used > task['plan']['budget_breakdown']['staging_bytes']:
                        raise ValueError('budget_exceeded: preparation staging exceeded hard cap')
                time.sleep(.2)
            if process.returncode != 0:
                raise ValueError('conversion_failed: SDK exit '+str(process.returncode)+'; inspect '+str(root/'sdk.log'))
        except BaseException:
            terminate_group(process)
            raise
    error_file=root/'sdk-error.json'
    if error_file.is_file():
        error=json.loads(error_file.read_text())
        from .profiles import PreparationError
        raise PreparationError(error['code'],error['error'])
    if not Path(task['output']).is_file():
        raise ValueError('conversion_failed: SDK produced no verified result; inspect '+str(root/'sdk.log'))
    result = json.loads(Path(task['output']).read_text())
    return result


def _summary(package, manifest, *, reused, transferred):
    from .environment import file_sha
    from .contracts import prepared_contract
    result=prepared_contract(manifest,manifest_path=package/'manifest.json',manifest_sha256=file_sha(package/'manifest.json'))
    return dict(result,cache_hit=reused,actual_download_bytes=transferred)


def execute(root):
    root = Path(root).resolve(); record = json.loads((root/'job.json').read_text())
    config = json.loads((root/'config.json').read_text()); plan = json.loads((root/'plan.json').read_text())
    def phase(value, checkpoint=None, **fields):
        record['state'] = value; record.update(fields)
        if checkpoint: record['checkpoints'].append(checkpoint)
        write(root/'job.json', record)
    try:
        from ..acquisition.plans import load_plan
        from .environment import current_runtime
        if load_plan(plan['plan_id'], config=config) != plan:
            raise ValueError('verification_failed: plan snapshot differs from canonical plan')
        runtime = current_runtime(config=config)
        if (runtime['target'] != plan['target'] or runtime['installation'] != plan['toolchain_requirements']
                or runtime['converter'] != plan['converter_selection']
                or runtime.get('predecoder_configuration') != plan.get('converter_environment')):
            raise ValueError('plan_environment_changed: create a new plan for this toolchain')
        check_cancel(root); phase('acquiring')
        from ..acquisition.dispatch import acquire_selected
        acquired = acquire_selected(plan, config=config, job_directory=root)
        write(root/'acquired.json', acquired)
        phase('acquiring',actual_download_bytes=acquired.get('actual_download_bytes'),
              transfer_ledger=acquired.get('transfer_ledger',[]))
        check_cancel(root)
        if Path(acquired['root']).suffix.lower()=='.glb':
            if acquired.get('unresolved_dependencies') or acquired.get('dependency_status')=='missing':
                raise ValueError('dependency_missing: selected GLB closure is incomplete')
            from .glb_convert import validate_glb
            validate_glb(acquired['root'],rigid=plan['profile_id']=='rigid_prop_v1')
        elif acquired.get('dependency_status') not in ('resolved_locally','resolved_with_runtime'):
            raise ValueError('dependency_missing: USD source closure is incomplete or unverified')
        phase('converting', 'verified_source_closure')
        store = Path(config['prepared_directory']); store.mkdir(parents=True, exist_ok=True)
        # Acquisition and LRU operate on the source cache separately. A private
        # source copy made by dispatch is never an LRU victim during conversion.
        with (store/'.prepared.lock').open('a') as lock:
            while True:
                check_cancel(root)
                try:fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:time.sleep(.1)
            # Resolve an existing source+profile+target result by its content key.
            from .profiles import preparation_key,source_identity
            from .glb_convert import CONVERTER
            from .environment import file_sha
            files = [{'path':f['path'], 'sha256':f['sha256'], 'size_bytes':f.get('size_bytes',f.get('size'))} for f in acquired['files']]
            import hashlib
            closure = hashlib.sha256(json.dumps(sorted(files,key=lambda f:f['path']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
            converter = CONVERTER if Path(acquired['root']).suffix.lower()=='.glb' else {'backend':'openusd','version':plan['target']['usd_version']}
            key = preparation_key(source_identity(acquired,closure), plan['profile_id'], plan['parameters'], plan['target'], converter)
            package = store/key; reused = package.exists()
            from ..physics_binding import validate_asset_binding
            if not reused:
                output = root/'prepared-staging'
                result = run_sdk(root, {'operation':'prepare', 'plan':plan, 'acquired':acquired,
                    'output_directory':str(output), 'output':str(root/'sdk-result.json')}, config)
                if result['prepared_id'] != key: raise ValueError('verification_failed: prepared content key mismatch')
                phase('inspecting', 'converter_exited_successfully')
                validate_asset_binding({'manifest_path':str(output/'manifest.json'), 'manifest_sha256':file_sha(output/'manifest.json')})
                size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
                source_size = sum(p.stat().st_size for p in (root/'source').rglob('*') if p.is_file())
                if size+source_size > plan['budget_breakdown']['staging_bytes']:
                    raise ValueError('budget_exceeded: source plus prepared staging exceeded frozen cap')
                if size > config['prepared_cache_bytes']: raise ValueError('budget_exceeded: prepared package exceeds cache capacity')
                entries = [p for p in store.iterdir() if p.is_dir() and len(p.name)==64]
                used = sum(f.stat().st_size for p in entries for f in p.rglob('*') if f.is_file())
                for old in sorted(entries,key=lambda p:p.stat().st_mtime_ns):
                    if used+size <= config['prepared_cache_bytes']: break
                    old_size = sum(f.stat().st_size for f in old.rglob('*') if f.is_file())
                    shutil.rmtree(old); used -= old_size
                os.replace(output, package)
            binding = {'manifest_path':str(package/'manifest.json'), 'manifest_sha256':file_sha(package/'manifest.json')}
            manifest = validate_asset_binding(binding)
            expected={'prepared_id':key,'profile_id':plan['profile_id'],'parameters':plan['parameters'],
                      'source_ref':acquired.get('source_ref'),'source_manifest_sha256':acquired.get('manifest_sha256'),
                      'license':acquired.get('license'),'provenance':acquired.get('provenance'),
                      'target':plan['target'],'toolchain':converter,'source_closure_sha256':closure}
            if any(manifest.get(k)!=v for k,v in expected.items()):
                raise ValueError('verification_failed: prepared cache identity or attribution differs from immutable selection')
            os.utime(package, None)
            check_cancel(root)
            result = _summary(package, manifest, reused=reused, transferred=acquired.get('actual_download_bytes'))
            phase('completed', 'verified_prepared_closure', result=result)
    except Cancelled as error: phase('cancelled', error=str(error), error_code='cancelled')
    except Exception as error:
        code = getattr(error, 'code', None) or str(error).partition(':')[0]
        if not isinstance(code,str):code='preparation_failed'
        accounting={key:getattr(error,key) for key in ('actual_download_bytes','transfer_ledger') if hasattr(error,key)}
        phase('failed', error=str(error), error_code=code if len(code)<80 else 'preparation_failed',**accounting)


if __name__ == '__main__': execute(sys.argv[1])
