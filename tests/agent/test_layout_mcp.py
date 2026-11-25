"""Exercise the new proposal and revision-safe edit over the actual MCP transport."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_proposal_does_not_edit_until_atomic_apply():
    async def exercise(root):
        bootstrap = '''
from simscene import layout_synthesis
from simscene.mcp_server import server
def backend(request):
    return {"schema":"simscene.scene_synthesizer.placements.v1", "seed":request["seed"],
            "backend":{"name":"scene_synthesizer", "version":"1.15.0", "python":"3.10",
                       "platform":"Linux-test", "native_versions":{"geos":"3.13.1"},
                       "geometry":"render-bounds box proxies; original USD not imported",
                       "dependency_versions":{"numpy":"2", "trimesh":"5", "python-fcl":"0.7",
                                              "shapely":"2", "rtree":"1", "scipy":"1", "networkx":"3"}},
            "placements":[{"id":item["id"], "offset_xy":[-.3 + .6 * i, 0.]}
                          for i,item in enumerate(request["items"])]}
layout_synthesis._run_backend = backend
server.run(transport="stdio")
'''
        env = dict(os.environ, SIMSCENE_HOME=str(root))
        server = StdioServerParameters(command=sys.executable, args=['-c', bootstrap], env=env)
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert tools['scene_plan_layout'].annotations.readOnlyHint
                assert not (await session.call_tool('scene_open', {'scene_id': 'layout_test'})).isError
                objects = {
                    'bench': {'kind': 'box', 'size': [2, 1, .1], 'position': [0, 0, .5], 'collision': True},
                    'a': {'kind': 'box', 'size': [.2, .2, .2], 'position': [3, 0, 1], 'dynamic': True},
                    'b': {'kind': 'box', 'size': [.2, .2, .2], 'position': [4, 0, 1], 'dynamic': True},
                }
                setup = await session.call_tool('scene_apply', {
                    'scene_id': 'layout_test', 'base_revision': 0, 'request_id': 'setup',
                    'operations': [{'op': 'add', 'id': key, 'object': value} for key, value in objects.items()]})
                assert not setup.isError
                for field, invalid in [('seed', True), ('seed', 1.0), ('seed', '9'),
                                       ('clearance_m', False), ('clearance_m', '0.01'),
                                       ('gap_m', False), ('gap_m', '0.05')]:
                    bad = await session.call_tool('scene_plan_layout', {
                        'scene_id': 'layout_test', 'ids': ['a', 'b'], 'support': 'bench', field: invalid})
                    assert bad.isError, (field, invalid)
                result = await session.call_tool('scene_plan_layout', {
                    'scene_id': 'layout_test', 'ids': ['a', 'b'], 'support': 'bench', 'seed': 9})
                assert not result.isError
                plan = result.structuredContent or json.loads(result.content[0].text)
                assert plan['scene_id'] == 'layout_test' and plan['base_revision'] == 1
                assert plan['physics_tested'] is False
                before_result = await session.call_tool('scene_get', {'scene_id': 'layout_test'})
                before = before_result.structuredContent or json.loads(before_result.content[0].text)
                assert before['objects']['a']['position'] == [3, 0, 1]
                assert before['revision'] == 1
                applied = await session.call_tool('scene_apply', {
                    'scene_id': 'layout_test', 'base_revision': plan['base_revision'],
                    'request_id': 'apply_layout', 'operations': plan['operations']})
                assert not applied.isError
                after_result = await session.call_tool('scene_get', {'scene_id': 'layout_test'})
                after = after_result.structuredContent or json.loads(after_result.content[0].text)
                assert after['objects']['a']['position'] == plan['placements'][0]['position_m']
                assert after['revision'] == 2
                stale = await session.call_tool('scene_apply', {
                    'scene_id': 'layout_test', 'base_revision': plan['base_revision'],
                    'request_id': 'stale_layout', 'operations': plan['operations']})
                assert stale.isError and 'revision conflict' in stale.content[0].text
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(exercise(Path(directory)))
