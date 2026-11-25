"""A request retry reconnects to its frozen runtime, even if config changes."""
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from simscene.generation import jobs
from simscene.generation.sand3d import COMMIT, parameters
from simscene.recipes.io import _generation_intent


def _runtime():
    return {'schema_version':1,'python':'/old/runtime/python','reviewed_commit':COMMIT,
            'observed':{'sand3d_commit':COMMIT,'sand3d_fingerprint':'fixed'}}


def test_new_generation_replay_never_depends_on_current_runtime(tmp_path):
    runtime=tmp_path/'runtime.json';runtime.write_text(json.dumps(_runtime()))
    config={'home':str(tmp_path/'state'),'index_directory':str(tmp_path/'index'),'generation_runtime':str(runtime)}
    with patch('simscene.generation.jobs.subprocess.Popen') as launch, patch('simscene.jobs._process_identity',return_value={'start_ticks':123}):
        launch.return_value.pid=999
        first=jobs.start('guide_plate_v1',{},'reconnect',config=config)
        replacement=_runtime();replacement['python']='/changed/runtime/python';runtime.write_text(json.dumps(replacement))
        assert jobs.start('guide_plate_v1',{},'reconnect',config=config)['job_id']==first['job_id']
        runtime.unlink()
        assert jobs.start('guide_plate_v1',{},'reconnect',config=config)['replayed'] is True
        with pytest.raises(ValueError,match='different job parameters'):
            jobs.start('guide_plate_v1',{'length_m':.7},'reconnect',config=config)
        with pytest.raises(ValueError,match='runtime_unavailable'):
            jobs.start('guide_plate_v1',{},'new-request',config=config)
        assert launch.call_count==1


def test_legacy_request_replays_after_original_runtime_disappears(tmp_path):
    home=tmp_path/'state';job_id='gen-'+'a'*32;root=home/'generation_jobs'/job_id;root.mkdir(parents=True)
    payload={'operation':'asset_generate','recipe_id':'guide_plate_v1','parameters':parameters('guide_plate_v1',{}),'runtime':_runtime()}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    receipt={'job_id':job_id,'type':'asset_generation','recipe_id':'guide_plate_v1'}
    (root/'task.json').write_text(json.dumps(payload))
    (root/'job.json').write_text(json.dumps(dict(receipt,state='queued',request_id='legacy',request_payload_sha256=digest)))
    directory=home/'job-requests';directory.mkdir()
    (directory/'legacy.json').write_text(json.dumps({'payload_sha256':digest,'state':'started','result':receipt}))
    config={'home':str(home),'index_directory':str(tmp_path/'index'),'generation_runtime':str(tmp_path/'removed.json')}
    with patch('simscene.generation.jobs.subprocess.Popen') as launch:
        resumed=jobs.start('guide_plate_v1',{},'legacy',config=config)
        assert resumed==dict(receipt,replayed=True)
        with pytest.raises(ValueError,match='different job parameters'):
            jobs.start('guide_plate_v1',{'length_m':.7},'legacy',config=config)
        launch.assert_not_called()


def test_missing_reservation_does_not_prove_a_started_worker_never_existed(tmp_path):
    runtime=tmp_path/'runtime.json';runtime.write_text(json.dumps(_runtime()))
    home=tmp_path/'state';directory=home/'job-requests';directory.mkdir(parents=True)
    payload={'operation':'asset_generate','recipe_id':'guide_plate_v1','parameters':parameters('guide_plate_v1',{})}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    (directory/'uncertain.json').write_text(json.dumps({'payload_sha256':digest,'state':'starting'}))
    config={'home':str(home),'generation_runtime':str(runtime)}
    with patch('simscene.generation.jobs.subprocess.Popen') as launch:
        with pytest.raises(ValueError,match='outcome is uncertain'):
            jobs.start('guide_plate_v1',{},'uncertain',config=config)
        launch.assert_not_called()
    assert json.loads((directory/'uncertain.json').read_text())['state']=='starting'


def test_missing_runtime_on_new_request_does_not_poison_a_retry(tmp_path):
    runtime=tmp_path/'runtime.json'
    config={'home':str(tmp_path/'state'),'generation_runtime':str(runtime)}
    with patch('simscene.generation.jobs.subprocess.Popen') as launch, patch('simscene.jobs._process_identity',return_value={'start_ticks':123}):
        launch.return_value.pid=999
        with pytest.raises(ValueError,match='runtime_unavailable'):
            jobs.start('guide_plate_v1',{},'later',config=config)
        runtime.write_text(json.dumps(_runtime()))
        assert jobs.start('guide_plate_v1',{},'later',config=config)['replayed'] is False
        assert launch.call_count==1


def _portable_intent(runtime):
    template=files('simscene.generation').joinpath('templates/guide_plate_v1.py').read_bytes()
    identity={'recipe_id':'guide_plate_v1','parameters':parameters('guide_plate_v1',{}),'seed':0,
              'template_sha256':hashlib.sha256(template).hexdigest(),'toolchain':runtime}
    return _generation_intent(identity,{'generator':'sand3d','reviewed_commit':COMMIT})


def test_portable_lock_compared_to_runtime_actually_frozen_before_launch(tmp_path):
    original=_runtime();intent=_portable_intent(original)
    changed=_runtime();changed['observed']['sand3d_fingerprint']='changed'
    runtime=tmp_path/'runtime.json';runtime.write_text(json.dumps(changed))
    config={'home':str(tmp_path/'state'),'generation_runtime':str(runtime)}
    with patch('simscene.generation.jobs.subprocess.Popen') as launch:
        with pytest.raises(ValueError,match='portable lock'):
            jobs.start('guide_plate_v1',{},'changed-runtime',config=config,expected_intent=intent)
        launch.assert_not_called()


def test_portable_lock_checks_the_copied_template_before_launch(tmp_path):
    runtime=tmp_path/'runtime.json';runtime.write_text(json.dumps(_runtime()))
    config={'home':str(tmp_path/'state'),'generation_runtime':str(runtime)}
    intent=_portable_intent(_runtime());copytree=shutil.copytree
    def changed_copy(src,dst,*args,**kwargs):
        result=copytree(src,dst,*args,**kwargs)
        template=Path(dst)/'generation/templates/guide_plate_v1.py'
        if template.is_file():template.write_text('# altered after earlier preflight\n')
        return result
    with patch('simscene.generation.jobs.shutil.copytree',side_effect=changed_copy),patch('simscene.generation.jobs.subprocess.Popen') as launch:
        with pytest.raises(ValueError,match='portable lock'):
            jobs.start('guide_plate_v1',{},'changed-template',config=config,expected_intent=intent)
        launch.assert_not_called()
