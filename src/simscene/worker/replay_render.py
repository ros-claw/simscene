"""Isaac renderer for recorded-pose replay; timeline stays stopped.

Run only with the Isaac SDK Python. Per-frame provenance calls this a replay,
not a new native physical recording. Source layers are never saved or edited.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simscene.replay import sha

p = argparse.ArgumentParser()
p.add_argument('request', type=Path)
p.add_argument('--request-sha256', required=True)
a = p.parse_args()
if sha(a.request) != a.request_sha256:
    raise ValueError('replay request changed')
request = json.loads(a.request.read_text())
if request['schema'] != 'simscene.recorded_pose_replay.v1':
    raise ValueError('unsupported replay request')
run = Path(request['source_run_directory'])
if sha(request['poses_path']) != request['poses_sha256']:
    raise ValueError('recorded pose extraction changed')
for name in ('spec.json', 'scene.usda', 'run-lock.json', 'evidence-lock.json'):
    if sha(run/name) != request['source_sha256'][name]:
        raise ValueError('source metadata changed')
from isaacsim import SimulationApp
exit_code = 0
app = SimulationApp({'headless': True, 'multi_gpu': False, 'fast_shutdown': True, 'active_gpu': int(os.getenv('SIMSCENE_GPU', '0')),
                     'renderer': 'RealTimePathTracing'})
encoder = None
try:
    import numpy as np
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    import carb
    from pxr import Gf, Usd, UsdGeom, UsdPhysics
    from isaacsim.core.simulation_manager import SimulationManager
    from simscene.worker.render_settings import configure, check
    from simscene.video_color import SRGB_TO_REC709
    timeline = omni.timeline.get_timeline_interface(); timeline.stop()
    if not omni.usd.get_context().open_stage(str(run/'scene.usda')):
        raise RuntimeError('cannot open source USD')
    stage = omni.usd.get_context().get_stage()
    stage.SetEditTarget(stage.GetSessionLayer())
    spec = json.loads((run/'spec.json').read_text())
    zero_steps = SimulationManager.get_num_physics_steps()
    zero_time = SimulationManager.get_simulation_time()
    if zero_steps != 0:
        raise RuntimeError('replay must not start a physics task')

    def update():
        if timeline.is_playing():
            raise RuntimeError('physics timeline must stay stopped')
        app.update()
        if SimulationManager.get_num_physics_steps() != zero_steps or SimulationManager.get_simulation_time() != zero_time:
            raise RuntimeError('physics advanced during camera-only replay')

    from simscene.worker.spawn import spawn
    for name, obj in spec['objects'].items():
        if obj.get('dynamic') and obj.get('spawn_step', 0) and not stage.GetPrimAtPath('/World/'+name.replace('-', '_')):
            spawn(stage, name, obj)
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr().Set(False)
        if prim.IsA(UsdPhysics.Joint):
            UsdPhysics.Joint(prim).CreateJointEnabledAttr().Set(False)
    capture = spec.get('presentation', {}).get('capture', {})
    config = {'renderer': 'RealTimePathTracing', 'anti_aliasing': capture.get('anti_aliasing', 'dlss_quality'),
              'depth_of_field': False, 'motion_blur': False, 'exposure_mode': 'manual', 'exposure_ev': capture.get('exposure_ev', 0)}
    render_settings = configure(carb.settings.get_settings(), config, update=update)
    archive = np.load(request['poses_path'], allow_pickle=False)
    steps, poses, present = archive['steps'], archive['poses'], archive['present']
    index = {int(n): i for i, n in enumerate(steps)}
    ops = []
    for path in request['body_paths']:
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise RuntimeError('source rigid root missing: '+path)
        xform = UsdGeom.Xformable(prim)
        ordered = xform.GetOrderedXformOps()
        translate = next((op for op in ordered if op.GetOpType() == UsdGeom.XformOp.TypeTranslate), None)
        orient = next((op for op in ordered if op.GetOpType() == UsdGeom.XformOp.TypeOrient), None)
        if not translate or not orient:
            raise RuntimeError('replay requires authored root translate/orient operations')
        ops.append((translate, orient, UsdGeom.Imageable(prim)))
    root = a.request.parent
    if (root/'render-complete.json').exists():
        raise ValueError('preserve prior replay outputs')
    camera = UsdGeom.Camera.Define(stage, '/World/RecordedPoseCamera')
    camera.CreateFStopAttr().Set(0); camera.CreateClippingRangeAttr().Set(Gf.Vec2f(.01, 1000))
    camera_op = UsdGeom.Xformable(camera.GetPrim()).AddTransformOp()
    rendered = []
    for shot in request['shots']:
        out = root/shot['id']; out.mkdir(exist_ok=False)
        width, height = shot.get('resolution', [1920, 1080])
        camera.CreateFocalLengthAttr().Set(shot['camera'].get('focal_length_mm', 45)/100)
        camera.CreateHorizontalApertureAttr().Set(.36)
        camera.CreateVerticalApertureAttr().Set(.36*height/width)
        product = rep.create.render_product(str(camera.GetPath()), (width, height))
        rgb = rep.AnnotatorRegistry.get_annotator('rgb'); rgb.attach(product)
        path = out/(shot['id']+'.mp4')
        log = (out/'ffmpeg.log').open('wb')
        command = ['ffmpeg', '-loglevel', 'warning', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                   '-s', f'{width}x{height}', '-r', str(shot['playback_fps']), '-i', '-', '-an',
                   '-vf', SRGB_TO_REC709, '-c:v', 'libx264', '-threads', '2', '-crf', '17', '-preset', 'medium',
                   '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709', '-color_trc', 'bt709',
                   '-color_primaries', 'bt709', '-movflags', '+faststart', str(path)]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        with (out/'frames.jsonl').open('x') as manifest:
            for frame_id, step in enumerate(shot['source_steps']):
                row = index[step]
                for j, (translate, orient, imageable) in enumerate(ops):
                    if not present[row, j]:
                        imageable.MakeInvisible(); continue
                    imageable.MakeVisible(); values = poses[row, j]
                    translate.Set(Gf.Vec3d(*[float(x) for x in values[:3]]))
                    q = Gf.Quatf(float(values[3]), Gf.Vec3f(*[float(x) for x in values[4:]]))
                    orient.Set(q)
                cfg = shot['camera']
                eye, target = cfg.get('position'), cfg.get('target')
                if 'follow_body' in cfg:
                    body = request['body_paths'].index('/World/'+cfg['follow_body'].replace('-', '_'))
                    if not present[row, body]:
                        raise ValueError('camera subject is not present at this source step')
                    pos = poses[row, body, :3]
                    eye = [float(x+y) for x, y in zip(pos, cfg['eye_offset'])]
                    target = [float(x+y) for x, y in zip(pos, cfg.get('target_offset', [0, 0, 0]))]
                camera_op.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1)).GetInverse())
                for _ in range(shot.get('render_updates', 6) if frame_id else 60):
                    update()
                # Replicator's explicit zero-delta capture renders a changed
                # USD state on a stopped timeline and waits for this payload.
                rep.orchestrator.step(rt_subframes=3, delta_time=0.0,
                                      pause_timeline=True, wait_for_render=True)
                if (timeline.is_playing() or SimulationManager.get_num_physics_steps() != zero_steps
                        or SimulationManager.get_simulation_time() != zero_time):
                    raise RuntimeError('physics advanced during zero-delta replay capture')
                frame = rgb.get_data()
                if frame is None or np.asarray(frame).shape[:2] != (height, width):
                    raise RuntimeError('RGB annotator is not ready; no frame was filled or repeated')
                frame = np.asarray(frame)[:, :, :3].astype(np.uint8)
                encoder.stdin.write(frame.tobytes())
                if frame_id == 0 or frame_id % 90 == 0:
                    from PIL import Image
                    Image.fromarray(frame).save(out/f'frame-{frame_id:05d}.png')
                manifest.write(json.dumps({'frame_id': frame_id, 'source_physics_step': step,
                    'source_sim_time_s': step/60, 'playback_time_s': frame_id/shot['playback_fps'],
                    'source_run_id': request['source_run_id'], 'camera': shot['id'],
                    'playback_speed': shot['playback_speed'], 'new_physics_steps': SimulationManager.get_num_physics_steps(),
                    'camera_position_m': eye, 'camera_target_m': target,
                    'provenance': 'new camera render of exact recorded rigid poses; not original native-camera recording'})+'\n')
                manifest.flush()
        encoder.stdin.close(); code = encoder.wait(timeout=120); encoder = None; log.close()
        if code:
            raise RuntimeError('replay video encoder failed')
        rgb.detach(product); product.destroy()
        rendered.append({'shot_id': shot['id'], 'path': str(path), 'sha256': sha(path),
                         'frames': len(shot['source_steps']), 'duration_s': shot['duration_s'],
                         'playback_speed': shot['playback_speed'], 'frame_map': str(out/'frames.jsonl')})
    check(carb.settings.get_settings(), render_settings['expected'])
    record = {'schema': 'simscene.recorded_pose_render_receipt.v1', 'request_sha256': a.request_sha256,
              'source_run_id': request['source_run_id'], 'new_physics_steps': SimulationManager.get_num_physics_steps(),
              'new_physics_runs': 0, 'source_pose_interpolation': False, 'source_layers_saved': False,
              'videos': rendered, 'render_settings': render_settings,
              'scope': request['scope'], 'visual_review': 'pending actual decoded frame and moving-sequence review'}
    (root/'render-complete.json').write_text(json.dumps(record, indent=2)+'\n')
except BaseException:
    exit_code = 1
    (a.request.parent/'render-failure.json').write_text(json.dumps({'error': traceback.format_exc(),
        'scope': 'Replay rendering failed; no completion or physics acceptance claimed.'}, indent=2)+'\n')
    raise
finally:
    if encoder is not None:
        if encoder.stdin and not encoder.stdin.closed:
            encoder.stdin.close()
        if encoder.poll() is None:
            encoder.terminate(); encoder.wait()
    app.close(exit_code=exit_code)
