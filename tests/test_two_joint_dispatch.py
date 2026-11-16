import json
from unittest.mock import Mock,patch

import pytest

from simscene.verification import case_runner


def test_two_joint_schema_dispatches_to_its_own_sealed_verifier(tmp_path):
    case=tmp_path/'case.json';case.write_text(json.dumps({'schema':'simscene.articulated_asset_two_joint.v1'}))
    fake=Mock();fake.verify_run.return_value={'passed':False}
    with patch.object(case_runner.importlib,'import_module',return_value=fake) as load:
        result=case_runner.evaluate(tmp_path,case)
    assert load.call_args.args[0]=='.articulated_asset_two_joint'
    assert result['case_type']=='articulated_asset_two_joint'
    with pytest.raises(ValueError):
        case_runner.evaluate(tmp_path,case,'parallel')


def test_two_joint_paired_mode_requires_and_dispatches_positive_reference(tmp_path):
    case=tmp_path/'case.json';case.write_text(json.dumps({'schema':'simscene.articulated_asset_two_joint.v1'}))
    reference=tmp_path/'positive';reference.mkdir()
    fake=Mock();fake.verify_pair.return_value={'passed':True}
    with patch.object(case_runner.importlib,'import_module',return_value=fake) as load:
        result=case_runner.evaluate(tmp_path,case,mode='missing_second_joint_drive',reference_run=reference)
    assert load.call_args.args[0]=='.articulated_asset_two_joint_pair'
    fake.verify_pair.assert_called_once_with(reference,tmp_path,case)
    assert result['passed'] and result['case_type']=='articulated_asset_two_joint'
    with pytest.raises(ValueError):
        case_runner.evaluate(tmp_path,case,mode='missing_second_joint_drive')
