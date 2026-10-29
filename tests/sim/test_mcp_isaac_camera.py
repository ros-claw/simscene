"""Opt-in actual MCP + Isaac capture; requires SIMSCENE_ISAAC_PYTHON."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@unittest.skipUnless(os.environ.get('SIMSCENE_ISAAC_PYTHON'), 'requires Isaac Sim')
class IsaacMCPTest(unittest.TestCase):
    def test_camera_from_runtime(self):
        async def run(root):
            env = dict(os.environ, SIMSCENE_HOME=root)
            server = StdioServerParameters(command=sys.executable, args=['-m','simscene.cli','mcp'], env=env)
            async with stdio_client(server) as (read, write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    async def call(name,args):
                        result=await session.call_tool(name,args)
                        if result.isError: self.fail(str(result.content))
                        return result
                    await call('scene_open', {'scene_id':'capture'})
                    await call('scene_apply', {'scene_id':'capture','base_revision':0,'request_id':'setup','operations':[
                        {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,.5],'size':[.5,.5,.5],'color':[1,0,0]}},
                        {'op':'add','id':'camera','object':{'kind':'camera','position':[0,0,3]}},
                        {'op':'add','id':'sun','object':{'kind':'light','intensity':3000}}]})
                    result = await call('simulation_start', {'scene_id':'capture','steps':5})
                    info=result.structuredContent or json.loads(result.content[0].text)
                    for _ in range(150):
                        state = await call('job_status', {'job_id':info['job_id']})
                        body = state.structuredContent or json.loads(state.content[0].text)
                        if body['state'] != 'running': break
                        await asyncio.sleep(2)
                    self.assertEqual(body['state'], 'completed', str(body))
                    image = await call('scene_observe', {'job_id':info['job_id'],'camera':'camera'})
                    self.assertEqual(image.content[0].type, 'image')
                    self.assertEqual(image.content[0].mimeType, 'image/png')
                    self.assertGreater(len(image.content[0].data), 1000)
        with tempfile.TemporaryDirectory() as root: asyncio.run(run(root))
