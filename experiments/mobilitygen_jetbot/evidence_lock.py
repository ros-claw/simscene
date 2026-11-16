"""Freeze and verify local run files; hashes do not provide authenticity."""
import json
import os
from pathlib import Path
import tempfile

from asset_lock import sha256

FILES = ('telemetry.jsonl', 'metadata.json', 'result.json', 'process-exit.json', 'worker.log')


def create_evidence_lock(root, mode, returncode):
    root = Path(root)
    if mode not in ('positive', 'zero') or (returncode is not None and type(returncode) is not int):
        raise ValueError('invalid run mode or exit code')
    files = {}
    for name in FILES:
        path = root / name
        if path.is_symlink():
            raise ValueError('evidence file is a symlink: ' + name)
        files[name] = {'bytes': path.stat().st_size, 'sha256': sha256(path)} if path.is_file() else None
    record = {'schema': 'simscene.mobilitygen_jetbot.evidence-lock.v1', 'mode': mode,
              'returncode': returncode, 'partial': returncode != 0 or any(v is None for v in files.values()),
              'files': files}
    target = root / 'evidence-lock.json'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=root, prefix='.evidence-lock-', delete=False) as f:
        temporary = Path(f.name)
        json.dump(record, f, indent=2, sort_keys=True)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    try:
        # Linking an already-fsynced temp file is atomic and never replaces evidence.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256(target)


def verify_evidence_lock(root, mode, expected_digest):
    root = Path(root)
    target = root / 'evidence-lock.json'
    if target.is_symlink() or not target.is_file() or sha256(target) != expected_digest:
        raise ValueError('evidence lock missing or changed')
    record = json.loads(target.read_text())
    files = record.get('files')
    if (record.get('schema') != 'simscene.mobilitygen_jetbot.evidence-lock.v1' or
            record.get('mode') != mode or type(record.get('partial')) is not bool or
            not isinstance(files, dict) or set(files) != set(FILES)):
        raise ValueError('invalid evidence lock')
    code = record.get('returncode')
    if code is not None and type(code) is not int:
        raise ValueError('invalid locked process exit code')
    if record['partial'] != (code != 0 or any(v is None for v in files.values())):
        raise ValueError('inconsistent partial evidence status')
    for name, expected in files.items():
        path = root / name
        if path.is_symlink():
            raise ValueError('evidence file became a symlink: ' + name)
        if expected is None:
            if path.exists():
                raise ValueError('missing evidence appeared after locking: ' + name)
        elif (not isinstance(expected, dict) or set(expected) != {'bytes', 'sha256'} or
              not path.is_file() or path.stat().st_size != expected['bytes'] or sha256(path) != expected['sha256']):
            raise ValueError('evidence missing or changed: ' + name)
    return record
