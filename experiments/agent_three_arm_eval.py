"""Fresh Codex experiment for the requested three-arm scene (real Isaac)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if len(sys.argv)!=3:raise SystemExit('usage: agent_three_arm_eval.py PACKAGE_ROOT EMPTY_EVAL_DIRECTORY')
package=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
if root.exists():raise SystemExit('evaluation directory must not exist')
launcher=package/'server'/'launch.py'
if not launcher.is_file():raise SystemExit('packaged MCP launcher missing')
root.mkdir(parents=True);work=root/'work';work.mkdir();(root/'state').mkdir()
case=Path(__file__).resolve().parent.parent/'tests'/'fixtures'/'agent_three_arm_case.json'
shutil.copyfile(case,root/'pre_registered_case.json')
(root/'pre_registered_case.sha256').write_text(hashlib.sha256(case.read_bytes()).hexdigest()+'\n')
checker=Path(__file__).resolve().parent/'verify_agent_three_arm.py'
shutil.copyfile(checker,root/'frozen-checker.py')
(root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest()+'\n')
skill=work/'.agents'/'skills'/'build-scene';skill.parent.mkdir(parents=True)
shutil.copytree(package/'skills'/'build-scene',skill)
hashes={str(f.relative_to(package)):hashlib.sha256(f.read_bytes()).hexdigest() for basepath in ('server/vendor/simscene','skills') for f in (package/basepath).rglob('*') if f.is_file() and '__pycache__' not in f.parts}
(root/'package-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
prompt=('在线寻找并使用现成仿真资产，搭建一座明亮、精致的智能分拣工作站，让 Kawasaki RS007L、Franka Panda 和 UR10 三种机械臂沿一条持续运行的传送带错位协作，'
        '分别将不断进入的红、绿、蓝三类小件抓取并放入对应料箱，呈现双指夹持和吸盘搬运两种动作，加入补料滑槽、末端漏料回收区、'
        '跟随真实设备状态变化的指示灯与分拣计数，以及全景、俯视和抓取特写相机，自动运行并检查结果，'
        '保存可继续编辑的场景和一段能够清楚看见真实抓取过程的演示视频。')
(root/'prompt.txt').write_text(prompt+'\n')
allowed=['environment_probe','asset_search','asset_thumbnail','asset_inspect','asset_acquire','asset_inspect_local','robot_prepare_profile','robot_suggest_configuration','robot_plan_pick_cycle','robot_solve_ik',
         'scene_open','scene_get','scene_apply','scene_plan_stream','scene_plan_stream_case','scene_plan_collision_audit','scene_plan_retime','scene_plan_interleave','scene_plan_synchronize','scene_plan_swap_routes','scene_plan_translate_group','scene_validate','scene_export','simulation_start',
         'job_status','job_cancel','simulation_pause','simulation_resume','run_observe','run_contacts','scene_observe','run_video_chunk','run_verify_lock','run_verify','run_verify_evidence']
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
(root/'evaluation-config.json').write_text(json.dumps({'client':subprocess.check_output(['codex','--version'],text=True).strip(),
    'package':str(package),'tool_allowlist':allowed,'mcp_environment':server_env,'assets':'agent discovers and acquires selected online assets',
    'approval':'tool access approved only for this isolated evaluation'},indent=2)+'\n')
with (root/'trace.jsonl').open('w') as trace,(root/'stderr.log').open('w') as err:
    completed=subprocess.run(cmd,input=prompt,text=True,stdout=trace,stderr=err,env=env)
(root/'exit-code.txt').write_text(str(completed.returncode)+'\n')
raise SystemExit(completed.returncode)
