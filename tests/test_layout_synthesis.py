"""The optional layout backend proposes checked, editable scene operations."""
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from simscene.layout_synthesis import plan_layout
from simscene.placement import bounds
from simscene.scene import SceneError


def scene():
    q = math.sqrt(0.5)
    return {'revision': 7, 'objects': {
        'bench': {'kind': 'box', 'size': [2.0, 1.0, 1.0], 'position': [1.0, 2.0, .5], 'collision': True,
                  'orientation_wxyz': [q, 0, 0, q]},
        'cup': {'kind': 'box', 'size': [.2, .2, .1], 'position': [4., 4., 4.],
                'orientation_wxyz': [1, 0, 0, 0], 'dynamic': True},
        'box': {'kind': 'box', 'size': [.2, .2, .2], 'position': [5., 5., 5.], 'dynamic': True},
    }}


def response(positions, seed=9):
    return {'schema': 'simscene.scene_synthesizer.placements.v1', 'seed': seed,
            'backend': {'name': 'scene_synthesizer', 'version': '1.15.0', 'python': '3.10.12',
                        'platform': 'Linux-test', 'native_versions': {'geos': '3.13.1'},
                        'geometry': 'render-bounds box proxies; original USD not imported',
                        'dependency_versions': {'numpy': '2.2.6', 'trimesh': '5.2.1',
                                                'python-fcl': '0.7.0', 'shapely': '2.1.2', 'rtree': '1.4.1',
                                                'scipy': '1.15.3', 'networkx': '3.4.2'}},
            'placements': [{'id': name, 'offset_xy': offset} for name, offset in positions]}


def test_rotated_support_plan_is_editable_and_does_not_modify_scene():
    original = scene()
    before = copy.deepcopy(original)
    with patch('simscene.layout_synthesis._run_backend', return_value=response([
        ('cup', [-.4, 0]), ('box', [.4, 0])])):
        plan = plan_layout(original, ['cup', 'box'], 'bench', seed=9, clearance_m=.03)
    assert original == before
    assert plan['base_revision'] == 7 and plan['physics_tested'] is False
    assert [op['op'] for op in plan['operations']] == ['place_on', 'place_on']
    assert plan['placements'][0]['support_id'] == 'bench'
    assert plan['placements'][0]['position_m'] == pytest.approx([1., 1.6, 1.05])
    assert plan['placements'][0]['orientation_wxyz'] == [1, 0, 0, 0]
    assert plan['placements'][1]['position_m'] == pytest.approx([1., 2.4, 1.1])
    assert 'cup' in plan['operations'][1]['avoid_ids']


def test_plan_identity_binds_source_and_scene_context():
    original = scene()
    other_source = copy.deepcopy(original)
    other_source['objects']['cup']['mass_kg'] = .5
    shifted_support = copy.deepcopy(original)
    shifted_support['objects']['bench']['position'][0] += 3
    other_scene = copy.deepcopy(original)
    other_scene['scene_id'] = 'other_scene'
    response_data = response([('cup', [-.4, 0]), ('box', [.4, 0])])
    with patch('simscene.layout_synthesis._run_backend', return_value=response_data):
        first = plan_layout(original, ['cup', 'box'], 'bench', seed=9)
        again = plan_layout(copy.deepcopy(original), ['cup', 'box'], 'bench', seed=9)
        other = plan_layout(other_source, ['cup', 'box'], 'bench', seed=9)
        shifted = plan_layout(shifted_support, ['cup', 'box'], 'bench', seed=9)
        renamed = plan_layout(other_scene, ['cup', 'box'], 'bench', seed=9)
        gap = plan_layout(original, ['cup', 'box'], 'bench', seed=9, gap_m=.001)
    assert first['plan_sha256'] == again['plan_sha256']
    assert len({p['plan_sha256'] for p in (first, other, shifted, renamed, gap)}) == 5


