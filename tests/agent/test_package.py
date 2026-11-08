"""Run generated launchers in a directory outside the source checkout."""
import asyncio,json,os,shutil,subprocess,sys,tempfile,unittest,yaml,zipfile
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
        async def check_independent_metadata(root,plugin):
            # A new venv has neither checkout imports nor host site-packages.
            interpreter=root/'isolated-python'
            subprocess.run([sys.executable,'-m','venv','--without-pip',str(interpreter)],check=True)
            python=interpreter/'bin/python'
            vendor=plugin/'server/vendor'
            bootstrap=r"""
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from importlib import metadata,resources
from simscene.catalog.registry import load_registry
from simscene.catalog.models import AssetRef,AssetRecord
from simscene.catalog.store import CatalogStore
root=Path(sys.argv[2]);revision=load_registry().get('abo-glb').metadata_entries[0].revision
ref=AssetRef('abo-glb','original_package_fixture',revision)
record=AssetRecord(ref=ref,title='Original package fixture',format='glb',entry_path='objects/fixture.glb',
 license={'status':'known','license':'CC-BY-4.0'},availability={'status':'declared','estimated_download_bytes':100})
CatalogStore(root/'index').replace_index('abo-glb',[record],revision+':original-package-fixture')
(root/'v2.json').write_text(json.dumps({'index_directory':str(root/'index'),'runtime_manifest':str(root/'missing-runtime')}))
from simscene.recipes.registry import list_recipes
assert list_recipes()['recipes']
assert resources.files('simscene.generation.templates').joinpath('guide_plate_v1.py').is_file()
assert metadata.version('rosclaw-simscene')=='0.2.0.dev1'
from simscene.preparation.glb_convert import predecoder_fingerprint
from simscene.preparation.profiles import PreparationError
try:predecoder_fingerprint(str(root/'missing-decoder'))
except PreparationError as error:assert error.code=='dependency_missing'
else:raise AssertionError('missing optional decoder was reported available')
"""
            env={key:value for key,value in os.environ.items() if not key.startswith(('SIMSCENE_','USD_SEARCH_'))}
            env.update(PYTHONPATH='',PYTHONNOUSERSITE='1',HOME=str(root/'home'),XDG_CONFIG_HOME=str(root/'config'),
                SIMSCENE_HOME=str(root/'state'),SIMSCENE_CACHE=str(root/'cache'),SIMSCENE_V2_CONFIG=str(root/'v2.json'))
            subprocess.run([str(python),'-I','-c',bootstrap,str(vendor),str(root)],cwd=root,env=env,check=True)
            server=StdioServerParameters(command=str(python),args=['-I',str(plugin/'server/launch.py')],env=env,cwd=str(root))
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    names={tool.name for tool in (await session.list_tools()).tools}
                    self.assertTrue({'catalog_search','asset_plan','asset_prepare','catalog_discover','asset_generate','scene_compile_recipe'}<=names)
                    response=await session.read_resource('simscene://catalog/sources')
                    self.assertTrue(json.loads(response.contents[0].text)['sources'])
                    response=await session.call_tool('catalog_search',{'query':'Original package fixture','filters':{'source_ids':['abo-glb']},'limit':1})
                    self.assertFalse(response.isError,str(response))
                    page=json.loads(response.content[0].text);self.assertEqual(len(page['items']),1)
                    unavailable=await session.call_tool('asset_generate',{'recipe_id':'guide_plate_v1','parameters':{}})
                    self.assertTrue(unavailable.isError);self.assertIn('generation_runtime_unavailable',str(unavailable))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            supplied=os.environ.get('SIMSCENE_TEST_PACKAGE_OUTPUT')
            output=Path(supplied).resolve() if supplied else root/'dist'
            if not supplied:
                subprocess.run([sys.executable,str(ROOT/'plugins/build.py'),'--output',str(output),'--use-installed-deps'],check=True,stdout=subprocess.DEVNULL)
            wheels=list((output/'wheels').glob('*.whl'));self.assertEqual(len(wheels),1)
            with zipfile.ZipFile(wheels[0]) as archive:
                members=set(archive.namelist())
                for name in ('simscene/catalog/data/sources.yaml','simscene/recipes/data/recipes.json',
                             'simscene/preparation/data/package-lock.json','simscene/generation/templates/guide_plate_v1.py',
                             'simscene/worker/isaac_run.py','simscene/preparation/worker.py'):
                    self.assertIn(name,members)
                self.assertFalse(any('__pycache__' in name or 'node_modules/' in name or name.endswith('.pyc') for name in members))
            for kind in ('portable','claude','deepseek'):
                stage=root/kind;stage.mkdir()
                plugin=output/kind/'simscene'
                self.assertTrue((plugin/'README.md').is_file())
                for notice in ('LICENSE','NOTICE','OPEN_SOURCE_NOTICES.md'):
                    self.assertTrue((plugin/notice).is_file())
                    self.assertEqual((plugin/notice).read_bytes(),(ROOT/notice).read_bytes())
                info=json.loads((plugin/'server/build-info.json').read_text());self.assertEqual(info['python_version'],'0.2.0.dev1');self.assertEqual(info['plugin_version'],'0.2.0-dev.1')
                if kind=='portable':
                    config=json.loads((plugin/'mcp.json').read_text());self.assertEqual(config['mcpServers']['simscene']['type'],'stdio')
                elif kind=='claude':self.assertTrue((plugin/'.claude-plugin/plugin.json').is_file())
                else:
                    patch=yaml.safe_load((plugin/'cordis.patch.yml').read_text());row=patch[0]['insert'][0]
                    self.assertEqual(row['name'],'@deepseek-ai/dsh-mcp-client')
                    self.assertEqual(row['config']['args'],[str(plugin/'server'/'launch.py')])
                    self.assertEqual(row['config']['cwd'],str(plugin))
                asyncio.run(check(stage,plugin))
                if kind=='portable':asyncio.run(check_independent_metadata(stage,plugin))
            if shutil.which('codex'):
                project=root/'installed-project';project.mkdir()
                codex_home=root/'isolated-codex';codex_home.mkdir()
                isaac=root/'python.sh';isaac.write_text('#!/bin/sh\n')
                destination=root/'installed-simscene'
                env=dict(os.environ,CODEX_HOME=str(codex_home))
                install=subprocess.run([sys.executable,str(output/'portable/simscene/install.py'),
                    '--destination',str(destination),'--project',str(project),
                    '--register-codex','--mcp-name','simscene-v2-package-test','--isaac-python',str(isaac)],
                    env=env,capture_output=True,text=True,check=True)
                result=json.loads(install.stdout)
                self.assertTrue(result['codex_mcp_registered'])
                self.assertFalse(result['native_plugin_installed'])
                self.assertTrue((project/'.agents/skills/build-scene/SKILL.md').is_file())
                asyncio.run(check(project,destination))
