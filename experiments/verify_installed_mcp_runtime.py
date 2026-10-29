"""Smoke-test an installed MCP launcher against the installed example scene."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if len(sys.argv)!=3:
    raise SystemExit('usage: verify_installed_mcp_runtime.py LAUNCHER OUTPUT_DIRECTORY')
launcher,out=Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()
out.mkdir(parents=True,exist_ok=True)

def data(result):
    if result.isError:raise RuntimeError(result.content[0].text)
    return result.structuredContent or json.loads(result.content[0].text)

async def main():
    env=dict(os.environ,SIMSCENE_ISAAC_PYTHON='/data/omniverse/isaac-sim-6.2.0/python.sh',
             SIMSCENE_PHYSICS_DEVICE='cpu',CUDA_VISIBLE_DEVICES='0')
    parameters=StdioServerParameters(command='/usr/bin/python3.10',args=[str(launcher)],env=env)
    async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            job=data(await session.call_tool('simulation_start',{'scene_id':'three_arm_online_example',
                'steps':120,'seed':17,'request_id':launcher.parent.parent.name+'-installed-runtime-smoke'}))
            while True:
                status=data(await session.call_tool('job_status',{'job_id':job['job_id']}))
                if status['state'] not in ('queued','running','paused'):break
                await asyncio.sleep(3)
            lock=data(await session.call_tool('run_verify_lock',{'job_id':job['job_id']}))
            evidence=data(await session.call_tool('run_verify_evidence',{'job_id':job['job_id']}))
            shot=await session.call_tool('scene_observe',{'job_id':job['job_id'],'camera':'overview'})
            if shot.isError:raise RuntimeError(shot.content[0].text)
            image=next((x for x in shot.content if getattr(x,'type',None)=='image'),None)
            if image is not None:(out/'runtime-smoke.png').write_bytes(base64.b64decode(image.data))
            checks={'completed':status['state']=='completed','observed_exit_zero':status.get('exit_code')==0 and status.get('exit_code_inferred') is False,
                    'steps':(status.get('result') or {}).get('actual_physics_steps')==120,
                    'input_lock':lock.get('passed') is True,'output_lock':evidence.get('passed') is True and not evidence.get('partial'),
                    'rendered_image':image is not None}
            report={'job':job,'checks':checks,'passed':all(checks.values()),
                    'scope':'Installed MCP launcher, actual Isaac 6.2 120-step load/render run; not a sorting acceptance.'}
            (out/'runtime-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report),flush=True)
            if not report['passed']:raise SystemExit(1)
asyncio.run(main())
