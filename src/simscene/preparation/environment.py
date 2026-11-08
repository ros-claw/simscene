"""Validate a runtime capability observation without starting a GPU in plan-only work."""
import hashlib
import json
from pathlib import Path
import platform


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


def installation_fingerprint():
    from ..settings import get
    launcher = Path(get('isaac_python', '')).expanduser().resolve()
    if not launcher.is_file():
        raise ValueError('source_unavailable: configure an Isaac Python launcher')
    version = launcher.parent/'VERSION'
    if not version.is_file():
        raise ValueError('source_unavailable: SDK VERSION is missing')
    # Source files defining selected SDK extension policy are part of identity.
    converters = sorted(launcher.parent.glob('extscache/omni.kit.asset_converter-*/config/extension.toml'))
    return {'isaac_launcher': str(launcher), 'launcher_sha256': file_sha(launcher),
            'isaac_version': version.read_text().strip(), 'version_sha256': file_sha(version),
            'converter_configs': {str(p.relative_to(launcher.parent)): file_sha(p) for p in converters}}


def current_runtime(config=None):
    from ..catalog.config import read
    config = config or read(); path = Path(config['runtime_manifest'])
    if not path.is_file():
        raise ValueError('environment_probe_required: run the explicit preparation runtime probe')
    record = json.loads(path.read_text())
    if record.get('schema_version') != 1 or record.get('installation') != installation_fingerprint():
        raise ValueError('plan_environment_changed: preparation runtime probe is stale')
    from ..catalog.models import BackendTarget
    target = BackendTarget.from_dict(record['target']).to_dict()
    converter = record['converter']
    if converter.get('backend') != 'omni.kit.asset_converter' or not converter.get('version'):
        raise ValueError('unsupported_codec: no verified converter available')
    from .glb_convert import CONVERTER, predecoder_fingerprint
    if converter != CONVERTER:
        raise ValueError('plan_environment_changed: converter policy changed')
    prefix = config.get('converter_tools_prefix')
    tools = predecoder_fingerprint(prefix) if prefix else None
    if tools != record.get('predecoder_configuration'):
        raise ValueError('plan_environment_changed: predecoder installation changed')
    return {'target': target, 'converter': converter, 'installation': record['installation'],
            'predecoder_configuration':tools}


def save_observation(observation, output=None):
    """Called only after an actual SDK process observes the selected environment."""
    from ..catalog.config import read
    from ..catalog.models import BackendTarget
    import os, tempfile
    target = BackendTarget.from_dict(observation['target']).to_dict()
    if target['engine'] != 'physx': raise ValueError('M1 requires PhysX')
    record = {'schema_version': 1, 'installation': installation_fingerprint(),
              'target': target, 'converter': observation['converter'],
              'observation_source': observation.get('observation_source'),
              'predecoder_configuration': observation.get('predecoder_configuration'),
              'physical_steps': observation.get('physical_steps', 0)}
    path = Path(output or read()['runtime_manifest']); path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.runtime-', delete=False) as f:
        json.dump(record, f, indent=2); f.flush(); os.fsync(f.fileno()); temporary = Path(f.name)
    try: os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)
    return record


def probe_runtime():
    """Explicit setup action. Unlike planning this starts a queued SDK app."""
    from ..catalog.config import read
    from .jobs import write
    from .worker import run_sdk
    import uuid
    config=read(); root=Path(config['home'])/'preparation-probes'/uuid.uuid4().hex
    root.mkdir(parents=True)
    observation=run_sdk(root,{'operation':'probe','output':str(root/'observation.json')},config)
    result=save_observation(observation)
    return dict(result,record_path=config['runtime_manifest'],probe_directory=str(root))
