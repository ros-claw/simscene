"""A slow online request must not block unrelated MCP status or scene calls."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import tempfile
import threading
import unittest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_slow_search_does_not_block_scene_get(self):
        entered=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                entered.set();release.wait(10)
                body=json.dumps({'hits':[]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                env=dict(os.environ,SIMSCENE_HOME=root,XDG_CONFIG_HOME=root,
                         USD_SEARCH_API_URL=f'http://127.0.0.1:{http.server_port}',
                         NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
                for name in ('USD_SEARCH_API_TOKEN','USD_SEARCH_API_USERNAME','USD_SEARCH_API_PASSWORD'):
                    env.pop(name,None)
                server=StdioServerParameters(command=sys.executable,args=['-m','simscene.cli','mcp'],env=env)
                async with stdio_client(server) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        opened=await session.call_tool('scene_open',{'scene_id':'concurrency_test'})
                        self.assertFalse(opened.isError)
                        slow=asyncio.create_task(session.call_tool('asset_search',{'query':'conveyor'}))
                        try:
                            self.assertTrue(await asyncio.to_thread(entered.wait,5),'search did not reach server')
                            response=await asyncio.wait_for(session.call_tool('scene_get',{'scene_id':'concurrency_test'}),2)
                            self.assertFalse(response.isError)
                        finally:
                            release.set()
                            result=await asyncio.wait_for(slow,5)
                            self.assertFalse(result.isError)
        finally:
            release.set();http.shutdown();http.server_close();thread.join(timeout=5)

    async def test_cache_locked_simulation_preparation_does_not_block_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'cache'/('a'*64);package.mkdir(parents=True)
            asset=package/'asset.usd';asset.write_text('#usda 1.0\n')
            (package/'simscene-lock.json').write_text('{}')
            runtime=root/'isaac-python';runtime.write_text('unused')
            env=dict(os.environ,SIMSCENE_HOME=str(root/'state'),XDG_CONFIG_HOME=tmp,
                     SIMSCENE_ISAAC_PYTHON=str(runtime))
            server=StdioServerParameters(command=sys.executable,args=['-m','simscene.cli','mcp'],env=env)
            with (root/'cache'/'.cache.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                async with stdio_client(server) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        await session.call_tool('scene_open',{'scene_id':'locked_cache'})
                        applied=await session.call_tool('scene_apply',{'scene_id':'locked_cache','base_revision':0,
                            'request_id':'asset','operations':[{'op':'add','id':'model',
                            'object':{'kind':'asset','asset_path':str(asset)}}]})
                        self.assertFalse(applied.isError)
                        slow=asyncio.create_task(session.call_tool('simulation_start',{'scene_id':'locked_cache','steps':1}))
                        try:
                            for _ in range(100):
                                if list((root/'state'/'runs').glob('*')):break
                                await asyncio.sleep(.05)
                            else:self.fail('simulation preparation did not begin')
                            response=await asyncio.wait_for(session.call_tool('job_status',{'job_id':'not-a-job'}),2)
                            self.assertTrue(response.isError)
                            self.assertIn('job not found',response.content[0].text)
                        finally:
                            fcntl.flock(lock,fcntl.LOCK_UN)
                            result=await asyncio.wait_for(slow,5)
                            self.assertTrue(result.isError)  # deliberately invalid cache lock


if __name__=='__main__':unittest.main()
