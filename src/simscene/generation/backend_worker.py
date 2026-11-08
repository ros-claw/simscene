"""Executed only by an explicitly configured separate Sand3D interpreter."""
import json
from pathlib import Path
import resource
import sys


def main():
    task = json.loads(Path(sys.argv[1]).read_text())
    # These are real resource caps for trusted shipped templates, not a network
    # or filesystem sandbox and never an external-program execution interface.
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    import bpy
    import sand3d as s3d
    from importlib.metadata import distribution
    direct = json.loads(distribution('sand3d').read_text('direct_url.json') or '{}')
    commit = direct.get('vcs_info',{}).get('commit_id')
    if commit != '0d589a5ba568fd72c8da97f8d039918650608a42':
        raise ValueError('Sand3D distribution must identify the reviewed immutable commit')
    runtime = {'python_version': list(sys.version_info[:3]), 'sand3d_version': s3d.__version__,
               'sand3d_fingerprint': s3d.fingerprint(), 'sand3d_commit': commit,'bpy_version': bpy.app.version_string}
    output = Path(task['output'])
    if task['operation'] == 'probe':
        output.write_text(json.dumps(runtime, sort_keys=True, indent=2)+'\n')
        return
    if task['operation'] != 'generate' or task['recipe_id'] not in {'guide_plate_v1','open_receiver_v1'}:
        raise ValueError('unknown trusted generation task')
    if runtime != task['expected_runtime']:
        raise ValueError('generation runtime changed; explicitly probe again')
    if task['recipe_id']=='guide_plate_v1':
        from simscene.generation.templates.guide_plate_v1 import build
    else:
        from simscene.generation.templates.open_receiver_v1 import build
    model = build(s3d, task['parameters'])
    s3d.export(model, str(output))
    Path(task['runtime_output']).write_text(json.dumps(runtime, sort_keys=True, indent=2)+'\n')


if __name__ == '__main__':
    main()
