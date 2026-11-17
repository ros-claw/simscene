"""Known joint motion must reserve intermediate space before physics starts."""
import copy
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from simscene.scene import SceneError


def implementation():
    assert importlib.util.find_spec('simscene.recipes.motion_keepouts') is not None, 'motion preflight is unavailable'
    return importlib.import_module('simscene.recipes.motion_keepouts')


def test_revolute_bound_includes_the_intermediate_sweep_not_just_endpoints():
    mod = implementation()
    initial = {'min': [0., .99, -.01], 'max': [.2, 1.01, .01]}
    result = mod.swept_local_bounds('revolute', initial, [1., 0., 0.], [0., math.pi], [0., 0., 0.])
    # A 180-degree rotation has almost zero Z at either endpoint, but reaches
    # approximately one metre at its intermediate 90-degree pose.
    assert result['min'][1] <= -1.01 and result['max'][1] >= 1.01
    assert result['min'][2] <= -1.01 and result['max'][2] >= 1.01


def test_prismatic_bound_uses_the_real_axis_and_full_declared_travel():
    mod = implementation()
    result = mod.swept_local_bounds('prismatic', {'min': [-.4, -.3, .1], 'max': [.4, .27, .47]},
                                    [0., -1., 0.], [0., .5])
    assert result['min'] == pytest.approx([-.4, -.8, .1])
    assert result['max'] == pytest.approx([.4, .27, .47])
    with pytest.raises(SceneError, match='axis'):
        mod.swept_local_bounds('prismatic', {'min': [-.4, -.3, .1], 'max': [.4, .27, .47]},
                               [0., 0., 0.], [0., .5])


def test_actual_child_geometry_must_fit_the_frozen_source_envelope():
    mod = implementation()
    assert hasattr(mod, 'require_contained_bounds')
    frozen = {'min': [-.5, -.2, 0.], 'max': [.5, .2, .4]}
    mod.require_contained_bounds({'min': [-.49, -.19, .01], 'max': [.49, .19, .39]}, frozen)
    with pytest.raises(SceneError, match='geometry|bounds'):
        mod.require_contained_bounds({'min': [-.6, -.19, .01], 'max': [.49, .19, .39]}, frozen)


def test_missing_usd_bindings_are_reported_as_a_preflight_error(monkeypatch):
    import builtins
    mod = implementation()
    original_import = builtins.__import__
    def no_usd(name, *args, **kwargs):
        if name == 'pxr':
            raise ImportError('USD bindings unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_usd)
    with pytest.raises(SceneError, match='USD|inspect'):
        mod._inspect_prepared_geometry('/missing.usda', {})


def test_known_hinge_checks_external_props_and_never_flags_its_owner(monkeypatch):
    mod = implementation()
    profile = mod.load_profile('usdcraft_lift_cabinet_v1')
    manifest = copy.deepcopy(profile['qualification_manifest'])
    monkeypatch.setattr('simscene.physics_binding.validate_asset_binding', lambda *a, **k: manifest)
    monkeypatch.setattr(mod, '_inspect_prepared_geometry', lambda *a: None)
    scene = {'revision': 3, 'objects': {
        'cabinet': {'kind': 'asset', 'dynamic': True, 'position': [-.7, .259, .832],
                    'asset_path': '/prepared/main.usda', 'asset_binding': {'placeholder': True}},
        'box': {'kind': 'box', 'size': [.1, .1, .1], 'position': [.6, .2, 1.]},
    }}
    original = copy.deepcopy(scene)
    clear = mod.check_motion_clearance(scene, 'cabinet', 'usdcraft_lift_cabinet_v1', ['cabinet', 'box'])
    assert clear['status'] == 'clear' and clear['physics_tested'] is False
    assert clear['skipped_owner'] is True and len(clear['keepout_bounds']) == 1
    assert scene == original
    scene['objects']['box']['position'] = [-.7, -.1, 1.1]
    blocked = mod.check_motion_clearance(scene, 'cabinet', 'usdcraft_lift_cabinet_v1', ['box'])
    assert blocked['status'] == 'conflict'
    assert blocked['scene_sha256'] != clear['scene_sha256']
    assert blocked['conflicts'][0]['object_id'] == 'box'
    assert blocked['conflicts'][0]['joint_id'] == 'main'
    unchecked = mod.check_motion_clearance(scene, 'cabinet', 'usdcraft_lift_cabinet_v1', [])
    assert unchecked['status'] == 'not_checked'


def test_missing_or_changed_native_joint_geometry_is_not_marked_clear(monkeypatch):
    mod = implementation()
    profile = mod.load_profile('usdcraft_lift_cabinet_v1')
    manifest = copy.deepcopy(profile['qualification_manifest'])
    manifest['joint_map']['main']['axis'] = 'Z'
    monkeypatch.setattr('simscene.physics_binding.validate_asset_binding', lambda *a, **k: manifest)
    scene = {'revision': 1, 'objects': {'cabinet': {'kind': 'asset', 'dynamic': True,
             'asset_path': '/prepared/main.usda', 'asset_binding': {'placeholder': True}}}}
    with pytest.raises(SceneError, match='joint|geometry'):
        mod.check_motion_clearance(scene, 'cabinet', 'usdcraft_lift_cabinet_v1', [])
    with pytest.raises(SceneError, match='unknown|unsupported'):
        mod.load_profile('uninspected_joint')


def test_nine_objects_are_rejected_before_layout_backend_is_called():
    from simscene.layout_synthesis import plan_layout
    objects = {'table': {'kind': 'box', 'size': [4, 4, .1], 'position': [0, 0, 0], 'collision': True}}
    objects.update({f'part{i}': {'kind': 'box', 'size': [.1, .1, .1]} for i in range(9)})
    with pytest.raises(SceneError, match='1..8'):
        plan_layout({'revision': 0, 'objects': objects}, [f'part{i}' for i in range(9)], 'table')


def test_file_preflight_reports_unknown_profile_without_a_false_pass(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'experiments/check_motion_clearance.py'
    assert script.is_file(), 'installed motion preflight entrypoint is unavailable'
    scene = tmp_path / 'scene.json'
    output = tmp_path / 'result.json'
    scene.write_text(json.dumps({'revision': 0, 'objects': {}}))
    result = subprocess.run([sys.executable, str(script), '--scene', str(scene), '--owner', 'cabinet',
                             '--profile', 'unknown', '--output', str(output)],
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src')),
                            text=True, capture_output=True)
    assert result.returncode == 1
    report = json.loads(output.read_text())
    assert report['status'] == 'error' and report['physics_tested'] is False
    assert 'unknown' in report['error']


@pytest.mark.parametrize('surface', [
    {'min_xy': [-.4, -.4], 'max_xy': [.4, .4], 'z_m': .3},
    {'min_xy': [-1.1, -.4], 'max_xy': [.4, .4], 'z_m': .05},
])
def test_wrong_primitive_support_height_or_extent_fails_before_sampling(surface, monkeypatch):
    from simscene import layout_synthesis
    scene = {'revision': 0, 'objects': {
        'table': {'kind': 'box', 'size': [2., 1., .1], 'collision': True,
                  'support_surfaces': {'top': surface}},
        'part': {'kind': 'box', 'size': [.1, .1, .1], 'dynamic': True},
    }}
    def no_backend(_):
        pytest.fail('an invalid support reached the optional layout backend')
    monkeypatch.setattr(layout_synthesis, '_run_backend', no_backend)
    with pytest.raises(SceneError, match='support.*(height|extent)'):
        layout_synthesis.plan_layout(scene, ['part'], 'table', support_surface='top')
