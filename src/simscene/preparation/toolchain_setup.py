"""Explicit opt-in setup of the isolated, spike-verified meshopt predecoder.

This module never runs during planning, probing, conversion, or import. It does
not install Node.js or change runtime configuration. Failed prefixes and their
logs are retained; select a new empty prefix for a later attempt.
"""
import hashlib
from importlib import resources
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess

from .glb_convert import PREDECODER, predecoder_fingerprint
from .profiles import PreparationError


def _prefix(destination):
    if not isinstance(destination, (str, os.PathLike)) or not str(destination).strip():
        raise ValueError('decoder destination must be a nonempty directory path')
    path = Path(destination).expanduser().absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('decoder destination must not contain symlinks')
    if path.exists():
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError('decoder destination must be a directory owned by the current user')
        if info.st_mode & 0o022:
            raise ValueError('decoder destination must not be writable by other users')
        if any(path.iterdir()):
            raise ValueError('decoder destination must be new or empty; existing installs are preserved')
    else:
        path.mkdir(parents=True, mode=0o700)
    return path


def _resources():
    packaged = resources.files('simscene.preparation').joinpath('data')
    package = packaged.joinpath('package.json').read_bytes()
    lock = packaged.joinpath('package-lock.json').read_bytes()
    if hashlib.sha256(lock).hexdigest() != PREDECODER['package_lock_sha256']:
        raise PreparationError('verification_failed', 'shipped decoder lock differs from the verified toolchain')
    dependencies = {'@gltf-transform/core': PREDECODER['core_version'],
                    '@gltf-transform/extensions': PREDECODER['extensions_version'],
                    'meshoptimizer': PREDECODER['meshoptimizer_version']}
    if json.loads(package) != {'dependencies': dependencies}:
        raise PreparationError('verification_failed', 'shipped decoder package differs from the verified toolchain')
    if json.loads(lock).get('name') != 'converter-tools':
        raise PreparationError('verification_failed', 'verified decoder lock name changed')
    return package, lock


def setup_predecoder(destination, *, timeout_seconds=180):
    """Install the pinned packages into a new/empty owned prefix, then verify.

    npm lifecycle scripts, audit, and funding requests are disabled. The only
    success state is an exact match to predecoder_fingerprint(). Failure raises
    PreparationError with setup_directory/log_path and keeps all artifacts.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
        raise ValueError('decoder setup timeout must be finite and between 0 and 600 seconds')
    prefix = _prefix(destination)
    # Exclusive reservation prevents simultaneous callers from sharing a setup.
    # The marker intentionally remains so a failed prefix is never mistaken for
    # an untouched empty destination on the next call.
    with (prefix / '.setup-reservation').open('x') as marker:
        marker.write('simscene explicit predecoder setup\n')
    log_path = prefix / 'install.log'
    result_path = prefix / 'setup-result.json'
    result = {'schema_version': 1, 'status': 'installing', 'prefix': str(prefix),
              'log_path': str(log_path), 'setup_record': str(result_path)}
    def save():
        from .jobs import write
        write(result_path, result)
    try:
        save()
        with log_path.open('w', encoding='utf-8') as log:
            node, npm = shutil.which('node'), shutil.which('npm')
            if not node or not npm:
                raise PreparationError('dependency_missing', 'Node.js and npm must be installed before explicit decoder setup')
            version = subprocess.run([node, '--version'], capture_output=True, text=True,
                                     timeout=5, check=True).stdout.strip()
            log.write('Node version: ' + version + '\n')
            if version != PREDECODER['node_version']:
                raise PreparationError('plan_environment_changed', 'decoder requires Node ' + PREDECODER['node_version'])
            package, lock = _resources()
            (prefix / 'package.json').write_bytes(package)
            (prefix / 'package-lock.json').write_bytes(lock)
            command = [npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund',
                       '--prefix', str(prefix), '--workspaces=false',
                       '--fetch-retries=0', '--fetch-timeout=30000']
            result['command'] = command
            log.write('Command: ' + json.dumps(command) + '\n'); log.flush()
            subprocess.run(command, cwd=prefix, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout_seconds, check=True)
            # npm ci must preserve the shipped selection lock byte-for-byte.
            if (prefix / 'package-lock.json').read_bytes() != lock or (prefix / 'package.json').read_bytes() != package:
                raise PreparationError('verification_failed', 'npm changed the frozen decoder package selection')
            fingerprint = predecoder_fingerprint(prefix)
            result.update(status='ready', fingerprint=fingerprint)
            save()
            return result
    except Exception as error:
        code = getattr(error, 'code', None) or ('setup_timeout' if isinstance(error, subprocess.TimeoutExpired) else 'decoder_setup_failed')
        result.update(status='failed', error_code=code, error=str(error))
        result.pop('fingerprint', None)
        save()
        with log_path.open('a', encoding='utf-8') as log:
            log.write('\nSetup failed: ' + str(error) + '\n')
        failure = PreparationError(code, 'decoder setup failed; retained prefix ' + str(prefix) + '; inspect ' + str(log_path))
        failure.setup_directory = str(prefix)
        failure.log_path = str(log_path)
        raise failure from error
