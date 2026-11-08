"""Measure new layouts and preserve the ordinary transaction boundary."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from simscene.recipes.compile import compile_recipe
from simscene.recipes.registry import list_recipes
from simscene.scene import SceneStore, SceneError


class SceneRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = {'revision': 0, 'objects': {}}
        self.bindings = {role: self.package(role) for role in ('payload', 'support')}

    def package(self, role, width=None):
        root = self.root/role
        root.mkdir(exist_ok=True)
        asset = root/'main.usda'
        asset.write_text('#usda 1.0\n')
        rigid = role == 'payload'
        width = width or (.1 if rigid else 1.)
        box = {'min': [-width/2, -.05 if rigid else -.3, -.025], 'max': [width/2, .05 if rigid else .3, .025]}
        manifest = {'schema': 'simscene.prepared_asset.v1', 'schema_version': 1,
                    'main': 'main.usda', 'default_prim': '/Asset', 'prepared_id': ('a' if rigid else 'b')*64,
                    'profile_id': 'rigid_prop_v1' if rigid else 'static_fixture_v1', 'bounds': box,
                    'files': [{'path': 'main.usda', 'sha256': hashlib.sha256(asset.read_bytes()).hexdigest(), 'size_bytes': asset.stat().st_size}],
                    'body_map': {'main': {'relative_prim_path': 'Body', 'role': 'rigid' if rigid else 'static',
                                         'visual_relative_prim_paths': ['Body/Visual'], 'collider_relative_prim_paths': ['Body/Collider']}},
                    'support_surfaces': {'top': {'min_xy': [-width/2, -.3], 'max_xy': [width/2, .3], 'z_m': .025}} if not rigid else {}}
        path = root/'manifest.json'
        path.write_text(json.dumps(manifest))
        return {'asset_path': str(asset), 'asset_binding': {'manifest_path': str(path), 'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}

    def compile(self, **params):
        return compile_recipe('gravity_drop_v1', dict(support_surface='top', **params), self.bindings, self.scene)

    def test_three_layout_changes_measure_support_and_complete_payload_footprints(self):
        first = self.compile(count=2)
        raised = self.compile(count=2, origin_m=[.5, -.2, 1.3])
        more = self.compile(count=4)
        self.assertEqual(len(first['operations']), 3)
        self.assertEqual(len(more['operations']), 5)
        for a, b in zip(first['operations'], raised['operations']):
            self.assertEqual([round(y-x, 8) for x, y in zip(a['object']['position'], b['object']['position'])], [.5, -.2, 1.3])
        self.assertNotEqual(first['recipe_hash'], raised['recipe_hash'])
        self.assertNotEqual(first['recipe_hash'], more['recipe_hash'])
        for box in more['drop_envelopes_m'].values():
            self.assertGreaterEqual(box['min'][0], -.5)
            self.assertLessEqual(box['max'][0], .5)
            self.assertEqual(box['min'][2], .025)
        self.bindings['payload'] = self.package('payload', .18)
        changed = self.compile(count=4)
        self.assertNotEqual(changed['recipe_hash'], more['recipe_hash'])
        self.assertAlmostEqual(changed['drop_envelopes_m']['cell_payload_01']['max'][0]-changed['drop_envelopes_m']['cell_payload_01']['min'][0], .18)

    def test_oversize_keepout_excluded_region_and_wrong_profile_fail_actionably(self):
        self.bindings['payload'] = self.package('payload', .3)
        with self.assertRaisesRegex(ValueError, 'larger support'):
            self.compile(count=4)
        with self.assertRaisesRegex(ValueError, 'keepout'):
            self.compile(keepout_bounds=[{'min': [-.4, -.4, .1], 'max': [.4, .4, .5]}])
        self.bindings['payload'] = self.bindings['support']
        with self.assertRaisesRegex(ValueError, 'rigid_prop_v1'):
            self.compile()

    def test_pins_and_atomic_revision_conflict(self):
        store = SceneStore(self.root/'scenes')
        initial = store.open('trial')
        plan = compile_recipe('gravity_drop_v1', {'support_surface': 'top'}, self.bindings, initial)
        original = deepcopy(initial)
        self.assertEqual(initial, original)
        store.apply('trial', plan['base_revision'], 'other-edit', [{'op': 'add', 'id': 'lamp', 'object': {'kind': 'light'}}])
        with self.assertRaisesRegex(SceneError, 'revision conflict'):
            store.apply('trial', plan['base_revision'], 'recipe-edit', plan['operations'])
        self.assertEqual(set(store.get('trial')['objects']), {'lamp'})
        plan = compile_recipe('gravity_drop_v1', {'support_surface': 'top'}, self.bindings, store.get('trial'))
        store.apply('trial', plan['base_revision'], 'recipe-edit-2', plan['operations'])
        self.assertEqual(len(store.get('trial')['objects']), 3)
        Path(self.bindings['payload']['asset_path']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.compile()

    def test_bridge_is_editable_passive_and_no_release_is_synthesized(self):
        plan = compile_recipe('passive_door_bridge_v1', {'prefix': 'bridge', 'origin': [0, 0, 1]}, {}, self.scene)
        panel, joint = (op['object'] for op in plan['operations'][:2])
        self.assertEqual(panel['kind'], 'compound')
        self.assertEqual(joint['joint']['type'], 'revolute')
        self.assertFalse(plan['physics_tested'])
        self.assertTrue(any('retainer' in warning for warning in plan['warnings']))
        self.assertFalse(any('spawn_step' in op['object'] for op in plan['operations']))
        self.assertEqual(len(list_recipes()['recipes']), 2)

    def test_missing_role_unknown_nan_and_existing_ids_fail_before_writing(self):
        with self.assertRaisesRegex(ValueError, 'asset://payload'):
            compile_recipe('gravity_drop_v1', {'support_surface': 'top'}, {'support': self.bindings['support']}, self.scene)
        for parameters in ({'count': True}, {'drop_height_m': float('nan')}, {'unexpected': 1}):
            with self.assertRaises(ValueError):
                self.compile(**parameters)
        self.scene['objects']['cell_support'] = {'kind': 'box'}
        with self.assertRaisesRegex(SceneError, 'already exists'):
            self.compile()


if __name__ == '__main__':
    unittest.main()
