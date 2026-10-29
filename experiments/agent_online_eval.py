"""Run a fresh real Codex session against a built plugin in an isolated workspace.

This is an opt-in integration experiment: it contacts the public asset service,
downloads selected assets and starts a real Isaac worker. Run on an idle GPU.
It makes no changes to user-wide Codex configuration or approval settings.
"""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path

if len(sys.argv)!=3:
    raise SystemExit('usage: agent_online_eval.py PACKAGE_ROOT EMPTY_EVAL_DIRECTORY')
package=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
if root.exists():raise SystemExit('evaluation directory must not exist')
root.mkdir(parents=True);(root/'work').mkdir();(root/'state').mkdir()
checker=Path(__file__).resolve().parent/'verify_agent_online.py'
shutil.copyfile(checker,root/'frozen-checker.py')
(root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest()+'\n')
launcher=package/'server'/'launch.py'
if not launcher.is_file():raise SystemExit('packaged MCP launcher is missing')
skill=root/'work'/'.agents'/'skills'/'build-scene';skill.parent.mkdir(parents=True)
shutil.copytree(package/'skills'/'build-scene',skill)
hashes={str(f.relative_to(package)):hashlib.sha256(f.read_bytes()).hexdigest()
        for base in ('server/vendor/simscene','skills') for f in (package/base).rglob('*')
        if f.is_file() and '__pycache__' not in f.parts}
(root/'package-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
prompt=('请从网上找到一个适合场景的工业输送带，检查并选用资产，'
        '搭建有地面、照明和观察相机的场景，运行仿真并观察结果，'
        '必要时根据观察改进。请保存场景并说明实际结果。'
        '请仅通过 SimScene 插件工具搜索、检查、获取资产和构建运行；'
        '检查依赖和预计大小，优先选择体积合适且依赖完整的候选；'
        '选中资产后等待获取任务完成，使用返回的路径。')
(root/'prompt.txt').write_text(prompt+'\n')
allowed=['environment_probe','asset_search','asset_thumbnail','asset_inspect','asset_acquire',
         'asset_inspect_local','scene_open','scene_get','scene_apply','scene_validate','scene_export',
         'simulation_start','job_status','job_cancel','run_observe','scene_observe','run_verify_lock','run_verify_evidence']
server_env={'SIMSCENE_HOME':str(root/'state'),'SIMSCENE_CACHE':str(root/'cache'), 'XDG_CONFIG_HOME':str(root/'config')}
for name in ('SIMSCENE_ISAAC_PYTHON','SIMSCENE_PHYSICS_DEVICE','CUDA_VISIBLE_DEVICES','SIMSCENE_GPU'):
    if name in os.environ:server_env[name]=os.environ[name]
config=[f'mcp_servers.simscene.command={json.dumps(sys.executable)}',
        f'mcp_servers.simscene.args={json.dumps([str(launcher)])}',
        'mcp_servers.simscene.default_tools_approval_mode="approve"',
        'mcp_servers.simscene.env={'+','.join(k+'='+json.dumps(v) for k,v in server_env.items())+'}',
        'mcp_servers.simscene.enabled_tools='+json.dumps(allowed)]
cmd=['codex','exec','--skip-git-repo-check','--ephemeral','--json','--sandbox','workspace-write','-C',str(root/'work')]
for setting in config:cmd.extend(['-c',setting])
env=dict(os.environ,SIMSCENE_HOME=str(root/'state'),SIMSCENE_CACHE=str(root/'cache'),
         XDG_CONFIG_HOME=str(root/'config'))
metadata={'client':'codex CLI','client_version':subprocess.check_output(['codex','--version'],text=True).strip(),
          'package':str(package),'tool_allowlist':allowed,'approval':'explicitly approved for this isolated session only',
          'mcp_environment':server_env,'gpu':env.get('CUDA_VISIBLE_DEVICES'),'physics_device':env.get('SIMSCENE_PHYSICS_DEVICE','cpu')}
(root/'evaluation-config.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
with (root/'trace.jsonl').open('w') as trace,(root/'stderr.log').open('w') as err:
    completed=subprocess.run(cmd,input=prompt,text=True,stdout=trace,stderr=err,env=env)
(root/'exit-code.txt').write_text(str(completed.returncode)+'\n')
raise SystemExit(completed.returncode)
