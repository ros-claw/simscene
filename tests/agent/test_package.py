"""Run generated launchers in a directory outside the source checkout."""
import asyncio,json,os,shutil,subprocess,sys,tempfile,unittest,yaml
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[2]
class PackageIntegration(unittest.TestCase):
    def test_packages_launch_and_export_without_checkout_on_pythonpath(self):
        async def check(root,plugin):
            env=dict(os.environ,SIMSCENE_HOME=str(root/'state'),PYTHONPATH='')
            server=StdioServerParameters(command=sys.executable,args=[str(plugin/'server'/'launch.py')],env=env,cwd=str(root))
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    for name,args in [('scene_open',{'scene_id':'package'}),('scene_apply',{'scene_id':'package','base_revision':0,'request_id':'add','operations':[{'op':'add','id':'cube','object':{'kind':'box'}}]}),('scene_export',{'scene_id':'package','destination':str(root/'scene.usda')})]:
                        result=await session.call_tool(name,args)
                        self.assertFalse(result.isError,f'{name}: {result}')
                    self.assertTrue((root/'scene.usda').is_file())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'dist'
            subprocess.run([sys.executable,str(ROOT/'plugins/build.py'),'--output',str(output),'--use-installed-deps'],check=True,stdout=subprocess.DEVNULL)
            for kind in ('portable','claude','deepseek'):
                stage=root/kind;stage.mkdir()
                plugin=output/kind/'simscene'
                self.assertTrue((plugin/'README.md').is_file())
                self.assertTrue((plugin/'LICENSE').is_file())
                if kind=='portable':
                    config=json.loads((plugin/'mcp.json').read_text());self.assertEqual(config['mcpServers']['simscene']['type'],'stdio')
                elif kind=='claude':self.assertTrue((plugin/'.claude-plugin/plugin.json').is_file())
                else:
                    patch=yaml.safe_load((plugin/'cordis.patch.yml').read_text());row=patch[0]['insert'][0]
                    self.assertEqual(row['name'],'@deepseek-ai/dsh-mcp-client')
                    self.assertEqual(row['config']['args'],[str(plugin/'server'/'launch.py')])
                    self.assertEqual(row['config']['cwd'],str(plugin))
                asyncio.run(check(stage,plugin))
            if shutil.which('codex'):
                project=root/'installed-project';project.mkdir()
                codex_home=root/'isolated-codex';codex_home.mkdir()
                isaac=root/'python.sh';isaac.write_text('#!/bin/sh\n')
                destination=root/'installed-simscene'
                env=dict(os.environ,CODEX_HOME=str(codex_home))
                install=subprocess.run([sys.executable,str(output/'portable/simscene/install.py'),
                    '--destination',str(destination),'--project',str(project),
                    '--register-codex','--isaac-python',str(isaac)],
                    env=env,capture_output=True,text=True,check=True)
                result=json.loads(install.stdout)
                self.assertTrue(result['codex_mcp_registered'])
                self.assertFalse(result['native_plugin_installed'])
                self.assertTrue((project/'.agents/skills/build-scene/SKILL.md').is_file())
                asyncio.run(check(project,destination))