def test_collision_and_reserved_space_are_rechecked_even_if_backend_claims_success():
    original = scene()
    with patch('simscene.layout_synthesis._run_backend', return_value=response([
        ('cup', [0., 0.]), ('box', [0., 0.])])):
        with pytest.raises(SceneError, match='clearance'):
            plan_layout(original, ['cup', 'box'], 'bench', seed=9)
    with patch('simscene.layout_synthesis._run_backend', return_value=response([
        ('cup', [0., 0.]), ('box', [.4, 0.])])):
        with pytest.raises(SceneError, match='reserved'):
            plan_layout(original, ['cup', 'box'], 'bench', seed=9,
                        keepout_bounds=[{'min': [.8, 1.8, .95], 'max': [1.2, 2.2, 1.3]}])
    assert original == scene()


@pytest.mark.parametrize('output', [
    response([('cup', [0, 0])]),
    response([('cup', [0, 0]), ('cup', [.5, 0])]),
    response([('cup', [float('nan'), 0]), ('box', [.5, 0])]),
    response([('cup', [2., 0]), ('box', [.5, 0])]),
    response([('cup', [0, 0]), ('box', [.5, 0])], seed=10),
])
def test_untrusted_backend_output_fails_closed(output):
    with patch('simscene.layout_synthesis._run_backend', return_value=output):
        with pytest.raises(SceneError):
            plan_layout(scene(), ['cup', 'box'], 'bench', seed=9)


@pytest.mark.parametrize('ids, support, seed', [
    ([], 'bench', 9), (['cup', 'cup'], 'bench', 9), (['cup', 'missing'], 'bench', 9),
    (['cup'], 'cup', 9), (['cup'], 'bench', -1), (['cup'], 'bench', True),
])
def test_invalid_request_never_runs_backend(ids, support, seed):
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError):
            plan_layout(scene(), ids, support, seed=seed)
        backend.assert_not_called()


def test_tilted_support_and_unavailable_runtime_are_reported():
    original = scene()
    original['objects']['bench']['orientation_wxyz'] = [math.sqrt(.5), math.sqrt(.5), 0, 0]
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='horizontal'):
            plan_layout(original, ['cup'], 'bench', seed=9)
        backend.assert_not_called()
    with patch('simscene.layout_synthesis._run_backend', side_effect=SceneError('backend unavailable')):
        with pytest.raises(SceneError, match='backend unavailable'):
            plan_layout(scene(), ['cup'], 'bench', seed=9)


@pytest.mark.parametrize('target', ['stdout', 'stderr'])
def test_worker_output_is_capped_while_it_is_running(target):
    from simscene.layout_synthesis import _bounded_process
    command = [sys.executable, '-c',
               'import os,time; os.write(' + ('1' if target == 'stdout' else '2') + ', b"x"*100000); time.sleep(2)']
    with pytest.raises(SceneError, match='output exceeds limit'):
        _bounded_process(command, b'{}', timeout=3, limit=1024)


def test_bounded_worker_receives_complete_large_input():
    from simscene.layout_synthesis import _bounded_process
    payload = b'x' * 200_000
    code, stdout, stderr = _bounded_process([sys.executable, '-c',
        'import sys; print(len(sys.stdin.buffer.read()))'], payload, timeout=3)
    assert code == 0 and int(stdout) == len(payload) and not stderr


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires POSIX process groups')
def test_worker_descendant_cannot_hold_output_pipes_past_deadline():
    from simscene.layout_synthesis import _bounded_process
    command = [sys.executable, '-c',
               'import os,time; pid=os.fork()\n'
               'if pid: print("{}", flush=True); os._exit(0)\n'
               'time.sleep(2); os.write(1, b"trailing")']
    with pytest.raises(subprocess.TimeoutExpired):
        _bounded_process(command, b'{}', timeout=.25)


