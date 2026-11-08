"""Binding failures must guide callers to repair the binding, retaining rigid flags."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from simscene.scene import validate


class SceneBindingDiagnosticsTest(unittest.TestCase):
    def asset(self, binding=None):
        return {'kind': 'asset', 'asset_path': '/fixture/main.usda', 'dynamic': True,
                'collision': True, 'asset_binding': binding}

    def test_whole_preparation_result_reports_one_precise_error_per_body(self):
        result = {'manifest_path': '/fixture/manifest.json', 'manifest_sha256': 'a' * 64,
                  'root': '/fixture/main.usda', 'prepared_handle': 'b' * 64}
        scene = {'objects': {f'body{i}': self.asset(deepcopy(result)) for i in range(4)}}
        original = deepcopy(scene)
        issues = validate(scene)
        self.assertEqual(len(issues), 4)
        self.assertEqual({item['object'] for item in issues}, set(scene['objects']))
        self.assertTrue(all(item['message'] == 'invalid asset_binding: asset_binding requires manifest_path and manifest_sha256'
                            for item in issues))
        self.assertEqual(scene, original)
        self.assertTrue(all(obj['dynamic'] is True and obj['collision'] is True for obj in scene['objects'].values()))

    def test_invalid_binding_retains_boolean_type_errors_without_primitive_advice(self):
        obj = self.asset({})
        obj.update(dynamic='true', collision=1)
        messages = {item['message'] for item in validate({'objects': {'part': obj}})}
        self.assertEqual(messages, {'invalid asset_binding: asset_binding requires manifest_path and manifest_sha256',
                                    'dynamic must be boolean', 'collision must be boolean'})
        for binding in (None, {}, {'manifest_path': '/fixture/manifest.json'}):
            with self.subTest(binding=binding):
                issues = validate({'objects': {'part': self.asset(binding)}})
                self.assertEqual(len(issues), 1)
                self.assertTrue(issues[0]['message'].startswith('invalid asset_binding:'))

    def test_removing_dynamic_is_rejected_with_correct_prepared_profile_guidance(self):
        binding = {'manifest_path': '/fixture/manifest.json', 'manifest_sha256': 'a' * 64}
        manifest = {'profile_id': 'rigid_prop_v1', 'body_map': {'main': {
            'role': 'rigid', 'collider_relative_prim_paths': ['Body/Visual/Mesh0']}}}
        obj = self.asset(binding)
        with patch('simscene.physics_binding.validate_asset_binding', return_value=manifest):
            self.assertEqual(validate({'objects': {'part': obj}}), [])
            obj['dynamic'] = False
            issues = validate({'objects': {'part': obj}})
        self.assertEqual(issues, [{'object': 'part', 'message': 'invalid asset_binding: prepared rigid_prop_v1 requires dynamic=true'}])

    def test_legacy_unbound_asset_messages_and_primitive_rules_are_unchanged(self):
        for value in (True, False):
            obj = {'kind': 'asset', 'asset_path': '/fixture/legacy.usda', 'dynamic': value, 'collision': value}
            with self.subTest(value=value):
                self.assertEqual(validate({'objects': {'part': obj}}), [
                    {'object': 'part', 'message': 'collision is only authored for primitive geometry; inspect asset physics separately'},
                    {'object': 'part', 'message': 'dynamic is only authored for primitive geometry; inspect asset physics separately'}])
        self.assertEqual(validate({'objects': {'part': {'kind': 'box', 'dynamic': True, 'collision': True, 'size': [.1, .2, .3]}}}), [])
        self.assertEqual(validate({'objects': {'part': {'kind': 'asset', 'asset_path': '/fixture/legacy.usda'}}}), [])


if __name__ == '__main__':
    unittest.main()
