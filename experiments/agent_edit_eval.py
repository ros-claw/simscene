"""Run one natural-language edit in a fresh isolated Codex session.

The input is the actual scene saved by the earlier agent. This prepares no
replacement solution: the session must edit, run and inspect the scene itself.
The captured before/after specs and run evidence still require independent
verification. Run only when the Isaac GPU is free.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if len(sys.argv) != 5 or sys.argv[3] not in ('swap', 'relocate', 'retime', 'retime_repair', 'relocate_repair'):
    raise SystemExit('usage: agent_edit_eval.py PACKAGE_ROOT SAVED_SCENE_JSON swap|relocate|retime|retime_repair|relocate_repair EMPTY_DIRECTORY')
package = Path(sys.argv[1]).resolve()
source = Path(sys.argv[2]).resolve()
mode = sys.argv[3]
repair = mode.endswith('_repair')
base_mode = mode.removesuffix('_repair')
root = Path(sys.argv[4]).resolve()
if root.exists():
    raise SystemExit('evaluation directory must not exist')
launcher = package/'server'/'launch.py'
if not launcher.is_file() or not source.is_file():
    raise SystemExit('package launcher or source scene missing')
scene = json.loads(source.read_text())
scene_id = scene['scene_id']
if not scene_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in scene_id):
    raise SystemExit('invalid scene ID')
root.mkdir(parents=True)
work = root/'work'; work.mkdir()
state = root/'state'; state.mkdir()
shutil.copyfile(source, root/'before.json')
shutil.copyfile(source, state/(scene_id+'.json'))
case_name = ('agent_retime_repair_case.json' if mode == 'retime_repair' else
             'agent_retime_case.json' if mode == 'retime' else 'agent_route_edit_case.json')
checker_name = ('verify_agent_retime_repair.py' if mode == 'retime_repair' else
                'verify_agent_retime.py' if mode == 'retime' else 'verify_agent_route_edit.py')
case = Path(__file__).resolve().parent.parent/'tests'/'fixtures'/case_name
shutil.copyfile(case, root/'pre_registered_case.json')
(root/'pre_registered_case.sha256').write_text(hashlib.sha256(case.read_bytes()).hexdigest()+'\n')
if mode == 'retime_repair':
    verified = json.loads((source.parent.parent/'verification.json').read_text())
    if verified.get('passed') is not True: raise SystemExit('reference agent scene has not passed its independent checker')
    reference = Path(verified['run_directory'])/'acceptance-case.json'
    shutil.copyfile(reference, root/'reference-case.json')
    (root/'reference-case.sha256').write_text(hashlib.sha256(reference.read_bytes()).hexdigest()+'\n')
checker = Path(__file__).resolve().parent/checker_name
shutil.copyfile(checker, root/'frozen-checker.py')
(root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest()+'\n')
skill = work/'.agents'/'skills'/'build-scene'
skill.parent.mkdir(parents=True)
shutil.copytree(package/'skills'/'build-scene', skill)
prompts = {
    'swap': '交换负责红色和绿色物料的两台机械臂的分拣类别，保持其他功能合理。',
    'relocate': '把红色物料料箱移到对应机械臂的另一侧，重新检查可达性和运动路线。',
    'retime': '把传送带速度降低 25%，并把连续投料间隔增加 50%。',
}
prompt = ('请打开已有 SimScene 场景 '+scene_id+'。'+prompts[base_mode]+
          '请保存修改后的场景，实际运行仿真，观察并检查结果。使用 SimScene 插件工具。'+
          ('如有分拣、运动或碰撞检查失败，请根据实际观察修正受影响的动作并重新运行；保持要求的速度、投料间隔及其他功能。' if repair else ''))
(root/'prompt.txt').write_text(prompt+'\n')
allowed = ['environment_probe', 'asset_inspect_local', 'robot_solve_ik',
           'robot_suggest_configuration', 'robot_plan_pick_cycle', 'scene_open',
           'scene_get', 'scene_apply', 'scene_plan_stream', 'scene_plan_stream_case', 'scene_plan_collision_audit', 'scene_plan_retime', 'scene_plan_interleave', 'scene_plan_synchronize', 'scene_plan_swap_routes', 'scene_plan_translate_group', 'scene_validate', 'scene_export',
           'simulation_start', 'job_status', 'job_cancel', 'simulation_pause', 'simulation_resume', 'run_observe', 'run_contacts', 'scene_observe',
           'run_video_chunk', 'run_verify_lock', 'run_verify', 'run_verify_evidence']
server_env = {'SIMSCENE_HOME': str(state), 'SIMSCENE_CACHE': str(root/'cache'),
              'XDG_CONFIG_HOME': str(root/'config')}
for key in ('SIMSCENE_ISAAC_PYTHON', 'SIMSCENE_PHYSICS_DEVICE', 'CUDA_VISIBLE_DEVICES', 'SIMSCENE_GPU'):
    if key in os.environ:
        server_env[key] = os.environ[key]
config = [f'mcp_servers.simscene.command={json.dumps(sys.executable)}',
          f'mcp_servers.simscene.args={json.dumps([str(launcher)])}',
          'mcp_servers.simscene.default_tools_approval_mode="approve"',
          'mcp_servers.simscene.env={'+','.join(k+'='+json.dumps(v) for k, v in server_env.items())+'}',
          'mcp_servers.simscene.enabled_tools='+json.dumps(allowed)]
cmd = ['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '--json', '--sandbox', 'workspace-write', '-C', str(work)]
for setting in config:
    cmd.extend(['-c', setting])
env = dict(os.environ, **server_env)
hashes = {str(f.relative_to(package)): hashlib.sha256(f.read_bytes()).hexdigest()
          for base in ('server/vendor/simscene', 'skills') for f in (package/base).rglob('*')
          if f.is_file() and '__pycache__' not in f.parts}
(root/'package-hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
metadata = {'client': subprocess.check_output(['codex', '--version'], text=True).strip(),
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'scene_id': scene_id,
            'mode': base_mode, 'evaluation_variant': mode, 'tool_allowlist': allowed, 'mcp_environment': server_env,
            'approval': 'tool access approved only for this isolated evaluation'}
(root/'evaluation-config.json').write_text(json.dumps(metadata, indent=2)+'\n')
with (root/'trace.jsonl').open('w') as trace, (root/'stderr.log').open('w') as err:
    completed = subprocess.run(cmd, input=prompt, text=True, stdout=trace, stderr=err, env=env)
(root/'exit-code.txt').write_text(str(completed.returncode)+'\n')
after = state/(scene_id+'.json')
if after.is_file():
    shutil.copyfile(after, root/'after.json')
    current = json.loads(after.read_text())
    before_objects = scene.get('objects', {}); after_objects = current.get('objects', {})
    changes = {key: {'before': before_objects.get(key), 'after': after_objects.get(key)}
               for key in sorted(set(before_objects)|set(after_objects))
               if before_objects.get(key) != after_objects.get(key)}
    (root/'spec-diff.json').write_text(json.dumps(changes, ensure_ascii=False, indent=2)+'\n')
raise SystemExit(completed.returncode)
