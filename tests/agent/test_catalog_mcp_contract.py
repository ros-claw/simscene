"""V2 additions over the real stdio transport, with local metadata and no SDK launch.

An optional SIMSCENE_MCP_BASELINE_FILE compares all legacy schemas against an
external observation. Machine-specific baseline documents are never repo fixtures.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import site
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LEGACY_TOOLS = frozenset('''environment_probe environment_configure asset_search
huggingface_search_datasets huggingface_list_assets huggingface_acquire_asset
asset_thumbnail asset_inspect asset_inspect_local asset_acquire robot_solve_ik
robot_prepare_profile robot_suggest_configuration robot_plan_pick_cycle scene_open
scene_get scene_apply scene_measure scene_plan_rope scene_plan_presentation
run_presentation_events video_export video_inspect scene_plan_stream
scene_plan_stream_case scene_plan_collision_audit scene_plan_synchronize
scene_plan_retime scene_plan_interleave scene_plan_swap_routes
scene_plan_translate_group scene_validate scene_export simulation_start job_status
run_observe run_contacts run_verify_lock run_verify run_verify_passive_suite
run_verify_evidence run_video_chunk scene_observe job_cancel simulation_pause
simulation_resume'''.split())
NEW_TOOLS = frozenset({'catalog_search', 'asset_plan', 'asset_prepare', 'catalog_discover', 'scene_compile_recipe', 'asset_generate'})


def nullable(kind, title):
    value = {'type': kind}
    if kind == 'object':
        value['additionalProperties'] = True
    return {'anyOf': [value, {'type': 'null'}], 'default': None, 'title': title}


def schema(name, properties, required):
    return {'properties': properties, 'required': required, 'title': name + 'Arguments', 'type': 'object'}

NEW_SCHEMAS = {
    'asset_generate': schema('asset_generate', {
        'recipe_id': {'title': 'Recipe Id', 'type': 'string'},
        'parameters': {'additionalProperties': True, 'title': 'Parameters', 'type': 'object'},
        'request_id': nullable('string', 'Request Id')}, ['recipe_id', 'parameters']),
    'catalog_discover': schema('catalog_discover', {
        'query': {'title': 'Query', 'type': 'string'},
        'budget': nullable('object', 'Budget'),
        'cursor': nullable('string', 'Cursor')}, ['query']),
    'scene_compile_recipe': schema('scene_compile_recipe', {
        'scene_id': {'title': 'Scene Id', 'type': 'string'},
        'recipe_id': {'title': 'Recipe Id', 'type': 'string'},
        'parameters': {'additionalProperties': True, 'title': 'Parameters', 'type': 'object'},
        'bindings': {'additionalProperties': True, 'title': 'Bindings', 'type': 'object'}}, ['scene_id', 'recipe_id', 'parameters', 'bindings']),
    'catalog_search': schema('catalog_search', {
        'query': {'title': 'Query', 'type': 'string'},
        'filters': nullable('object', 'Filters'),
        'limit': {'default': 8, 'title': 'Limit', 'type': 'integer'},
        'cursor': nullable('string', 'Cursor')}, ['query']),
    'asset_plan': schema('asset_plan', {
        'asset_ref': {'additionalProperties': True, 'title': 'Asset Ref', 'type': 'object'},
        'profile_id': {'default': 'visual_prop_v1', 'title': 'Profile Id', 'type': 'string'},
        'parameters': nullable('object', 'Parameters'),
        'budget_bytes': nullable('integer', 'Budget Bytes')}, ['asset_ref']),
    'asset_prepare': schema('asset_prepare', {
        'plan_id': {'title': 'Plan Id', 'type': 'string'},
        'request_id': nullable('string', 'Request Id')}, ['plan_id']),
}
READ_NETWORK = {'title': None, 'readOnlyHint': True, 'destructiveHint': None,
                'idempotentHint': None, 'openWorldHint': True}

# Only the provider delay is synthetic. Requests still run through the actual
# registered wrappers, search facade, SQLite provider, planner and job rejection.
BOOTSTRAP = r'''
import os,time,urllib.request
from pathlib import Path
from simscene.catalog.providers.abo import ABOProvider
from simscene.preparation import worker
from simscene.mcp_server import server
root=Path(os.environ['SIMSCENE_TEST_GATE'])
original=ABOProvider.search

def gated_search(self,request):
    if request.query == 'slow fixture':
        (root/'entered').write_text('entered')
        deadline=time.monotonic()+8
        while not (root/'release').is_file():
            if time.monotonic()>deadline:raise RuntimeError('test gate deadline exceeded')
            time.sleep(.01)
    return original(self,request)

def forbidden(*args,**kwargs):
    raise AssertionError('contract test attempted network or SDK execution')
ABOProvider.search=gated_search
urllib.request.OpenerDirector.open=forbidden
worker.run_sdk=forbidden
server.run(transport='stdio')
'''


def content(result):
    return result.structuredContent or json.loads(result.content[0].text)


class CatalogMCPContract(unittest.IsolatedAsyncioTestCase):
    async def test_tools_sources_cached_plan_and_nonblocking_search(self):
        from simscene.catalog.models import AssetRecord, AssetRef
        from simscene.catalog.registry import load_registry
        from simscene.catalog.store import CatalogStore
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('home', 'state', 'cache', 'config', 'index'):
                (root / name).mkdir()
            registry = load_registry()
            revision = registry.get('abo-glb').metadata_entries[0].revision
            ref = AssetRef('abo-glb', 'original-fixture', revision)
            record = AssetRecord(ref=ref, title='Original fixture box', format='glb',
                                 entry_path='objects/original-fixture.glb',
                                 license={'status': 'known', 'license': 'CC0-1.0'},
                                 availability={'estimated_download_bytes': 1024, 'granularity': 'single_file'})
            store = CatalogStore(root / 'index')
            store.replace_index('abo-glb', [record], revision + ':contract-fixture')
            settings = root / 'v2.json'
            settings.write_text(json.dumps({'index_directory': str(root / 'index'),
                                            'runtime_manifest': str(root / 'missing-runtime.json')}))
            env = dict(os.environ, HOME=str(root / 'home'), SIMSCENE_HOME=str(root / 'state'),
                       SIMSCENE_CACHE=str(root / 'cache'), XDG_CONFIG_HOME=str(root / 'config'),
                       SIMSCENE_V2_CONFIG=str(settings), SIMSCENE_TEST_GATE=str(root))
            # A fresh HOME must not hide dependencies installed in the parent
            # interpreter's user site; derive this path at runtime, never freeze it.
            env['PYTHONPATH']=os.pathsep.join(filter(None,[os.environ.get('PYTHONPATH'),site.getusersitepackages()]))
            for name in ('SIMSCENE_GLTF_TRANSFORM_PREFIX', 'SIMSCENE_ISAAC_PYTHON',
                         'USD_SEARCH_API_TOKEN', 'USD_SEARCH_API_USERNAME', 'USD_SEARCH_API_PASSWORD'):
                env.pop(name, None)
            server = StdioServerParameters(command=sys.executable, args=['-c', BOOTSTRAP], env=env)
            async with stdio_client(server) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    self.assertEqual(len(LEGACY_TOOLS), 46)
                    self.assertEqual(set(tools), LEGACY_TOOLS | NEW_TOOLS)
                    for name, expected in NEW_SCHEMAS.items():
                        self.assertEqual(tools[name].inputSchema, expected, name)
                    self.assertEqual(tools['catalog_search'].annotations.model_dump(), READ_NETWORK)
                    self.assertIsNone(tools['asset_plan'].annotations)
                    self.assertIsNone(tools['asset_prepare'].annotations)
                    self.assertEqual(tools['asset_acquire'].inputSchema, schema('asset_acquire', {
                        'asset_url': {'title': 'Asset Url', 'type': 'string'},
                        'refresh': {'default': False, 'title': 'Refresh', 'type': 'boolean'}}, ['asset_url']))
                    self.assertIsNone(tools['asset_acquire'].annotations)
                    self.assertEqual(tools['scene_get'].inputSchema, schema('scene_get', {
                        'scene_id': {'title': 'Scene Id', 'type': 'string'}}, ['scene_id']))
                    self.assertTrue(tools['scene_get'].annotations.readOnlyHint)
                    self.assertFalse(tools['scene_get'].annotations.openWorldHint)
                    self.assertTrue(tools['asset_search'].annotations.readOnlyHint)
                    self.assertTrue(tools['asset_search'].annotations.openWorldHint)
                    self.assertEqual(tools['job_status'].inputSchema['required'], ['job_id'])
                    self.assertEqual(tools['job_status'].inputSchema['properties']['wait_seconds']['default'], 0)
                    baseline_path = os.environ.get('SIMSCENE_MCP_BASELINE_FILE')
                    if baseline_path:
                        baseline = json.loads(Path(baseline_path).read_text())
                        self.assertEqual(set(baseline), LEGACY_TOOLS)
                        for name, expected in baseline.items():
                            observed = {'inputSchema': tools[name].inputSchema,
                                        'annotations': tools[name].annotations.model_dump() if tools[name].annotations else None}
                            self.assertEqual(observed, expected, name)
                    resources = await session.list_resources()
                    self.assertIn('simscene://catalog/sources', [str(item.uri) for item in resources.resources])
                    response = await session.read_resource('simscene://catalog/sources')
                    sources = json.loads(response.contents[0].text)
                    self.assertEqual(sources['schema_version'], 1)
                    self.assertTrue({'abo-glb', 'nvidia-usd-search'} <= {s['source_id'] for s in sources['sources']})
                    self.assertTrue(all(s['state'] in {'audited', 'enabled', 'candidate', 'quarantined', 'reference_only'} for s in sources['sources']))
                    searched = await session.call_tool('catalog_search', {'query': 'fixture', 'filters': {'source_ids': ['abo-glb']}, 'limit': 1})
                    self.assertFalse(searched.isError)
                    page = content(searched)
                    self.assertEqual(len(page['items']), 1)
                    self.assertEqual(page['items'][0]['ref'], ref.to_dict())
                    self.assertLessEqual(len(json.dumps(page).encode()), 12 * 1024)
                    planned = await session.call_tool('asset_plan', {'asset_ref': ref.to_dict(),
                        'parameters': {'source_physics_policy': 'reject_if_physics', 'proxy_tolerance_m': .002},
                        'budget_bytes': 2048})
                    self.assertFalse(planned.isError)
                    plan = content(planned)
                    self.assertFalse(plan['ready_to_fetch'])
                    self.assertIn('environment_probe_required', {item['code'] for item in plan['blocking_reasons']})
                    self.assertIsNone(plan['converter_selection'])
                    refused = await session.call_tool('asset_prepare', {'plan_id': plan['plan_id'], 'request_id': 'blocked-plan'})
                    self.assertTrue(refused.isError)
                    self.assertIn('plan_not_ready', refused.content[0].text)
                    self.assertFalse((root / 'state' / 'preparation_jobs').exists())
                    self.assertFalse((await session.call_tool('scene_open', {'scene_id': 'catalog_contract'})).isError)
                    slow = asyncio.create_task(session.call_tool('catalog_search', {
                        'query': 'slow fixture', 'filters': {'source_ids': ['abo-glb']}, 'limit': 1}))
                    try:
                        for _ in range(100):
                            if (root / 'entered').is_file():
                                break
                            await asyncio.sleep(.02)
                        else:
                            self.fail('catalog provider did not enter its bounded test gate')
                        current = await asyncio.wait_for(session.call_tool('scene_get', {'scene_id': 'catalog_contract'}), 2)
                        self.assertFalse(current.isError)
                        self.assertFalse(slow.done(), 'unrelated scene call should finish while catalog provider remains gated')
                    finally:
                        (root / 'release').write_text('release')
                        completed = await asyncio.wait_for(slow, 5)
                    self.assertFalse(completed.isError)
                    self.assertEqual(len(content(completed)['items']), 1)


if __name__ == '__main__':
    unittest.main()