def prepared_package(tmp_path, *, support=False, native_dynamic=False):
    from pxr import Gf, Usd, UsdGeom, UsdPhysics
    tmp_path.mkdir()
    asset = tmp_path / 'main.usda'
    stage = Usd.Stage.CreateNew(str(asset))
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, '/Asset')
    stage.SetDefaultPrim(root.GetPrim())
    cube = UsdGeom.Cube.Define(stage, '/Asset/Part')
    cube.CreateSizeAttr(.2)
    cube.AddTranslateOp().Set(Gf.Vec3d(.3, 0, .1))
    if support:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim()).CreateCollisionEnabledAttr(True)
    if native_dynamic:
        UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())
    stage.GetRootLayer().Save()
    manifest = {'schema': 'simscene.prepared_asset.v1', 'schema_version': 1,
                'main': 'main.usda', 'default_prim': '/Asset',
                'profile_id': 'static_fixture_v1' if support else 'visual_prop_v1',
                'files': [{'path': 'main.usda', 'sha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
                           'size_bytes': asset.stat().st_size}],
                'body_map': {'main': {'role': 'static', 'relative_prim_path': 'Part',
                                      'collider_relative_prim_paths': ['Part']}} if support else {}}
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    binding = {'manifest_path': str(manifest_path), 'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    return {'kind': 'asset', 'asset_path': str(asset), 'asset_binding': binding, 'position': [4., 4., 4.]}


def test_imported_usd_root_offset_is_preserved(tmp_path):
    prepared = prepared_package(tmp_path / 'offset')
    asset = tmp_path / 'offset' / 'main.usda'
    original = scene()
    original['objects']['cup'] = prepared
    before = asset.read_bytes()
    with patch('simscene.layout_synthesis._run_backend', return_value=response([('cup', [0., 0.])])):
        plan = plan_layout(original, ['cup'], 'bench', seed=9)
    placed = copy.deepcopy(original)
    placed['objects']['cup']['position'] = plan['placements'][0]['position_m']
    box = bounds(placed['objects']['cup'], placed, 'cup')
    assert [(box['min'][i] + box['max'][i]) / 2 for i in (0, 1)] == pytest.approx([1., 2.])
    assert box['min'][2] == pytest.approx(1.)
    assert placed['objects']['cup']['asset_path'] == str(asset) and asset.read_bytes() == before
    assert plan['source_pins'] == [{'id': 'cup', 'status': 'verified_prepared',
                                    'manifest_sha256': prepared['asset_binding']['manifest_sha256'],
                                    'profile_id': 'visual_prop_v1'}]


def test_assets_require_verified_local_preparation_and_support_physics(tmp_path):
    original = scene()
    for missing_object in ('cup', 'bench'):
        candidate = copy.deepcopy(original)
        candidate['objects'][missing_object] = {'kind': 'asset', 'asset_path': '/missing.usda',
            'position': [0., 0., 0.], 'support_surfaces': {'top': {'min_xy': [-1, -1], 'max_xy': [1, 1], 'z_m': .5}}}
        with patch('simscene.layout_synthesis._run_backend') as backend:
            with pytest.raises(SceneError, match='prepared'):
                plan_layout(candidate, ['cup'], 'bench', support_surface='top' if missing_object == 'bench' else None, seed=9)
            backend.assert_not_called()
    candidate = scene()
    candidate['objects']['bench'] = prepared_package(tmp_path / 'bad_support', support=True, native_dynamic=True)
    candidate['objects']['bench']['support_surfaces'] = {'top': {'min_xy': [-1, -1], 'max_xy': [1, 1], 'z_m': .5}}
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='dynamic or articulated physics'):
            plan_layout(candidate, ['cup'], 'bench', support_surface='top', seed=9)
        backend.assert_not_called()


def test_instanced_imported_support_is_rejected_before_hidden_physics_can_be_missed(tmp_path):
    from pxr import Usd, UsdGeom, UsdPhysics
    package = tmp_path / 'instanced'
    prepared = prepared_package(package, support=True)
    prototype_path = package / 'prototype.usda'
    prototype = Usd.Stage.CreateNew(str(prototype_path))
    root = UsdGeom.Xform.Define(prototype, '/Template')
    prototype.SetDefaultPrim(root.GetPrim())
    moving = UsdGeom.Xform.Define(prototype, '/Template/Moving')
    UsdPhysics.RigidBodyAPI.Apply(moving.GetPrim())
    UsdPhysics.CollisionAPI.Apply(UsdGeom.Cube.Define(prototype, '/Template/Moving/Shape').GetPrim())
    prototype.GetRootLayer().Save()
    asset_path = package / 'main.usda'
    stage = Usd.Stage.Open(str(asset_path))
    instance = UsdGeom.Xform.Define(stage, '/Asset/Inst').GetPrim()
    instance.GetReferences().AddReference('./prototype.usda', '/Template')
    instance.SetInstanceable(True)
    stage.GetRootLayer().Save()
    manifest_path = package / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files'] = [{'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                          'size_bytes': p.stat().st_size} for p in (asset_path, prototype_path)]
    manifest_path.write_text(json.dumps(manifest))
    prepared['asset_binding']['manifest_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    prepared['support_surfaces'] = {'top': {'min_xy': [-1, -1], 'max_xy': [1, 1], 'z_m': .5}}
    original = scene()
    original['objects']['bench'] = prepared
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='instanc'):
            plan_layout(original, ['cup'], 'bench', support_surface='top', seed=9)
        backend.assert_not_called()


