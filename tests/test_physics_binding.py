import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from simscene.physics_binding import validate_asset_binding, resolve_body_bindings

try:
    from pxr import Usd, UsdGeom, UsdPhysics, Gf
except ImportError:
    Usd = None


@unittest.skipIf(Usd is None, 'USD unavailable')
class PhysicsBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.main = self.root / 'main.usda'
        source = Usd.Stage.CreateNew(str(self.main))
        UsdGeom.SetStageMetersPerUnit(source, 1.)
        UsdGeom.SetStageUpAxis(source, UsdGeom.Tokens.z)
        asset = UsdGeom.Xform.Define(source, '/Asset')
        source.SetDefaultPrim(asset.GetPrim())
        body = UsdGeom.Xform.Define(source, '/Asset/Body')
        UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
        UsdGeom.Xform.Define(source, '/Asset/Body/Visual')
        cube = UsdGeom.Cube.Define(source, '/Asset/Body/Visual/Mesh0')
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        source.GetRootLayer().Save()
        self.document = {'schema_version': 1, 'schema': 'simscene.prepared_asset.v1', 'profile_id': 'rigid_prop_v1', 'default_prim': '/Asset', 'main': 'main.usda', 'files': [{'path': 'main.usda', 'size_bytes': self.main.stat().st_size, 'sha256': self.hash(self.main)}], 'body_map': {'main': {'relative_prim_path': 'Body', 'role': 'rigid', 'visual_relative_prim_paths': ['Body/Visual'], 'collider_relative_prim_paths': ['Body/Visual/Mesh0']}}}
        self.manifest = self.root / 'manifest.json'
        self.binding = self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def hash(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.document))
        return {'manifest_path': str(self.manifest), 'manifest_sha256': self.hash(self.manifest)}

    def scene(self, names=('item',)):
        stage = Usd.Stage.CreateInMemory()
        spec = {'objects': {}}
        for name in names:
            UsdGeom.Xform.Define(stage, '/World/' + name)
            stage.OverridePrim('/World/' + name + '/Asset').GetReferences().AddReference(str(self.main))
            spec['objects'][name] = {'kind': 'asset', 'dynamic': True, 'asset_path': str(self.main), 'asset_binding': self.binding}
        return stage, spec

    def test_nested_body_and_four_independent_instances(self):
        stage, spec = self.scene(('one', 'two', 'three', 'four'))
        result = resolve_body_bindings(stage, spec)
        self.assertEqual(len(set(v['motion_body'] for v in result.values())), 4)
        self.assertEqual(result['one']['motion_body'], '/World/one/Asset/Body')
        self.assertEqual(result['one']['contact_bodies'], ['/World/one/Asset/Body'])
        self.assertEqual(result['one']['visual_roots'], ['/World/one/Asset/Body/Visual'])
        self.assertFalse(stage.GetPrimAtPath('/World/one').HasAPI(UsdPhysics.RigidBodyAPI))

    def test_hash_and_file_closure_mutation(self):
        self.main.write_text(self.main.read_text() + '\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'dependency'):
            validate_asset_binding(self.binding, require_dynamic=True)
        self.manifest.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            validate_asset_binding(self.binding)

    def test_unlisted_file_symlink_and_path_escape(self):
        extra = self.root / 'extra.txt'; extra.write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'complete package'):
            validate_asset_binding(self.binding)
        extra.unlink(); extra.symlink_to(self.main)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            validate_asset_binding(self.binding)
        extra.unlink(); self.document['files'][0]['path'] = '../main.usda'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            validate_asset_binding(self.write_manifest())

    def test_missing_body_duplicate_and_removed_collider(self):
        stage, spec = self.scene()
        self.document['body_map']['main']['relative_prim_path'] = 'Missing'
        spec['objects']['item']['asset_binding'] = self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'missing'):
            resolve_body_bindings(stage, spec)
        self.document['body_map']['other'] = dict(self.document['body_map']['main'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_asset_binding(self.write_manifest())
        self.document['body_map'].pop('other'); self.document['body_map']['main']['relative_prim_path'] = 'Body'
        spec['objects']['item']['asset_binding'] = self.write_manifest()
        stage.GetPrimAtPath('/World/item/Asset/Body/Visual/Mesh0').RemoveAPI(UsdPhysics.CollisionAPI)
        with self.assertRaisesRegex(ValueError, 'collider'):
            resolve_body_bindings(stage, spec)

    def test_parent_scale_animation_controller_and_unbound_dynamic(self):
        stage, spec = self.scene()
        UsdGeom.Xformable(stage.GetPrimAtPath('/World/item')).AddScaleOp().Set(Gf.Vec3d(2))
        with self.assertRaisesRegex(ValueError, 'scale'):
            resolve_body_bindings(stage, spec)
        stage, spec = self.scene()
        op = UsdGeom.Xformable(stage.GetPrimAtPath('/World/item/Asset/Body')).AddTranslateOp()
        op.Set(Gf.Vec3d(0), 0); op.Set(Gf.Vec3d(0, 0, 1), 1)
        with self.assertRaisesRegex(ValueError, 'animated'):
            resolve_body_bindings(stage, spec)
        stage, spec = self.scene(); spec['objects']['item']['pose_follower'] = {'model': 'controller'}
        with self.assertRaisesRegex(ValueError, 'follower'):
            resolve_body_bindings(stage, spec)
        del spec['objects']['item']['asset_binding']
        with self.assertRaisesRegex(ValueError, 'binding'):
            resolve_body_bindings(stage, spec)

    def test_usd_reference_cannot_escape_hashed_file_closure(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / 'outside.usda'
            other = Usd.Stage.CreateNew(str(outside)); UsdGeom.Xform.Define(other, '/Other'); other.GetRootLayer().Save()
            source = Usd.Stage.Open(str(self.main))
            source.GetPrimAtPath('/Asset/Body/Visual').GetReferences().AddReference(str(outside), '/Other')
            source.GetRootLayer().Save()
            self.document['files'][0].update(size_bytes=self.main.stat().st_size, sha256=self.hash(self.main))
            self.binding = self.write_manifest()
            stage, spec = self.scene()
            with self.assertRaisesRegex(ValueError, 'escapes'):
                resolve_body_bindings(stage, spec)

    def test_visual_profile_cannot_enable_dynamic(self):
        self.document['profile_id'] = 'visual_prop_v1'
        with self.assertRaisesRegex(ValueError, 'rigid_prop_v1'):
            validate_asset_binding(self.write_manifest(), require_dynamic=True)
        stage, spec = self.scene(); spec['objects']['item']['dynamic'] = False
        spec['objects']['item']['asset_binding'] = self.write_manifest()
        self.assertEqual(resolve_body_bindings(stage, spec), {})


if __name__ == '__main__':
    unittest.main()
