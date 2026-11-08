import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.scene import SceneError, SceneStore, validate
from simscene.usd_export import export_scene

try:
    from pxr import Usd, UsdGeom, UsdPhysics
except ImportError:
    Usd = None


@unittest.skipIf(Usd is None, 'USD unavailable')
class PreparedSceneBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rigid = self.package('rigid_prop_v1')
        self.static = self.package('static_fixture_v1')
        self.visual = self.package('visual_prop_v1')

    def tearDown(self):
        self.temp.cleanup()

    def package(self, profile):
        root = self.root / profile; root.mkdir()
        main = root / 'main.usda'
        stage = Usd.Stage.CreateNew(str(main))
        UsdGeom.SetStageMetersPerUnit(stage, 1.)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        anchor = UsdGeom.Xform.Define(stage, '/Asset')
        stage.SetDefaultPrim(anchor.GetPrim())
        body_map = {}
        if profile == 'rigid_prop_v1':
            body = UsdGeom.Xform.Define(stage, '/Asset/Body')
            UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
            UsdPhysics.MassAPI.Apply(body.GetPrim()).CreateMassAttr(.12)
            UsdGeom.Xform.Define(stage, '/Asset/Body/Visual')
            mesh = UsdGeom.Cube.Define(stage, '/Asset/Body/Visual/Mesh0')
            UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
            body_map['main'] = {'role': 'rigid', 'relative_prim_path': 'Body', 'visual_relative_prim_paths': ['Body/Visual'], 'collider_relative_prim_paths': ['Body/Visual/Mesh0']}
        else:
            UsdGeom.Cube.Define(stage, '/Asset/Visual')
            if profile == 'static_fixture_v1':
                proxy = UsdGeom.Cube.Define(stage, '/Asset/Proxy')
                UsdPhysics.CollisionAPI.Apply(proxy.GetPrim())
                body_map['main'] = {'role': 'static', 'relative_prim_path': 'Proxy', 'visual_relative_prim_paths': ['Visual'], 'collider_relative_prim_paths': ['Proxy']}
        stage.GetRootLayer().Save()
        manifest = {'schema_version': 1, 'schema': 'simscene.prepared_asset.v1', 'profile_id': profile, 'main': 'main.usda', 'default_prim': '/Asset', 'body_map': body_map, 'parameters': {'ccd': profile == 'rigid_prop_v1'}, 'files': [{'path': 'main.usda', 'size_bytes': main.stat().st_size, 'sha256': hashlib.sha256(main.read_bytes()).hexdigest()}]}
        path = root / 'manifest.json'; path.write_text(json.dumps(manifest))
        return {'kind': 'asset', 'asset_path': str(main), 'asset_binding': {'manifest_path': str(path), 'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, 'dynamic': profile == 'rigid_prop_v1', 'collision': profile != 'visual_prop_v1'}

    def scene(self, obj=None):
        return {'revision': 1, 'objects': {'item': copy.deepcopy(obj or self.rigid)}}

    def test_export_four_instances_preserves_nested_physics_and_returns_mapping(self):
        scene = {'revision': 1, 'objects': {name: dict(copy.deepcopy(self.rigid), position=[i, 0, 1]) for i, name in enumerate(('one', 'two', 'three', 'four'))}}
        result = export_scene(scene, self.root / 'four.usda')
        stage = Usd.Stage.Open(result['path'])
        self.assertEqual(len(result['body_bindings']), 4)
        for name in scene['objects']:
            path = '/World/' + name + '/Asset/Body'
            self.assertEqual(result['body_bindings'][name]['motion_body'], path)
            self.assertTrue(stage.GetPrimAtPath(path).HasAPI(UsdPhysics.RigidBodyAPI))
            self.assertAlmostEqual(UsdPhysics.MassAPI(stage.GetPrimAtPath(path)).GetMassAttr().Get(), .12, places=6)
            self.assertFalse(stage.GetPrimAtPath('/World/' + name).HasAPI(UsdPhysics.RigidBodyAPI))
            self.assertFalse(stage.GetPrimAtPath('/World/' + name).HasAPI(UsdPhysics.CollisionAPI))
        self.assertTrue(stage.GetPrimAtPath('/World/PhysicsScene').GetAttribute('physxScene:enableCCD').Get())

    def test_static_and_visual_flags_are_declarations_of_prepared_profile(self):
        for name, obj in [('static', self.static), ('visual', self.visual)]:
            self.assertEqual(validate(self.scene(obj)), [])
            result = export_scene(self.scene(obj), self.root / (name + '.usda'))
            self.assertEqual(result['body_bindings'], {})
            stage = Usd.Stage.Open(result['path'])
            self.assertFalse(any(prim.HasAPI(UsdPhysics.RigidBodyAPI) for prim in stage.Traverse()))
        bad = copy.deepcopy(self.static); bad['dynamic'] = True
        self.assertTrue(validate(self.scene(bad)))
        bad = copy.deepcopy(self.rigid); bad['dynamic'] = False
        self.assertTrue(validate(self.scene(bad)))
        bad = copy.deepcopy(self.rigid); bad['collision'] = False
        self.assertTrue(validate(self.scene(bad)))
        bad = copy.deepcopy(self.visual); bad['collision'] = True
        self.assertTrue(validate(self.scene(bad)))

    def test_prepared_identity_overrides_rejected_before_export(self):
        changes = {'size': [1, 1, 1], 'scale': [2, 2, 2], 'mass_kg': .2, 'physics': {'enable_ccd': True}, 'material': {'roughness': .2}, 'color': [.2, .3, .4], 'material_overrides': {'Body/Visual': {'roughness': .2}}, 'variants': {}, 'asset_metrics': {'meters_per_unit': 1., 'up_axis': 'Z', 'reason': 'already measured source'}, 'pose_follower': {}, 'rigid_attachment': {'body': 'item'}, 'collision_exclusions': [], 'asset_physics': 'visual_only', 'asset_lights': 'disabled'}
        for field, value in changes.items():
            obj = copy.deepcopy(self.rigid); obj[field] = value
            with self.subTest(field=field):
                issues = validate(self.scene(obj))
                self.assertTrue(any('asset_binding' in issue['message'] for issue in issues))
                with self.assertRaises(SceneError):
                    export_scene(self.scene(obj), self.root / 'invalid.usda')
                self.assertFalse((self.root / 'invalid.usda').exists())

    def test_legacy_imported_asset_rule_unchanged_and_mutation_fails(self):
        obj = {'kind': 'asset', 'asset_path': self.rigid['asset_path']}
        self.assertEqual(validate(self.scene(obj)), [])
        for key in ('dynamic', 'collision'):
            bad = dict(obj, **{key: False})
            self.assertTrue(any('only authored for primitive' in issue['message'] for issue in validate(self.scene(bad))))
        main = Path(self.rigid['asset_path']); main.write_text(main.read_text() + '\n# mutation\n')
        self.assertTrue(validate(self.scene()))
        with self.assertRaises(SceneError):
            export_scene(self.scene(), self.root / 'changed.usda')

    def test_binding_types_and_profile_mismatch_rejected(self):
        for binding in [None, {}, {'manifest_path': 'unknown'}, {'manifest_path': self.rigid['asset_binding']['manifest_path'], 'manifest_sha256': '0' * 64}]:
            obj = copy.deepcopy(self.rigid); obj['asset_binding'] = binding
            with self.subTest(binding=binding):
                self.assertTrue(validate(self.scene(obj)))
        primitive = {'kind': 'box', 'asset_binding': self.rigid['asset_binding']}
        self.assertTrue(validate(self.scene(primitive)))

    def test_actual_source_physics_and_metrics_must_match_prepared_profile(self):
        for name, template in [('static', self.static), ('units', self.rigid)]:
            obj = copy.deepcopy(template)
            main = Path(obj['asset_path'])
            source = Usd.Stage.Open(str(main))
            if name == 'static':
                UsdPhysics.RigidBodyAPI.Apply(source.GetPrimAtPath('/Asset/Proxy'))
            else:
                UsdGeom.SetStageMetersPerUnit(source, .01)
            source.GetRootLayer().Save()
            manifest_path = Path(obj['asset_binding']['manifest_path'])
            manifest = json.loads(manifest_path.read_text())
            manifest['files'][0].update(size_bytes=main.stat().st_size, sha256=hashlib.sha256(main.read_bytes()).hexdigest())
            manifest_path.write_text(json.dumps(manifest))
            obj['asset_binding']['manifest_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            output = self.root / (name + '-mismatch.usda')
            with self.subTest(name=name), self.assertRaises(SceneError):
                export_scene(self.scene(obj), output)
            self.assertFalse(output.exists())

    def test_final_binding_failure_removes_unpublished_stage(self):
        output = self.root / 'failed.usda'
        with patch('simscene.physics_binding.resolve_body_bindings', side_effect=ValueError('missing actual body')):
            with self.assertRaisesRegex(SceneError, 'missing actual body'):
                export_scene(self.scene(), output)
        self.assertFalse(output.exists())

    def test_scene_store_atomic_binding_roundtrip(self):
        store = SceneStore(self.root / 'scenes'); store.open('scene')
        store.apply('scene', 0, 'add', [{'op': 'add', 'id': 'item', 'object': self.rigid}])
        self.assertEqual(store.get('scene')['objects']['item']['asset_binding'], self.rigid['asset_binding'])
        bad = copy.deepcopy(self.rigid); bad['mass_kg'] = .5
        with self.assertRaises(SceneError):
            store.apply('scene', 1, 'bad', [{'op': 'add', 'id': 'other', 'object': bad}])
        self.assertEqual(store.get('scene')['revision'], 1)
        self.assertEqual(list(store.get('scene')['objects']), ['item'])


if __name__ == '__main__':
    unittest.main()
