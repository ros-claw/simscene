"""Keep the generated-plate example a controlled parameter comparison."""
import copy
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT=Path(__file__).resolve().parents[1]/'examples'/'usdcraft_sdk_guide'


def test_generated_plate_example_changes_only_its_prepared_role():
    short=json.loads((ROOT/'recipe-short.json').read_text())
    long=json.loads((ROOT/'recipe-long.json').read_text())
    case=json.loads((ROOT/'case.json').read_text())
    lock=json.loads((ROOT/'assets.lock.json').read_text())['assets']
    assert case['seed']==17 and case['physics_dt_s']==1/60 and case['physics_device']=='cpu'
    left=copy.deepcopy(short['operations']);right=copy.deepcopy(long['operations'])
    first=next(op for op in left if op.get('id')=='plate')['object']
    second=next(op for op in right if op.get('id')=='plate')['object']
    assert first.pop('asset_role')=='short' and second.pop('asset_role')=='long'
    assert left==right
    ball=next(op for op in left if op.get('id')=='ball')['object']
    assert ball['physics']['enable_ccd'] is True
    for role,length in (('short',.5),('long',.7)):
        item=lock[role];condition=case['assets'][role]
        assert item['source_ref']['source_id']=='local-usdcraft-sdk'
        assert item['generation']['parameters']['length_m']==length==condition['length_m']
        assert item['source_sha256']==condition['source_sha256']
        assert condition['manifest_sha256']=='${'+role+'.manifest_sha256}'
        assert condition['source_ref']=='${'+role+'.source_ref}'
        assert item['parameters']['source_physics_policy']=='replace_visual_only'
        assert item['parameters']['static_proxy']['size_m']==[length,.18,.015]


@pytest.mark.skipif(not os.getenv('SIMSCENE_SDK_PAIR_FIXTURE'),reason='requires independently recorded Isaac pair')
def test_real_pair_checker_rejects_equal_but_wrong_seed_device_and_initial_scene():
    fixture=json.loads(Path(os.environ['SIMSCENE_SDK_PAIR_FIXTURE']).read_text())
    short=Path(fixture['short']);long=Path(fixture['long']);case=Path(fixture['case'])
    spec=importlib.util.spec_from_file_location('sdk_guide_check',ROOT/'check_pair.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.check(short,long,case)['passed']
    read_text=Path.read_text
    for targets,change in (
        ({short/'run-lock.json',long/'run-lock.json'},lambda data:data.update(seed=999,physics_device='gpu')),
        ({short/'spec.json',long/'spec.json'},lambda data:data['objects']['ball'].update(position=[.3,0.,.7])),
        ({short/'result.json'},lambda data:data['samples'][100]['positions']['/World/ball'].__setitem__(2,float('nan'))),
        ({short/'result.json'},lambda data:data['samples'][100].update(absolute_physics_step=-1)),
    ):
        def spoof(path,*args,**kwargs):
            text=read_text(path,*args,**kwargs)
            if path in targets:
                data=json.loads(text);change(data);return json.dumps(data)
            return text
        with patch.object(Path,'read_text',spoof):
            assert not module.check(short,long,case)['passed']
