"""The portable example must retain its intended one-command counterfactual."""
import copy
import json
from pathlib import Path

from simscene.verification.articulated_asset_two_joint import _commands, validate_case


EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'usdcraft_two_drawer'


def test_drawer_case_and_control_keep_a_single_declared_causal_difference():
    positive = json.loads((EXAMPLE / 'recipe.json').read_text())
    control = json.loads((EXAMPLE / 'recipe-control.json').read_text())
    case = json.loads((EXAMPLE / 'case.json').read_text())
    selection = json.loads((EXAMPLE / 'assets.lock.json').read_text())['assets']['cabinet']
    obj = case['objects']['cabinet']
    assert obj['prepared_manifest_sha256'] == '${cabinet.manifest_sha256}'
    assert obj['source_ref'] == '${cabinet.source_ref}'
    obj['prepared_manifest_sha256'] = 'a' * 64
    obj['source_ref'] = selection['source_ref']
    validate_case(case)
    positive_ops = copy.deepcopy(positive['operations'])
    cabinet = next(op for op in positive_ops if op.get('id') == 'cabinet')
    commands = cabinet['object']['mechanism']['commands']
    assert commands == _commands(obj['joints'], obj['phases'])
    removed = commands.pop()
    assert removed['joint_id'] == obj['phases'][1]['joint_id']
    assert removed['trigger'] == {'type': 'at_step', 'physics_step': obj['phases'][1]['command_step']}
    assert positive_ops == control['operations']
    assert selection['profile_id'] == 'articulated_prop_v2'
    assert selection['source_ref']['asset_id'] == 'ds_R022_02'
