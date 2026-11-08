"""CPU launcher checks: preserve pinned case bytes before a complete replay.

The launcher imports a real SceneStore but the simulation job is substituted;
these tests do not start Isaac or establish any physical outcome.
"""
import hashlib
import json
import sys
import types
from pathlib import Path
import pytest

from experiments.export_run_project import LAUNCHER
from simscene.scene import SceneStore


def launch(tmp_path, monkeypatch, case_bytes):
    project = tmp_path / 'moved-project'
    project.mkdir()
    (project / 'project.json').write_text(json.dumps({'default_steps':7800, 'seed':0}))
    (project / 'scene.json').write_text(json.dumps({'objects':{'table':{
        'kind':'box', 'size':[1, 1, .1], 'collision':True}}}))
    if case_bytes is not None:
        (project / 'case.json').write_bytes(case_bytes)
    calls = []

    def start(scene_id, steps, seed, **kwargs):
        path = kwargs.get('case_path')
        calls.append({'scene_id':scene_id, 'steps':steps, 'seed':seed,
                      'kwargs':kwargs, 'case_bytes':Path(path).read_bytes() if path else None,
                      'scene':SceneStore().get(scene_id)})
        return {'job_id':'cpu-test-only'}

    jobs = types.ModuleType('simscene.jobs')
    jobs.start = start
    jobs.status = lambda job_id: {'state':'completed',
        'result_file':str(project/'state/runs/synthetic-only/result.json')}
    monkeypatch.setitem(sys.modules, 'simscene.jobs', jobs)
    monkeypatch.setenv('SIMSCENE_HOME', str(tmp_path / 'initial-home'))
    monkeypatch.setattr(sys, 'argv', [str(project / 'run_project.py')])
    monkeypatch.setattr(sys, 'path', list(sys.path))
    exec(compile(LAUNCHER, str(project / 'run_project.py'), 'exec'),
         {'__file__':str(project / 'run_project.py'), '__name__':'__main__'})
    assert len(calls) == 1
    return project, calls[0]


def test_unbound_case_is_pinned_byte_for_byte(tmp_path, monkeypatch):
    original = b'{\n   "schema" : "cpu.export.test", "other" : [2, 1]\n}\n'
    project, call = launch(tmp_path, monkeypatch, original)
    assert call['kwargs']['case_path'] == str(project / 'case.json')
    assert 'case' not in call['kwargs']
    assert call['case_bytes'] == original
    assert (project / 'case.json').read_bytes() == original
    assert call['steps'] == 7800 and call['seed'] == 0
    assert not list((project / 'state').glob('*.case.json'))


def test_legacy_scene_hash_rebind_is_explicit_and_does_not_replace_case(tmp_path, monkeypatch, capsys):
    original = b'{\n "schema":"cpu.export.test", "source_scene_sha256":"old-scene"\n}\n'
    project, call = launch(tmp_path, monkeypatch, original)
    rebound = Path(call['kwargs']['case_path'])
    assert rebound != project / 'case.json'
    assert rebound.parent == project / 'state'
    assert (project / 'case.json').read_bytes() == original
    expected = hashlib.sha256(json.dumps(call['scene'], sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    assert json.loads(call['case_bytes'])['source_scene_sha256'] == expected
    messages = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    notice = next(row['project_case_rebound'] for row in messages if 'project_case_rebound' in row)
    assert notice['original_sha256'] == hashlib.sha256(original).hexdigest()
    assert notice['rebound_file'] == str(rebound)
    assert notice['rebound_sha256'] == hashlib.sha256(call['case_bytes']).hexdigest()


def test_no_case_does_not_manufacture_an_acceptance_case(tmp_path, monkeypatch):
    project, call = launch(tmp_path, monkeypatch, None)
    assert call['kwargs']['case_path'] is None
    assert call['case_bytes'] is None
    assert not (project / 'case.json').exists()


@pytest.mark.parametrize('schema', ['simscene.passive_network.v1', 'simscene.passive_network.v2'])
@pytest.mark.parametrize('passed', [False, True])
def test_replayed_network_is_verified_and_returns_its_real_verdict(tmp_path, monkeypatch, schema, passed):
    original = json.dumps({'schema':schema}, indent=3).encode()+b'\n'
    verified = []
    checker = types.ModuleType('simscene.verification.case_runner')
    def evaluate(directory):
        verified.append(directory)
        assert (tmp_path/'moved-project/case.json').read_bytes() == original
        return {'passed':passed}
    checker.evaluate = evaluate
    monkeypatch.setitem(sys.modules, 'simscene.verification.case_runner', checker)
    with pytest.raises(SystemExit) as exit:
        launch(tmp_path, monkeypatch, original)
    assert exit.value.code == (0 if passed else 1)
    assert verified == [tmp_path/'moved-project/state/runs/synthetic-only']
