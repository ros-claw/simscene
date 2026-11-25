"""Fixed examples must be discoverable without claiming a new physics pass."""
from pathlib import Path

from simscene.recipes import registry


ROOT = Path(__file__).resolve().parents[1]


def test_fixed_examples_are_separate_from_compilable_role_recipes():
    assert hasattr(registry, 'list_examples'), 'fixed example registry is not available'
    listing = registry.list_examples()
    assert listing['schema'] == 'simscene.fixed_examples.v1'
    examples = {entry['id']: entry for entry in listing['examples']}
    assert set(examples) == {'first_delivery', 'automatic_cabinet_layout', 'artvip_door',
                             'usdcraft_two_drawer', 'usdcraft_sdk_guide', 'integration_workspace'}
    assert examples['automatic_cabinet_layout']['asset_sources'] == ['usdcraft', 'abo-glb', 'gso-glb']
    assert examples['automatic_cabinet_layout']['runtime_evidence'] == 'prior_example_only'
    assert examples['automatic_cabinet_layout']['operations'] == ['recipe.json']
    assert examples['usdcraft_two_drawer']['operations'] == ['recipe.json', 'recipe-control.json']
    assert all(entry['requires_new_physical_verification'] is True for entry in examples.values())
    assert all(entry['id'] not in {item['recipe_id'] for item in registry.list_recipes()['recipes']}
               for entry in examples.values())
    assert registry.list_recipes()['fixed_examples'] == listing['examples']
    for entry in examples.values():
        directory = ROOT / 'examples' / entry['id']
        for name in [entry['asset_lock'], entry['case'], *entry['operations'], entry['checker']]:
            if name.startswith('builtin:'):
                continue
            assert Path(name).name == name
            assert (directory / name).is_file(), (entry['id'], name)


def test_fixed_example_resource_returns_registry_data():
    from simscene import mcp_server
    import json
    assert hasattr(mcp_server, 'fixed_examples_resource')
    assert json.loads(mcp_server.fixed_examples_resource()) == registry.list_examples()


def test_first_delivery_locks_only_one_real_import_and_builtin_support():
    import json
    from simscene.recipes.io import portable
    from simscene.verification.rigid_asset_smoke import validate_case

    entry = next(e for e in registry.list_examples()['examples'] if e['id'] == 'first_delivery')
    assert entry['asset_sources'] == ['gso-glb']
    assert entry['steps'] == 240
    example = ROOT/'examples/first_delivery'
    lock = portable(json.loads((example/'assets.lock.json').read_text()))['assets']
    assert list(lock) == ['box']
    ops = portable(json.loads((example/'recipe.json').read_text()))['operations']
    assets = {op['id']: op['object'] for op in ops if op.get('object', {}).get('kind') == 'asset'}
    assert set(assets) == {'box'}
    assert assets['box']['dynamic'] and assets['box']['asset_role'] == 'box'
    support = next(op['object'] for op in ops if op.get('id') == 'table')
    assert support['kind'] == 'box' and support['collision'] is True
    case = validate_case(json.loads((example/'case.json').read_text()))
    assert case['objects']['box']['support_actors'] == ['/World/table']
    assert case['objects']['box']['initial_height_m'] == assets['box']['position'][2]
