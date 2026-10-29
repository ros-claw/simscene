"""Fresh-agent generic workbench experiment; starts real Isaac, so use an idle GPU.

The asset list only supplies a single robot file. No workbench recipe, object
positions, camera path, or robot profile is preloaded into the isolated scene.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: agent_workbench_eval.py PACKAGE_ROOT EMPTY_EVAL_DIRECTORY')
package=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
if root.exists():raise SystemExit('evaluation directory must not exist')
launcher=package/'server'/'launch.py'
if not launcher.is_file():raise SystemExit('packaged MCP launcher missing')
root.mkdir(parents=True);work=root/'work';work.mkdir();(root/'state').mkdir()
case=Path(__file__).resolve().parent.parent/'tests'/'fixtures'/'agent_workbench_case.json'
shutil.copyfile(case,root/'pre_registered_case.json')
(root/'pre_registered_case.sha256').write_text(hashlib.sha256(case.read_bytes()).hexdigest()+'\n')
checker=Path(__file__).resolve().parent/'verify_workbench_eval.py'
shutil.copyfile(checker,root/'frozen-checker.py')
(root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest()+'\n')
skill=work/'.agents'/'skills'/'build-scene';skill.parent.mkdir(parents=True)
shutil.copytree(package/'skills'/'build-scene',skill)
hashes={str(file.relative_to(package)):hashlib.sha256(file.read_bytes()).hexdigest()
        for base in ('server/vendor/simscene','skills') for file in (package/base).rglob('*')
        if file.is_file() and '__pycache__' not in file.parts}
(root/'package-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
asset='/data/omniverse/Assets/Isaac/6.0/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd'
if not Path(asset).is_file():raise SystemExit('local listed asset missing')
prompt=('请搭建一个单机械臂工作台，有两排料盒，并让相机环绕观测。'
        '请运行仿真、观察结果并保存场景。可用资产清单中有一台 Franka Panda，'
        '其仿真端路径为 '+asset+'。请使用 SimScene 工具完成。')
(root/'prompt.txt').write_text(prompt+'\n')
allowed=['environment_probe','asset_inspect_local','robot_prepare_profile','robot_suggest_configuration',
         'scene_open','scene_get','scene_apply','scene_validate','scene_export','simulation_start',
         'job_status','run_observe','scene_observe','run_video_chunk','run_verify_lock']
server_env={'SIMSCENE_HOME':str(root/'state'),'SIMSCENE_CACHE':str(root/'cache'),'XDG_CONFIG_HOME':str(root/'config')}
for name in ('SIMSCENE_ISAAC_PYTHON','SIMSCENE_PHYSICS_DEVICE','CUDA_VISIBLE_DEVICES','SIMSCENE_GPU'):
    if name in os.environ:server_env[name]=os.environ[name]
config=[f'mcp_servers.simscene.command={json.dumps(sys.executable)}',f'mcp_servers.simscene.args={json.dumps([str(launcher)])}',
        'mcp_servers.simscene.default_tools_approval_mode="approve"',
        'mcp_servers.simscene.env={'+','.join(k+'='+json.dumps(v) for k,v in server_env.items())+'}',
        'mcp_servers.simscene.enabled_tools='+json.dumps(allowed)]
cmd=['codex','exec','--skip-git-repo-check','--ephemeral','--json','--sandbox','workspace-write','-C',str(work)]
for setting in config:cmd.extend(['-c',setting])
env=dict(os.environ,SIMSCENE_HOME=str(root/'state'),SIMSCENE_CACHE=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'))
meta={'client':subprocess.check_output(['codex','--version'],text=True).strip(),'package':str(package),
      'tool_allowlist':allowed,'mcp_environment':server_env,'assets':[asset],
      'approval':'tool access approved only for this isolated evaluation'}
(root/'evaluation-config.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
with (root/'trace.jsonl').open('w') as trace,(root/'stderr.log').open('w') as err:
    completed=subprocess.run(cmd,input=prompt,text=True,stdout=trace,stderr=err,env=env)
(root/'exit-code.txt').write_text(str(completed.returncode)+'\n')
raise SystemExit(completed.returncode)
