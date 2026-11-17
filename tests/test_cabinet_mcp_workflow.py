"""The compact client workflow must retain real evidence and fail closed."""
import asyncio
import hashlib
import importlib
import json
from pathlib import Path

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
        return self.results.pop(0)


def test_journal_persists_complete_mcp_responses_and_rejects_tool_errors(tmp_path):
    mod = module(); session = Session([Result({'id': 'chosen', 'metadata': 'x' * 10000}),
                                      Result({'message': 'dependency missing'}, is_error=True)])
    journal = mod.MCPJournal(session, tmp_path)
    assert asyncio.run(journal.call('catalog_search', {'query': 'cabinet'}))['id'] == 'chosen'
    saved = json.loads(next(tmp_path.glob('*catalog_search.json')).read_text())
    assert saved['response']['structuredContent']['metadata'] == 'x' * 10000
    with pytest.raises(mod.WorkflowError, match='asset_prepare'):
        asyncio.run(journal.call('asset_prepare', {'plan_id': 'pinned'}))
    assert len(list(tmp_path.glob('*.json'))) == 2


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
    (package/'__init__.py').write_text('installed')
    wheel=tmp_path/'plugin.whl';wheel.write_bytes(b'actual')
    identity={'module_path':str(package/'__init__.py'),'build_info':{'wheel_sha256':hashlib.sha256(b'actual').hexdigest(),'source_clean':True}}
    (plugin/'server/build-info.json').write_text(json.dumps(identity['build_info']))
    mod.check_identity(identity, plugin, wheel)
    with pytest.raises(mod.WorkflowError, match='wheel'):
        mod.check_identity({**identity, 'build_info':{'wheel_sha256':'0'*64,'source_clean':True}},plugin,wheel)
    with pytest.raises(mod.WorkflowError, match='installed'):
        mod.check_identity({**identity, 'module_path':str(tmp_path/'checkout/simscene/__init__.py')},plugin,wheel)
