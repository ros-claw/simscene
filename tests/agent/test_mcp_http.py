"""Exercise the HTTP MCP endpoint over loopback."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

class HttpMCPTest(unittest.TestCase):
    def test_http_transport(self):
        with tempfile.TemporaryDirectory() as root:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            proc = subprocess.Popen([sys.executable,'-m','simscene.cli','mcp','--transport','streamable-http','--port',str(port)], env=dict(os.environ,SIMSCENE_HOME=root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    if proc.poll() is not None: self.fail('server exited')
                    try:
                        with socket.create_connection(('127.0.0.1',port), timeout=.1): break
                    except OSError: time.sleep(.1)
                else: self.fail('server did not start')
                async def run():
                    async with streamable_http_client(f'http://127.0.0.1:{port}/mcp') as (read,write,_):
                        async with ClientSession(read,write) as session:
                            await session.initialize()
                            result=await session.call_tool('scene_open',{'scene_id':'http'})
                            self.assertFalse(result.isError)
                            self.assertEqual((result.structuredContent or json.loads(result.content[0].text))['scene_id'],'http')
                with patch.dict(os.environ, {'NO_PROXY':'127.0.0.1,localhost', 'no_proxy':'127.0.0.1,localhost'}):
                    asyncio.run(run())
            finally:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
