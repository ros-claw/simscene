"""Real USD dependency scans and minimal generated SDK MDL modules; no app/network."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
try:
    from pxr import Usd, UsdGeom, Sdf
except ImportError:
    Usd = None

from simscene.preparation.snapshots import pin_prepared_runtime, verify_prepared_runtime, PROOF_FIELDS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(Usd, 'OpenUSD is optional on the CPU host')
class PreparedRuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / 'prepared'; self.package.mkdir()
        self.sdk = self.root / 'sdk'
        self.launcher = self.sdk / 'python.sh'; self.sdk.mkdir(); self.launcher.write_text('not executed')
        self.base = self.sdk / 'kit/mdl/core/Base'; self.base.mkdir(parents=True)
        (self.base / 'OmniPBR.mdl').write_text('mdl 1.7; import Helper::*; export string map="textures/tiny.png";')
        (self.base / 'Helper.mdl').write_text('mdl 1.7; import ::df::*;')
        (self.base / 'textures').mkdir(); (self.base / 'textures/tiny.png').write_bytes(b'original test texture')
        absolute = self.sdk / 'kit/mdl/core/mdl'; absolute.mkdir()
        (absolute / 'df.mdl').write_text('mdl 1.7; // generated standard-module shim')
        (self.base / 'OmniGlass.mdl').write_text('mdl 1.7;')
        self.layer(self.package / 'main.usda', 'OmniPBR.mdl')

    def layer(self, path, asset=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        stage = Usd.Stage.CreateNew(str(path)); root = UsdGeom.Xform.Define(stage, '/Asset')
        stage.SetDefaultPrim(root.GetPrim())
        if asset:
            root.GetPrim().CreateAttribute('test:mdl', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(asset))
        stage.GetRootLayer().Save()

    def manifest(self, declarations=True):
        value = {'main': 'main.usda', 'files': [
            {'path': p.relative_to(self.package).as_posix(), 'size_bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(self.package.rglob('*')) if p.is_file() and p != self.package / 'manifest.json'],
            'runtime_dependencies': ([{'asset': 'OmniPBR.mdl', 'attribute': '/Asset.test:mdl', 'kind': 'target_runtime_mdl'}]
                                     if declarations else [])}
        (self.package / 'manifest.json').write_text(json.dumps(value))
        return value

    def test_full_transitive_sdk_modules_and_texture_are_pinned(self):
        manifest = self.manifest(); proof = pin_prepared_runtime(self.package, manifest, self.launcher)
        self.assertEqual(set(proof), PROOF_FIELDS)
        self.assertEqual(proof['runtime_provided_dependencies'], {'OmniPBR.mdl': str(self.base / 'OmniPBR.mdl')})
        self.assertEqual(set(proof['prepared_mdl_runtime_files']), {
            'kit/mdl/core/Base/OmniPBR.mdl', 'kit/mdl/core/Base/Helper.mdl',
            'kit/mdl/core/Base/textures/tiny.png', 'kit/mdl/core/mdl/df.mdl'})
        self.assertTrue(verify_prepared_runtime(self.package, manifest, proof, self.launcher))
        original = (self.base / 'Helper.mdl').read_bytes()
        (self.base / 'Helper.mdl').write_text('mdl 1.7; // changed transitive module')
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, proof, self.launcher)
        (self.base / 'Helper.mdl').write_bytes(original)
        (self.base / 'textures/tiny.png').write_bytes(b'changed texture')
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, proof, self.launcher)

    def test_source_only_builtin_is_found_without_manifest_declaration(self):
        self.layer(self.package / 'source/original.usda', 'OmniGlass.mdl')
        # Main needs no MDL; source remains part of the complete immutable closure.
        stage = Usd.Stage.Open(str(self.package / 'main.usda'))
        stage.GetPrimAtPath('/Asset').RemoveProperty('test:mdl'); stage.GetRootLayer().Save()
        manifest = self.manifest(False); proof = pin_prepared_runtime(self.package, manifest, self.launcher)
        self.assertEqual(set(proof['runtime_provided_dependencies']), {'OmniGlass.mdl'})
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, {}, self.launcher)

    def test_custom_and_unclassified_runtime_assets_are_rejected(self):
        manifest = self.manifest()
        custom = copy.deepcopy(manifest); custom['runtime_dependencies'][0]['asset'] = 'Custom.mdl'
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, custom, self.launcher)
        outsider = self.root / 'OmniPBR.mdl'; outsider.write_text('mdl 1.7;')
        custom['runtime_dependencies'][0]['asset'] = str(outsider)
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, custom, self.launcher)
        stage = Usd.Stage.Open(str(self.package / 'main.usda'))
        stage.GetPrimAtPath('/Asset').GetAttribute('test:mdl').Set(Sdf.AssetPath('MissingCustom.mdl')); stage.GetRootLayer().Save()
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, self.manifest(False), self.launcher)

    def test_actual_external_custom_mdl_and_unlisted_local_file_rejected(self):
        outside = self.root / 'Custom.mdl'; outside.write_text('mdl 1.7;')
        stage = Usd.Stage.Open(str(self.package / 'main.usda'))
        stage.GetPrimAtPath('/Asset').GetAttribute('test:mdl').Set(Sdf.AssetPath(str(outside))); stage.GetRootLayer().Save()
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, self.manifest(False), self.launcher)
        stage.GetPrimAtPath('/Asset').RemoveProperty('test:mdl'); stage.GetRootLayer().Save()
        valid=self.manifest(False)
        (self.package / 'unlisted.txt').write_text('not inventoried')
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, valid, self.launcher)

    def test_exact_absolute_sdk_builtin_and_local_module_imports(self):
        stage = Usd.Stage.Open(str(self.package / 'main.usda'))
        stage.GetPrimAtPath('/Asset').GetAttribute('test:mdl').Set(Sdf.AssetPath(str(self.base / 'OmniPBR.mdl'))); stage.GetRootLayer().Save()
        proof=pin_prepared_runtime(self.package,self.manifest(False),self.launcher)
        self.assertEqual(set(proof['runtime_provided_dependencies']),{'OmniPBR.mdl'})
        (self.package / 'Custom.mdl').write_text('mdl 1.7; import ::df::*;')
        stage.GetPrimAtPath('/Asset').GetAttribute('test:mdl').Set(Sdf.AssetPath('./Custom.mdl')); stage.GetRootLayer().Save()
        manifest=self.manifest(False);proof=pin_prepared_runtime(self.package,manifest,self.launcher)
        self.assertEqual(proof['runtime_provided_dependencies'],{})
        self.assertEqual(set(proof['prepared_mdl_runtime_files']),{'kit/mdl/core/mdl/df.mdl'})
        with self.assertRaises(ValueError):verify_prepared_runtime(self.package,manifest,{},self.launcher)

    def test_missing_or_partial_proof_never_exempts_runtime_dependencies(self):
        manifest = self.manifest(); proof = pin_prepared_runtime(self.package, manifest, self.launcher)
        for missing in PROOF_FIELDS:
            changed = dict(proof); changed.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                verify_prepared_runtime(self.package, manifest, changed, self.launcher)
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, {}, self.launcher)
        changed = copy.deepcopy(proof); changed['prepared_mdl_runtime_files'] = {}
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, changed, self.launcher)

    def test_legacy_proof_absent_only_when_scans_prove_runtime_empty(self):
        stage = Usd.Stage.Open(str(self.package / 'main.usda'))
        stage.GetPrimAtPath('/Asset').RemoveProperty('test:mdl'); stage.GetRootLayer().Save()
        manifest = self.manifest(False)
        proof = pin_prepared_runtime(self.package, manifest, self.launcher)
        self.assertEqual(proof, {name: {} for name in PROOF_FIELDS})
        self.assertTrue(verify_prepared_runtime(self.package, manifest, {}, self.launcher))
        self.assertTrue(verify_prepared_runtime(self.package, manifest, proof, self.launcher))
        declared = self.manifest(True)
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, declared, {}, self.launcher)

    def test_runtime_symlink_and_package_content_changes_fail(self):
        manifest = self.manifest(); proof = pin_prepared_runtime(self.package, manifest, self.launcher)
        (self.package / 'main.usda').write_text('#usda 1.0\n')
        with self.assertRaises(ValueError): verify_prepared_runtime(self.package, manifest, proof, self.launcher)
        # Do not use basename matching to admit a module outside the selected SDK.
        helper = self.base / 'Helper.mdl'; helper.unlink(); outside = self.root / 'Helper.mdl'; outside.write_text('mdl 1.7;'); helper.symlink_to(outside)
        with self.assertRaises(ValueError): pin_prepared_runtime(self.package, self.manifest(), self.launcher)

if __name__ == '__main__':
    unittest.main()
