"""Run the installed 6.0.1 NVIDIA pick-place example headlessly.

This is a diagnostic, not a controller profile or acceptance test. The example
is loaded from the local installation and must remain version-matched.
"""
import types
import json
import os
import sys
import time
from pathlib import Path

root = Path(os.environ['SIMSCENE_ISAAC_ROOT'])
tutorial = root / 'standalone_examples/tutorials/manipulation/tutorial_9_pick_place_cumotion.py'
sys.argv = [str(tutorial), '--headless', '--device', 'cpu']
# The tutorial enables a livestream server when headless; this diagnostic
# uses no livestream and limits rendering to one GPU.
source = tutorial.read_text()
source = source.replace('SimulationApp({"headless": args.headless, "hide_ui": False})',
                        'SimulationApp({"headless": args.headless, "hide_ui": False, "multi_gpu": False, "active_gpu": 0})')
start = source.index('if args.headless:\n    from isaacsim.core.experimental.utils.app import enable_extension')
end = source.index('import isaacsim.core.experimental.utils.app as app_utils', start)
source = source[:start] + source[end:]
mod = types.ModuleType('nvidia_pick_place')
mod.__file__ = str(tutorial)
exec(compile(source, str(tutorial), 'exec'), mod.__dict__)
app = mod.simulation_app
if os.getenv('SIMSCENE_ASSETS_ROOT'):
    async def local_root():
        return os.environ['SIMSCENE_ASSETS_ROOT']
    mod.get_assets_root_path_async = local_root
try:
    from isaacsim.core.simulation_manager import SimulationManager
    import isaacsim.core.experimental.utils.app as app_utils
    from pxr import UsdGeom
    import omni.usd
    SimulationManager.setup_simulation(dt=1.0/60.0, device='cpu')
    scenario = mod.UR10ePickPlace()
    future = app.run_coroutine(scenario.setup_scene(), run_until_complete=False)
    deadline = time.monotonic() + 120
    while not future.done() and time.monotonic() < deadline:
        app.update()
    if not future.done(): raise RuntimeError('official example scene setup timed out')
    future.result()
    app_utils.play(); app.update()
    scenario.initialize_after_play()
    stage = omni.usd.get_context().get_stage()
    cube = stage.GetPrimAtPath('/World/cube')
    samples = []
    start = SimulationManager.get_num_physics_steps()
    for frame in range(1800):
        app.update()
        scenario.forward()
        if frame % 30 == 0:
            position = list(UsdGeom.XformCache().GetLocalToWorldTransform(cube).ExtractTranslation())
            samples.append({'frame':frame,'phase':scenario._event,'cube_position':position})
        if scenario.is_done(): break
    result = {'steps':SimulationManager.get_num_physics_steps()-start, 'phases_completed':scenario._event,
              'done':scenario.is_done(), 'samples':samples, 'note':'Observed cube positions are not by themselves grasp or placement verification'}
    print('SIMSCENE_RESULT=' + json.dumps(result), flush=True)
    app_utils.stop()
except Exception:
    import traceback
    traceback.print_exc()
    sys.stderr.flush()
    raise
finally:
    app.close()
