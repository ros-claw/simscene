"""Read a pinned locally generated source through the ordinary acquisition contract."""
import json
from pathlib import Path
import shutil

from ..catalog.models import stable_hash
from .sand3d import sha


def acquire_generated(plan, config, job_directory=None):
    descriptor=plan['acquisition'];ref=plan['asset_ref']
    expected=Path(config['home'])/'generated_assets'/ref['revision']/'generated.json'
    path=Path(descriptor['manifest_path']).absolute()
    if path != expected.absolute() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('generated source locator escaped its managed store')
    if not path.is_file() or path.stat().st_size>65536 or sha(path)!=descriptor['manifest_sha256']:
        raise ValueError('generated source manifest missing or changed')
    manifest=json.loads(path.read_text())
    identity=manifest['identity']
    if manifest.get('schema')!='simscene.generated_source.v1' or manifest.get('asset_ref')!=ref or stable_hash(identity)!=ref['revision']:
        raise ValueError('generated source identity mismatch')
    if manifest.get('root')!='source.usda' or manifest.get('files') != [{'path':'source.usda','sha256':identity['output_sha256'],'size_bytes':(path.parent/'source.usda').stat().st_size}]:
        raise ValueError('generated source file inventory changed')
    source=path.parent/'source.usda'
    if source.is_symlink() or not source.is_file() or sha(source)!=identity['output_sha256']:
        raise ValueError('generated source content changed')
    files=[dict(item) for item in manifest['files']]
    total=sum(item['size_bytes'] for item in files)
    limits=plan['budget_breakdown']
    if total>min(limits['staging_bytes'],limits['unpacked_bytes']):
        raise ValueError('budget_exceeded: generated input exceeds staging or unpacked limit')
    if job_directory is not None:
        destination=Path(job_directory)/'source';destination.mkdir(exist_ok=False)
        shutil.copyfile(source,destination/'source.usda');source=destination/'source.usda'
        if sha(source)!=identity['output_sha256']:raise ValueError('generated job copy changed')
    return {'root':str(source),'files':files,'source_ref':ref,'source':'generated:'+ref['revision'],
            'source_sha256':identity['output_sha256'],'source_manifest_hash':descriptor['manifest_sha256'],
            'manifest_sha256':descriptor['manifest_sha256'],'package_sha256':ref['revision'],
            'license':plan['license_decision'],'provenance':plan['source_snapshot']['provenance'],
            'dependency_status':'resolved_locally','actual_download_bytes':0,'transfer_ledger':[],
            'job_copy_bytes':total if job_directory else 0}
