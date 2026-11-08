"""Explicit SDK entry point, launched under the existing cooperative GPU queue."""
import json
import os
from pathlib import Path
import platform
import sys


def main():
    # Executing this file would otherwise shadow Python's stdlib inspect with
    # preparation/inspect.py while Kit imports its Python APIs.
    own_directory = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != own_directory]
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    task_path = Path(sys.argv[1]).resolve(); task = json.loads(task_path.read_text())
    from isaacsim import SimulationApp
    app = SimulationApp({'headless':True, 'multi_gpu':False,
                         'active_gpu':int(os.getenv('SIMSCENE_GPU', '0'))})
    try:
        from pxr import Usd
        from simscene.preparation.glb_convert import CONVERTER, probe
        from simscene.preparation.jobs import write
        capabilities = probe()
        # The launcher/version are observed in this actual SDK process.
        sdk_root = Path(os.environ['SIMSCENE_PROBE_SDK_ROOT'])
        target = {'engine':'physx', 'isaac_version':(sdk_root/'VERSION').read_text().strip(),
                  'usd_version':'.'.join(map(str, Usd.GetVersion())), 'platform':platform.system().lower()+'-'+platform.machine()}
        if task['operation'] == 'probe':
            write(task['output'], {'target':target, 'converter':CONVERTER,
                  'predecoder_configuration':capabilities.get('predecoder_configuration'),
                  'observation_source':'actual Isaac SimulationApp and enabled asset_converter extension',
                  'physical_steps':0, 'capabilities':capabilities})
        else:
            plan = task['plan']
            if target != plan['target'] or CONVERTER != plan['converter_selection']:
                raise ValueError('plan_environment_changed: SDK target/converter differs from immutable plan')
            if capabilities.get('predecoder_configuration') != plan.get('converter_environment'):
                raise ValueError('plan_environment_changed: SDK predecoder differs from frozen plan')
            from simscene.preparation import prepare_acquired
            result = prepare_acquired(task['acquired'], plan['profile_id'], plan['parameters'],
                                      plan['target'], task['output_directory'], app=app)
            write(task['output'], result)
    except BaseException as error:
        # Kit fast shutdown can exit before Python prints an uncaught exception.
        # Persist the failure before closing, independent of its process code.
        import traceback
        from simscene.preparation.jobs import write
        write(task_path.parent/'sdk-error.json',{'error':str(error),'code':getattr(error,'code','preparation_failed'),
                                               'traceback':traceback.format_exc()})
        raise
    finally: app.close()


if __name__ == '__main__': main()
