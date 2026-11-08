"""Fixed-template optional modeling. Arbitrary Python and remote programs are data only."""
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import tempfile

from ..catalog.models import AssetRecord, AssetRef, stable_hash
from ..catalog.store import CatalogStore
from ..preparation.jobs import write

COMMIT = '0d589a5ba568fd72c8da97f8d039918650608a42'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parameters(recipe_id, value):
    if recipe_id == 'open_receiver_v1':
        bounds={'interior_width_m':(.04,2,.4),'interior_depth_m':(.04,1,.3),
                'interior_height_m':(.02,1,.2),'wall_thickness_m':(.002,.05,.01),'floor_thickness_m':(.002,.05,.01)}
        if not isinstance(value,dict) or set(value)-set(bounds):
            raise ValueError('open_receiver_v1 requires structured metric cavity/wall dimensions only')
        from ..recipes.compile import _number
        return {key:_number(value.get(key,default),key,low,high) for key,(low,high,default) in bounds.items()}
    if recipe_id != 'guide_plate_v1':
        raise ValueError('unknown trusted template; available: guide_plate_v1,open_receiver_v1')
    if not isinstance(value, dict) or set(value)-{'length_m','width_m','thickness_m'}:
        raise ValueError('guide_plate_v1 accepts length_m,width_m,thickness_m only')
    normalized = dict(length_m=.5, width_m=.18, thickness_m=.015)
    normalized.update(value)
    for key, low, high in [('length_m',.05,2),('width_m',.02,.8),('thickness_m',.002,.08)]:
        from ..recipes.compile import _number
        normalized[key] = _number(normalized[key],key,low,high)
    if normalized['thickness_m'] >= min(normalized['length_m'],normalized['width_m']):
        raise ValueError('guide thickness must be less than length and width')
    return normalized


def _run(task, python, folder):
    python = str(Path(python).expanduser().absolute())
    if not Path(python).is_file():
        raise ValueError('independent generation interpreter is missing')
    task_path = folder/'backend-task.json'
    write(task_path,task)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]),
               OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MALLOC_ARENA_MAX='2')
    with (folder/'backend.log').open('ab') as log:
        subprocess.run([python,'-m','simscene.generation.backend_worker',str(task_path)],
                       env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120,cwd=folder)


def probe_runtime(python, output):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('runtime observation must be a new file')
    output.parent.mkdir(parents=True,exist_ok=True)
    folder = output.with_name(output.name+'.probe')
    folder.mkdir()
    result = folder/'observed.json'
    _run({'operation':'probe','output':str(result)},python,folder)
    observed = json.loads(result.read_text())
    write(output,{'schema_version':1,'python':str(Path(python).expanduser().absolute()),
                  'reviewed_commit':COMMIT,'observed':observed})
    return json.loads(output.read_text())


def generate_asset(recipe_id, value, runtime, *, output_directory, config):
    """Build a new immutable source, then register it for the normal planning path."""
    p = parameters(recipe_id,value)
    if not isinstance(runtime,dict) or runtime.get('schema_version') != 1 or runtime.get('reviewed_commit') != COMMIT:
        raise ValueError('generation_runtime_unavailable: explicitly probe a reviewed independent runtime')
    output = Path(output_directory).resolve()
    output.mkdir(parents=True,exist_ok=False)
    task = {'operation':'generate','recipe_id':recipe_id,'parameters':p,
            'expected_runtime':runtime['observed'],'output':str(output/'source.usda'),
            'runtime_output':str(output/'backend-runtime.json')}
    _run(task,runtime['python'],output)
    source = output/'source.usda'
    if not source.is_file() or source.stat().st_size > 16*1024**2:
        raise ValueError('generation_failed: output missing or exceeded size cap')
    template = files('simscene.generation').joinpath('templates/'+recipe_id+'.py').read_bytes()
    identity = {'recipe_id':recipe_id,'parameters':p,'seed':0,'template_sha256':hashlib.sha256(template).hexdigest(),
                'toolchain':runtime,'output_sha256':sha(source)}
    revision = stable_hash(identity)
    ref = AssetRef('local-sand3d',recipe_id,revision)
    closure = [{'path':'source.usda','sha256':sha(source),'size_bytes':source.stat().st_size}]
    generated = {'schema_version':1,'schema':'simscene.generated_source.v1','asset_ref':ref.to_dict(),
                 'identity':identity,'files':closure,'root':'source.usda',
                 'unit_contract':{'input':'m','output':'m','up_axis':'Z'},
                 'execution_scope':'trusted shipped template with process resource limits; no filesystem/network sandbox; external code execution unavailable',
                 'physics_status':'not_prepared','actual_download_bytes':0}
    write(output/'generated.json',generated)
    destination = Path(config['home'])/'generated_assets'/revision
    destination.parent.mkdir(parents=True,exist_ok=True)
    import fcntl, shutil
    with (destination.parent/'.publish.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if destination.exists():
            # Tool logs/runtime output may differ; source identity never does.
            if json.loads((destination/'generated.json').read_text()) != generated or sha(destination/'source.usda') != sha(source):
                raise ValueError('immutable generated source collision')
        else:
            with tempfile.TemporaryDirectory(dir=destination.parent,prefix='.publish-') as temporary:
                staging=Path(temporary)/'asset';staging.mkdir()
                shutil.copyfile(source,staging/'source.usda');write(staging/'generated.json',generated)
                os.replace(staging,destination)
    descriptor={'kind':'generated_package','manifest_path':str(destination/'generated.json'),
                'manifest_sha256':sha(destination/'generated.json'),'revision':revision}
    dimensions=([p['length_m'],p['width_m'],p['thickness_m']] if recipe_id=='guide_plate_v1' else
                [p['interior_width_m']+2*p['wall_thickness_m'],p['interior_depth_m']+2*p['wall_thickness_m'],p['interior_height_m']+p['floor_thickness_m']])
    record=AssetRecord(ref=ref,title='Parametric '+('guide plate' if recipe_id=='guide_plate_v1' else 'open receiver'),category='guide' if recipe_id=='guide_plate_v1' else 'container',format='usda',entry_path='source.usda',
        dimensions_m=dimensions,
        license={'status':'known','license':'Apache-2.0','basis':'project-owned shipped template; preserve generator notices'},
        availability={'granularity':'generated','estimated_download_bytes':0,'acquisition':descriptor},
        provenance={'generator':'sand3d','reviewed_commit':COMMIT,'generated_manifest_sha256':descriptor['manifest_sha256'],'identity':identity},
        evidence_level='declared',capabilities={})
    detail=CatalogStore(config['index_directory']).remember(record)
    return {'asset_ref':ref.to_dict(),'generated_manifest_path':descriptor['manifest_path'],
            'generated_manifest_sha256':descriptor['manifest_sha256'],'detail_ref':detail,
            'actual_download_bytes':0,'physics_status':'not_prepared'}
