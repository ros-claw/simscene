"""Recheck one standalone pair and its frozen inputs without changing them."""
import argparse
import json
from pathlib import Path
import sys

from asset_lock import sha256, verify_asset_files, verify_runtime
from pair_check import check_pair
from evidence_lock import verify_evidence_lock

TOOL_FILES = ('run_pair.py', 'fetch_assets.py', 'worker.py', 'evaluate.py', 'pair_check.py', 'asset_lock.py', 'evidence_lock.py',
              'audit_output.py', 'fixed_case.json', 'asset-lock.json', 'runtime-lock.json')


def _load_run(path):
    return {'metadata': json.loads((path / 'metadata.json').read_text()),
            'rows': [json.loads(line) for line in (path / 'telemetry.jsonl').read_text().splitlines()],
            'process': json.loads((path / 'process-exit.json').read_text()),
            'result': json.loads((path / 'result.json').read_text()),
            'log': (path / 'worker.log').read_text(errors='replace')}


def audit_output(output, isaac_python=None):
    root = Path(output).expanduser().resolve()
    runtime = root / 'runtime'
    manifest = json.loads((root / 'run-manifest.json').read_text())
    if manifest.get('schema') != 'simscene.mobilitygen_jetbot.run.v1':
        raise ValueError('unsupported run manifest')
    locks = manifest.get('evidence_locks')
    if not isinstance(locks, dict) or set(locks) != {'positive', 'zero'}:
        raise ValueError('evidence locks missing or incomplete')
    statuses = {mode: verify_evidence_lock(root / 'runs' / mode, mode, locks[mode])
                for mode in ('positive', 'zero')}
    if any(status['partial'] for status in statuses.values()):
        return {'passed': False, 'partial': True,
                'errors': ['one or both runs contain partial evidence'], 'evidence_locks': statuses}
    expected = manifest.get('runtime_files_sha256')
    if not isinstance(expected, dict) or set(expected) != set(TOOL_FILES) | {'gpu_queue.py'}:
        raise ValueError('frozen runtime file list differs from the contract')
    for name, digest in expected.items():
        file = runtime / name
        if file.is_symlink() or not file.is_file() or sha256(file) != digest:
            raise ValueError('frozen runtime file changed: ' + name)
    source_lock_path = runtime / 'tool-lock.json'
    if not source_lock_path.is_file() or sha256(source_lock_path) != manifest.get('source_tool_lock_sha256'):
        raise ValueError('tool lock changed or missing')
    source_lock = json.loads(source_lock_path.read_text())
    if (source_lock.get('files_sha256') != {name: expected[name] for name in TOOL_FILES} or
            source_lock.get('queue_sha256') != expected['gpu_queue.py']):
        raise ValueError('runtime files do not match the frozen tool lock')
    asset_lock = json.loads((runtime / 'asset-lock.json').read_text())
    verify_asset_files(root / 'assets' / asset_lock['asset'], asset_lock)
    launcher = Path(isaac_python or manifest['isaac_python']).expanduser().resolve()
    if not launcher.is_file() or sha256(launcher) != manifest['isaac_python_sha256']:
        raise ValueError('Isaac launcher missing or changed')
    runtime_lock = json.loads((runtime / 'runtime-lock.json').read_text())
    verify_runtime(launcher, runtime_lock)
    case = json.loads((runtime / 'fixed_case.json').read_text())
    positive, control = _load_run(root / 'runs/positive'), _load_run(root / 'runs/zero')
    for mode, item in [('positive', positive), ('zero', control)]:
        metadata, receipt = item['metadata'], item['process']
        if receipt.get('schema') != 'simscene.process_exit.v1' or receipt.get('run_id') != mode:
            raise ValueError('queue receipt missing or belongs to a different run')
        if (metadata.get('case') != case or metadata.get('case_sha256') != expected['fixed_case.json'] or
                metadata.get('script_sha256') != expected['worker.py'] or metadata.get('script_name') != 'worker.py' or
                metadata.get('asset_sha256') != sha256(root / 'assets' / asset_lock['asset']) or
                metadata.get('isaac_version') != runtime_lock['isaac_version']):
            raise ValueError('run metadata differs from frozen inputs')
    result = check_pair(positive, control)
    for mode, item in [('positive', positive), ('zero', control)]:
        expected_result = result['checks'][mode]
        recorded = item['result']
        expected_keys = ('passed', 'errors', 'samples', 'displacement_m', 'peak_displacement_m',
                         'max_step_displacement_m', 'final_goal_distance_m',
                         'forward_progress_during_nonzero_targets_m', 'sampled_wheel_short_angle_changes_rad')
        if (not isinstance(recorded, dict) or any(recorded.get(k) != expected_result.get(k) for k in expected_keys)
                or recorded.get('terminal_status') != item['metadata'].get('terminal_status')
                or (mode == 'positive' and recorded.get('first_arrival_step') != expected_result.get('first_arrival_step'))):
            result['passed'] = False
            result['errors'].append(mode + ' recorded result differs from recomputed evidence')
    result.update(schema='simscene.mobilitygen_jetbot.pair-audit.v1',
                  scope='one fixed straight route, one Jetbot, one host; no safety or integration claim',
                  runs={mode: {name + '_sha256': sha256(root / 'runs' / mode / name)
                              for name in ('metadata.json', 'telemetry.jsonl', 'process-exit.json', 'worker.log')}
                        for mode in ('positive', 'zero')})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', help='completed standalone pair directory')
    parser.add_argument('--isaac-python', help='equivalent tested Isaac python.sh if installation moved')
    args = parser.parse_args()
    try:
        result = audit_output(args.output, args.isaac_python)
    except Exception as error:
        result = {'passed': False, 'errors': [f'{type(error).__name__}: {error}']}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