def test_dynamic_props_require_a_colliding_support():
    original = scene()
    original['objects']['bench']['collision'] = False
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='collision'):
            plan_layout(original, ['cup'], 'bench', seed=9)
        backend.assert_not_called()


@pytest.mark.parametrize('mutation', ['support_excludes', 'item_excludes', 'item_no_collider', 'compound_without_colliders'])
def test_declared_support_contacts_cannot_be_disabled(mutation):
    original = scene()
    if mutation == 'support_excludes':
        original['objects']['bench']['collision_exclusions'] = ['cup']
    elif mutation == 'item_excludes':
        original['objects']['cup']['collision_exclusions'] = ['bench']
    elif mutation == 'item_no_collider':
        original['objects']['cup']['collision'] = False
    else:
        original['objects']['bench'] = {'kind': 'compound', 'collision': True, 'position': [0, 0, .5],
            'parts': [{'kind': 'box', 'size': [2, 1, 1], 'collision': False}],
            'support_surfaces': {'top': {'min_xy': [-1, -.5], 'max_xy': [1, .5], 'z_m': .5}}}
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='collis'):
            plan_layout(original, ['cup'], 'bench', support_surface='top' if mutation == 'compound_without_colliders' else None, seed=9)
        backend.assert_not_called()


def test_compounds_with_attached_visuals_are_rejected_before_loading_sources():
    original = scene()
    original['objects']['cup'] = {'kind': 'compound', 'position': [0, 0, 1], 'parts': []}
    original['objects']['attached'] = {'kind': 'asset', 'asset_path': '/missing.usda',
                                        'rigid_attachment': {'body': 'cup'}, 'asset_physics': 'visual_only'}
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='attached visuals'):
            plan_layout(original, ['cup'], 'bench', seed=9)
        backend.assert_not_called()


def test_changed_prepared_source_and_partial_backend_provenance_fail_closed(tmp_path):
    original = scene()
    original['objects']['cup'] = prepared_package(tmp_path / 'prop')
    result = response([('cup', [0., 0.])])
    with patch('simscene.layout_synthesis._run_backend', return_value=result):
        plan_layout(original, ['cup'], 'bench', seed=9)
    with open(original['objects']['cup']['asset_path'], 'a') as stream:
        stream.write('\n# changed without changing geometry\n')
    with patch('simscene.layout_synthesis._run_backend') as backend:
        with pytest.raises(SceneError, match='missing or changed'):
            plan_layout(original, ['cup'], 'bench', seed=9)
        backend.assert_not_called()
    incomplete = response([('cup', [0., 0.])])
    del incomplete['backend']['dependency_versions']
    with patch('simscene.layout_synthesis._run_backend', return_value=incomplete):
        with pytest.raises(SceneError, match='invalid response'):
            plan_layout(scene(), ['cup'], 'bench', seed=9)


@pytest.mark.skipif(not os.environ.get('SIMSCENE_LAYOUT_PYTHON'), reason='optional pinned layout backend not configured')
def test_real_backend_is_repeatable_across_processes_and_rejects_impossible_layout():
    original = scene()
    first = plan_layout(original, ['cup', 'box'], 'bench', seed=100)
    again = plan_layout(original, ['cup', 'box'], 'bench', seed=100)
    different = plan_layout(original, ['cup', 'box'], 'bench', seed=101)
    assert first == again
    assert first['placements'] != different['placements']
    assert first['backend']['version'] == '1.15.0'
    original['objects']['bench']['size'] = [.1, .1, 1.]
    before = copy.deepcopy(original)
    with pytest.raises(SceneError, match='no valid proxy placement'):
        plan_layout(original, ['cup'], 'bench', seed=100)
    assert original == before
