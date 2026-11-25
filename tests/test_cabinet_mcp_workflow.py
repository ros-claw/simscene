"""The compact client workflow must retain real evidence and fail closed."""
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import zipfile

import pytest


def module():
    return importlib.import_module('simscene.recipes.cabinet_mcp_workflow')


class Result:
    def __init__(self, value, is_error=False):
        self.structuredContent = value
        self.isError = is_error
        self.content = []
    def model_dump(self, **_):
        return {'structuredContent': self.structuredContent, 'isError': self.isError}


class Session:
    def __init__(self, results):
        self.results = list(results); self.calls = []
    async def call_tool(self, name, args):
        self.calls.append((name, args))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_journal_persists_complete_mcp_responses_and_rejects_tool_errors(tmp_path):
    mod = module(); session = Session([Result({'id': 'chosen', 'metadata': 'x' * 10000}),
                                      Result({'message': 'dependency missing'}, is_error=True)])
    journal = mod.MCPJournal(session, tmp_path)
    assert asyncio.run(journal.call('catalog_search', {'query': 'cabinet'}))['id'] == 'chosen'
    saved = json.loads(next(tmp_path.glob('*catalog_search-response.json')).read_text())
    assert saved['response']['structuredContent']['metadata'] == 'x' * 10000
    with pytest.raises(mod.WorkflowError, match='asset_prepare'):
        asyncio.run(journal.call('asset_prepare', {'plan_id': 'pinned'}))
    assert len(list(tmp_path.glob('*-request.json'))) == 2
    assert len(list(tmp_path.glob('*-response.json'))) == 2


def test_journal_persists_rpc_exception_as_an_incomplete_operation(tmp_path):
    mod = module(); journal = mod.MCPJournal(Session([RuntimeError('budget denied')]), tmp_path)
    with pytest.raises(mod.WorkflowError, match='simulation_start'):
        asyncio.run(journal.call('simulation_start', {'steps': 600}))
    request = json.loads(next(tmp_path.glob('*-request.json')).read_text())
    assert request['arguments']['steps'] == 600
    record = json.loads(next(tmp_path.glob('*-response.json')).read_text())
    assert record['exception']['type'] == 'RuntimeError'
    assert 'budget denied' in record['exception']['message']


def test_wait_uses_real_job_result_and_never_treats_failed_jobs_as_success(tmp_path):
    mod = module()
    good = Session([Result({'state': 'completed'}), Result({'state': 'completed', 'result': {'root': '/asset'}})])
    value = asyncio.run(mod.wait_for_job(mod.MCPJournal(good, tmp_path), 'job-a', tmp_path/'wait.json', 60))
    assert value['result']['root'] == '/asset'
    assert [name for name, _ in good.calls] == ['job_status', 'job_status']
    other = tmp_path/'failed'; other.mkdir()
    failed = Session([Result({'state': 'failed', 'error': 'unavailable'})])
    with pytest.raises(mod.WorkflowError, match='failed'):
        asyncio.run(mod.wait_for_job(mod.MCPJournal(failed, other), 'job-b', other/'wait.json', 60))
    assert len(failed.calls) == 1


