"""Exercise packaged stdio MCP planning against a completed observed run."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

launcher, output = map(Path, sys.argv[1:3])
root = Path('/tmp/simscene-formal-v19-camera-warmup/agent-acceptance/three_arm')

async def main():
    env = dict(os.environ, SIMSCENE_HOME=str(root/'state'), SIMSCENE_CACHE=str(root/'cache'))
    params = StdioServerParameters(command='/usr/bin/python3.10', args=[str(launcher.resolve())], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            item = next(x for x in tools.tools if x.name == 'scene_plan_synchronize')
            probe = await session.call_tool('environment_probe', {})
            if probe.isError:
                raise RuntimeError(str(probe.content))
            environment = probe.structuredContent or json.loads(probe.content[0].text)
            result = await session.call_tool('scene_plan_synchronize', {
                'scene_id': 'tri_arm_sorting', 'job_id': '8ac1e52fd6af429f8a0c75e1cb82235d',
                'ids': [f'feed{i:04d}' for i in range(9)]})
            if result.isError:
                raise RuntimeError(str(result.content))
            plan = result.structuredContent or json.loads(result.content[0].text)
            checks = {'registered_read_only': item.annotations.readOnlyHint is True,
                      'intact_run_plan': plan['class_order'] == ['blue', 'green', 'red'] and plan['interval_steps'] == 1561,
                      'revision_bound': plan['base_revision'] == 35, 'all_items': len(plan['operations']) == 9}
            report = {'passed': all(checks.values()), 'checks': checks, 'tool_count': len(tools.tools),
                      'environment_probe': environment,
                      'proposal': plan, 'scope': 'MCP planning from a completed prior run; not a new physical validation'}
            output.write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({'passed': report['passed'], 'checks': checks, 'tool_count': len(tools.tools)}))
            if not report['passed']:
                raise SystemExit(1)

asyncio.run(main())
