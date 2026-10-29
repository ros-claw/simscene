"""Exercise derived inline case, archiving and counters through real MCP.

The scene must already be built by build_three_arm_auto_case_probe.py. This
case is derived from that scene and supplied bin bounds; the probe does not
claim independent acceptance. Run only when the Isaac GPU is free.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from simscene.scene import SceneStore

scene=SceneStore().get('stream')
fixed=json.loads(Path('tests/fixtures/three_arm_stream18_audited_case.json').read_text())
bins={}
for entry in fixed['objects']:
    bins.setdefault(entry['class_label'],{'min':entry['bin_min'],'max':entry['bin_max'],'pass_x':entry['pass_x']})
forbidden=['belt']+[name for name in scene['objects'] if name.startswith('bin_')]
root=SceneStore().path
async def execute():
    server=StdioServerParameters(command=sys.executable,args=['-m','simscene.cli','mcp'],env=dict(os.environ))
    async with stdio_client(server) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            async def call(name,args):
                response=await session.call_tool(name,args)
                if response.isError:raise RuntimeError(name+': '+str(response.content))
                return response.structuredContent or json.loads(response.content[0].text)
            proposal=await call('scene_plan_stream_case',{'scene_id':'stream','belt_id':'belt','bins':bins,'forbidden_objects':forbidden})
            (root/'auto-case-proposal.json').write_text(json.dumps(proposal,indent=2)+'\n')
            job=await call('simulation_start',{'scene_id':'stream','steps':12000,'seed':17,
                        'case':proposal['case'],'archive_verified_objects':True})
            while True:
                state=await call('job_status',{'job_id':job['job_id']})
                if state['state'] not in ('queued','running','paused'):break
                await asyncio.sleep(3)
            directory=root/'runs'/job['run_id']
            (directory/'job-status.json').write_text(json.dumps(state,indent=2)+'\n')
            if state['state']!='completed' or state.get('exit_code')!=0:
                print(json.dumps({'passed':False,'directory':str(directory),'state':state['state']}));return 1
            report=await call('run_verify',{'job_id':job['job_id']})
            (directory/'auto-case-verification.json').write_text(json.dumps(report,indent=2)+'\n')
            observation=await call('run_observe',{'job_id':job['job_id']})
            (directory/'last-observation.json').write_text(json.dumps(observation,indent=2)+'\n')
            passed=bool(report['passed'] and report['case_pinned_to_run'] and report['archive_ledger_verified']
                        and report['ledger']['correct']==3 and observation.get('verified_counts',{}).get('total')==3)
            print(json.dumps({'passed':passed,'directory':str(directory),'correct':report['ledger']['correct'],
                              'case_pinned':report['case_pinned_to_run'],'archive_ledger_verified':report['archive_ledger_verified'],
                              'scope':'scene-derived case, not independent acceptance'},indent=2))
            return 0 if passed else 1
raise SystemExit(asyncio.run(execute()))