def test_identity_rejects_wrong_wheel_or_development_checkout(tmp_path):
    mod = module(); plugin = tmp_path/'plugin'; package=plugin/'server/vendor/simscene'; package.mkdir(parents=True)
    contents = {'__init__.py': b'installed', 'mcp_server.py': b'server', 'worker/isaac_run.py': b'worker',
                'recipes/cabinet_mcp_workflow.py': b'workflow'}
    wheel=tmp_path/'plugin.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        for name, value in contents.items():
            path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            archive.writestr('simscene/'+name,value)
    resource=plugin/'examples/automatic_cabinet_layout/recipe.json';resource.parent.mkdir(parents=True)
    resource.write_text('frozen recipe')
    manifest={'schema':'simscene.packaged_resources.v1','files':{'examples/automatic_cabinet_layout/recipe.json':hashlib.sha256(resource.read_bytes()).hexdigest()}}
    manifest_path=plugin/'server/resource-manifest.json';manifest_path.write_text(json.dumps(manifest))
    info={'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'source_clean':True,
          'resource_manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    identity={'module_path':str(package/'__init__.py'),'build_info':info}
    (plugin/'server/build-info.json').write_text(json.dumps(identity['build_info']))
    mod.check_identity(identity, plugin, wheel)
    (package/'mcp_server.py').write_text('changed server')
    with pytest.raises(mod.WorkflowError, match='wheel'):
        mod.check_identity(identity,plugin,wheel)
    (package/'mcp_server.py').write_bytes(contents['mcp_server.py'])
    resource.write_text('changed recipe')
    with pytest.raises(mod.WorkflowError, match='resource'):
        mod.check_identity(identity,plugin,wheel)
    resource.write_text('frozen recipe')
    with pytest.raises(mod.WorkflowError, match='wheel'):
        mod.check_identity({**identity, 'build_info':{'wheel_sha256':'0'*64,'source_clean':True}},plugin,wheel)
    with pytest.raises(mod.WorkflowError, match='installed'):
        mod.check_identity({**identity, 'module_path':str(tmp_path/'checkout/simscene/__init__.py')},plugin,wheel)


def test_configured_mcp_launcher_cannot_be_silently_bypassed(tmp_path, monkeypatch):
    mod = module(); plugin = tmp_path/'plugin'; configured=tmp_path/'bounded_proxy.py'
    configured.write_text('# bounded MCP launcher\n')
    monkeypatch.setenv('SIMSCENE_MCP_LAUNCHER', str(configured))
    assert mod.select_launcher(plugin, None) == configured.resolve()
    assert mod.select_launcher(plugin, configured) == configured.resolve()
    with pytest.raises(mod.WorkflowError, match='configured MCP launcher'):
        mod.select_launcher(plugin, tmp_path/'unbounded.py')


def test_default_scene_ids_do_not_collide_between_new_workspaces():
    mod = module()
    assert mod.new_scene_id() != mod.new_scene_id()


def test_resume_uses_only_the_original_persisted_physics_request(tmp_path):
    mod = module(); case=tmp_path/'case.json';case.write_text('{}')
    request={'scene_id':'cabinet_123','steps':600,'seed':42,'case_path':str(case),
             'request_id':'cabinet_123-physics'}
    (tmp_path/'physics-request.json').write_text(json.dumps(request))
    assert mod.read_recovery_request(tmp_path) == request
    request['steps']=601
    (tmp_path/'physics-request.json').write_text(json.dumps(request))
    with pytest.raises(mod.WorkflowError, match='recovery'):
        mod.read_recovery_request(tmp_path)


def test_run_must_bind_the_saved_scene_and_revision_before_export(tmp_path):
    mod = module();run=tmp_path/'run';run.mkdir();scene={'id':'cabinet','revision':2,'objects':{}}
    digest=hashlib.sha256(json.dumps(scene,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (run/'run-lock.json').write_text(json.dumps({'source_scene_sha256':digest,'scene_revision':2}))
    mod.check_run_scene(scene,run)
    with pytest.raises(mod.WorkflowError, match='scene'):
        mod.check_run_scene({**scene,'revision':3},run)


def test_video_recovery_reuses_job_status_after_losing_the_start_response(tmp_path):
    mod = module()
    from simscene.video_export_jobs import export_job_id

    movie = tmp_path/'technical.mp4'
    edit = movie.with_suffix('.edit.json')
    movie.write_bytes(b'checked native output')
    edit.write_text('{}')
    request = {'destination': str(movie), 'request_id': 'cabinet-video',
               'segments': [{'camera': 'overview'}], 'output_resolution': [1920, 1080]}
    mod._write(tmp_path/'video-request.json', request)
    expected_job = export_job_id(request['request_id'])
    lost = Session([Result({'state': 'completed'}),
                    Result({'job_id': expected_job, 'state': 'completed', 'completion_confirmed': True,
                            'result': {'video': str(movie), 'edit_map': str(edit),
                                       'video_sha256': mod._sha(movie), 'edit_map_sha256': mod._sha(edit)}})])
    journal = mod.MCPJournal(lost, tmp_path)
    assert asyncio.run(mod.wait_for_export(journal, tmp_path, request, resume=True, collect_only=True))['job_id'] == expected_job
    assert [name for name, _ in lost.calls] == ['job_status', 'job_status']
    assert {args['job_id'] for _, args in lost.calls} == {expected_job}


def test_collection_does_not_start_an_export_without_a_saved_request(tmp_path):
    mod = module()
    session = Session([])
    journal = mod.MCPJournal(session, tmp_path)
    request = {'destination': str(tmp_path/'technical.mp4'), 'request_id': 'cabinet-video'}
    with pytest.raises(mod.WorkflowError, match='no saved video export'):
        asyncio.run(mod.wait_for_export(journal, tmp_path, request, resume=True, collect_only=True))
    assert session.calls == []
    assert not (tmp_path/'video-request.json').exists()


def test_resume_replays_a_reserved_request_that_never_reached_the_server(tmp_path):
    mod = module()
    from simscene.video_export_jobs import export_job_id

    movie = tmp_path/'technical.mp4'
    request = {'destination': str(movie), 'request_id': 'cabinet-video',
               'segments': [{'camera': 'overview'}], 'output_resolution': [1920, 1080]}
    mod._write(tmp_path/'video-request.json', request)
    job_id = export_job_id(request['request_id'])
    edit = movie.with_suffix('.edit.json')
    movie.write_bytes(b'checked native output')
    edit.write_text('{}')
    session = Session([Result({'job_id': job_id}), Result({'state': 'completed'}),
                       Result({'job_id': job_id, 'state': 'completed', 'completion_confirmed': True, 'result': {
                           'video': str(movie), 'edit_map': str(edit),
                           'video_sha256': mod._sha(movie), 'edit_map_sha256': mod._sha(edit)}})])
    journal = mod.MCPJournal(session, tmp_path)
    assert asyncio.run(mod.wait_for_export(journal, tmp_path, request, resume=True))['job_id'] == job_id
    assert session.calls[0] == ('video_export_start', request)
