#!/usr/bin/env python3
"""Run the fixed experimental Jetbot pair via SimScene's per-user queue."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from asset_lock import sha256, snapshot_assets, verify_asset_files, verify_runtime
from audit_output import TOOL_FILES
from evidence_lock import create_evidence_lock

HERE = Path(__file__).resolve().parent


def _write_manifest(path, value):
    with tempfile.NamedTemporaryFile('w', encoding='utf8', dir=path.parent, prefix='.manifest-', delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_tool_lock(queue):
    lock = json.loads((HERE / 'tool-lock.json').read_text())
    expected = lock.get('files_sha256')
    names = set(TOOL_FILES)
    if lock.get('schema') != 'simscene.mobilitygen_jetbot.tool-lock.v1' or not isinstance(expected, dict) or set(expected) != names:
        raise ValueError('tool lock is missing required files')
    for name, digest in expected.items():
        path = HERE / name
        if not path.is_file() or path.is_symlink() or sha256(path) != digest:
            raise ValueError('tool file differs from its frozen lock: ' + name)
    if not queue.is_file() or sha256(queue) != lock.get('queue_sha256'):
        raise ValueError('queue script differs from the pinned SimScene GPU queue')
    return lock


def run_pair(isaac_python, asset_path, output, queue_script=None):
    launcher = Path(isaac_python).expanduser().resolve()
    asset = Path(asset_path).expanduser().absolute()
    output = Path(output).expanduser().absolute()
    default_queue = HERE.parent.parent / 'src/simscene/worker/gpu_queue.py'
    queue = Path(queue_script).expanduser().resolve() if queue_script else default_queue.resolve()
    lock = _validate_tool_lock(queue)
    runtime_lock = json.loads((HERE / 'runtime-lock.json').read_text())
    verify_runtime(launcher, runtime_lock)
    asset_lock = json.loads((HERE / 'asset-lock.json').read_text())
    verify_asset_files(asset, asset_lock)
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new path; prior evidence is never overwritten')
    output_real = output.resolve()
    repository = next((parent for parent in HERE.parents if (parent / '.git').exists()), None)
    if repository and output_real.is_relative_to(repository):
        raise ValueError('output must be outside the repository; source assets are not repository files')
    if output_real.is_relative_to(asset.parent.resolve()):
        raise ValueError('output must be outside the input asset tree')
    output.mkdir(parents=True, exist_ok=False)
    runtime = output / 'runtime'
    runtime.mkdir()
    try:
        for name in TOOL_FILES:
            shutil.copyfile(HERE / name, runtime / name)
        shutil.copyfile(HERE / 'tool-lock.json', runtime / 'tool-lock.json')
        shutil.copyfile(queue, runtime / 'gpu_queue.py')
        snapshot = snapshot_assets(asset, asset_lock, output / 'assets')
        files = {name: sha256(runtime / name) for name in (*TOOL_FILES, 'gpu_queue.py')}
        for name in TOOL_FILES:
            if files[name] != lock['files_sha256'][name]:
                raise ValueError('runtime snapshot changed while copying: ' + name)
        if files['gpu_queue.py'] != lock['queue_sha256']:
            raise ValueError('queue changed while copying')
        manifest = {'schema': 'simscene.mobilitygen_jetbot.run.v1', 'isaac_python': str(launcher),
                    'isaac_python_sha256': sha256(launcher), 'runtime_files_sha256': files,
                    'source_tool_lock_sha256': sha256(HERE / 'tool-lock.json'),
                    'input_asset_root': str(asset), 'experimental': True, 'evidence_locks': {}}
        _write_manifest(output / 'run-manifest.json', manifest)
        launches = []
        env = os.environ.copy()
        env.pop('PYTHONEXE', None)
        env['PYTHONUNBUFFERED'] = '1'
        for mode in ('positive', 'zero'):
            run = output / 'runs' / mode
            run.mkdir(parents=True)
            (run / 'queue-state.json').write_text(json.dumps({'state': 'queued'}) + '\n')
            command = [sys.executable, str(runtime / 'gpu_queue.py'), str(run / 'queue-state.json'),
                       str(launcher), '--no-ros-env', str(runtime / 'worker.py'), '--mode', mode,
                       '--asset', str(snapshot), '--output', str(run)]
            print(f'Starting {mode} through the SimScene GPU queue', file=sys.stderr, flush=True)
            with (run / 'worker.log').open('xb') as log:
                try:
                    code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, check=False).returncode
                except OSError as error:
                    code = None
                    (run / 'launch-error.txt').write_text(f'{type(error).__name__}: {error}\n')
            launches.append({'mode': mode, 'returncode': code})
            manifest['evidence_locks'][mode] = create_evidence_lock(run, mode, code)
            _write_manifest(output / 'run-manifest.json', manifest)
        (output / 'launch-summary.json').write_text(json.dumps(launches, indent=2) + '\n')
        audit = subprocess.run([sys.executable, str(runtime / 'audit_output.py'), str(output),
                                '--isaac-python', str(launcher)], capture_output=True, text=True, check=False)
        (output / 'audit.json').write_text(audit.stdout)
        if audit.stderr:
            (output / 'audit-stderr.txt').write_text(audit.stderr)
        try:
            result = json.loads(audit.stdout)
        except ValueError:
            result = {'passed': False, 'errors': ['audit produced invalid JSON']}
        if audit.returncode != 0 and result.get('passed'):
            result = {'passed': False, 'errors': ['audit process exited unsuccessfully']}
        result['output'] = str(output)
        return result
    except BaseException as error:
        (output / 'launch-error.txt').write_text(f'{type(error).__name__}: {error}\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isaac-python', required=True, help='tested Isaac Sim python.sh')
    parser.add_argument('--asset', required=True, help='locally acquired, locked jetbot.usda')
    parser.add_argument('--output', required=True, help='new output path outside the repository')
    parser.add_argument('--queue-script', help='copy of the pinned SimScene gpu_queue.py')
    args = parser.parse_args()
    try:
        result = run_pair(args.isaac_python, args.asset, args.output, args.queue_script)
    except (OSError, ValueError) as error:
        result = {'passed': False, 'errors': [f'{type(error).__name__}: {error}']}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
