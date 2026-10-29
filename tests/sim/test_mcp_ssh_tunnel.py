"""Opt-in real Isaac/MCP test over an isolated localhost SSH tunnel."""
import asyncio,getpass,json,os,shutil,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def wait_port(port,proc):
    for _ in range(100):
        if proc.poll() is not None:raise RuntimeError('process exited before listening')
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.1):return
        except OSError:time.sleep(.1)
    raise RuntimeError('server did not start')

@unittest.skipUnless(os.getenv('SIMSCENE_ISAAC_PYTHON') and os.getenv('SIMSCENE_TEST_SSH') and shutil.which('sshd') and shutil.which('ssh-keygen'),'requires Isaac, sshd and explicit opt-in')
class SshIsaacTest(unittest.TestCase):
    def test_remote_style_camera_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);host=root/'host';client=root/'client';host.mkdir();client.mkdir()
            for name in ('host-key','client-key'):
                subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(root/name)],check=True)
            (root/'authorized_keys').write_text((root/'client-key.pub').read_text())
            ssh_port,server_port,tunnel_port=port(),port(),port()
            config='\n'.join([f'Port {ssh_port}','ListenAddress 127.0.0.1',f'HostKey {root}/host-key',f'PidFile {root}/sshd.pid',f'AuthorizedKeysFile {root}/authorized_keys','UsePAM no','PasswordAuthentication no','KbdInteractiveAuthentication no','PubkeyAuthentication yes','StrictModes no','LogLevel ERROR'])+'\n'
            (root/'sshd_config').write_text(config)
            sshd=subprocess.Popen([shutil.which('sshd'),'-D','-e','-f',str(root/'sshd_config')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            server=tunnel=None
            try:
                wait_port(ssh_port,sshd)
                env=dict(os.environ,SIMSCENE_HOME=str(host),NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
                server=subprocess.Popen([sys.executable,'-m','simscene.cli','mcp','--transport','streamable-http','--port',str(server_port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                wait_port(server_port,server)
                tunnel=subprocess.Popen(['ssh','-F','/dev/null','-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-i',str(root/'client-key'),'-p',str(ssh_port),'-L',f'{tunnel_port}:127.0.0.1:{server_port}',getpass.getuser()+'@127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                wait_port(tunnel_port,tunnel)
                async def exercise():
                    async with streamable_http_client(f'http://127.0.0.1:{tunnel_port}/mcp') as (reader,writer,_):
                        async with ClientSession(reader,writer) as session:
                            await session.initialize()
                            async def call(name,args):
                                result=await session.call_tool(name,args)
                                if result.isError:self.fail(str(result.content))
                                return result
                            def body(result):return result.structuredContent or json.loads(result.content[0].text)
                            await call('scene_open',{'scene_id':'remote'})
                            await call('scene_apply',{'scene_id':'remote','base_revision':0,'request_id':'setup','operations':[
                                {'op':'add','id':'box','object':{'kind':'box','position':[0,0,.5],'size':[.2,.2,.2],'dynamic':True}},
                                {'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True}},
                                {'op':'add','id':'sun','object':{'kind':'light','intensity':1500}},
                                {'op':'add','id':'view','object':{'kind':'camera','position':[1.5,1.5,1.5],'record_fps':10}},
                                {'op':'look_at','id':'view','target':[0,0,.3]}]})
                            case=root/'case.json';case.write_text('{"sample":"frozen"}')
                            started=body(await call('simulation_start',{'scene_id':'remote','steps':600,'seed':17,'case_path':str(case)}))
                            job=started['job_id'];self.assertNotEqual(job,started['run_id'])
                            case.write_text('{"sample":"changed"}')
                            for _ in range(300):
                                live=await session.call_tool('run_observe',{'job_id':job})
                                if not live.isError:break
                                await asyncio.sleep(.2)
                            else:self.fail('live observation did not arrive')
                            await call('simulation_pause',{'job_id':job})
                            for _ in range(100):
                                paused=body(await call('job_status',{'job_id':job}))
                                if paused['state']=='paused':break
                                if paused['state']!='running':self.fail(str(paused))
                                await asyncio.sleep(.1)
                            self.assertEqual(paused['state'],'paused')
                            first=body(await call('run_observe',{'job_id':job}))['physics_steps']
                            await asyncio.sleep(.7)
                            self.assertEqual(body(await call('run_observe',{'job_id':job}))['physics_steps'],first)
                            await call('simulation_resume',{'job_id':job})
                            for _ in range(150):
                                status=body(await call('job_status',{'job_id':job}))
                                if status['state'] not in ('running','paused'):break
                                await asyncio.sleep(2)
                            self.assertEqual(status['state'],'completed',str(status))
                            self.assertEqual(status['run_id'],started['run_id'])
                            self.assertTrue(body(await call('run_verify_lock',{'job_id':job}))['passed'])
                            observation=body(await call('run_observe',{'job_id':job}))
                            self.assertIn('/World/box',observation['positions'])
                            image=await call('scene_observe',{'job_id':job,'camera':'view'})
                            self.assertEqual(image.content[0].mimeType,'image/png')
                            chunk=body(await call('run_video_chunk',{'job_id':job,'camera':'view','length':1024}))
                            self.assertGreater(chunk['total_bytes'],1024)
                            self.assertFalse(any(client.rglob('*.usd*')))
                with patch.dict(os.environ,{'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}):asyncio.run(exercise())
            finally:
                for proc in (tunnel,server,sshd):
                    if proc and proc.poll() is None:
                        proc.terminate()
                        try:proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:proc.kill();proc.wait()
