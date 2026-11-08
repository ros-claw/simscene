"""Prepared eviction recovery requires the caller's exact frozen manifest pin."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from simscene.cache_restore import restore_prepared_reference


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PreparedRestoreTest(unittest.TestCase):
    def setup_package(self, root):
        original = root / 'prepared-cache' / ('a' * 64)
        original.mkdir(parents=True)
        (original / 'main.usda').write_text('#usda 1.0\n')
        (original / 'textures').mkdir()
        (original / 'textures/albedo.png').write_bytes(b'fixture immutable texture')
        manifest = {'schema_version': 1, 'schema': 'simscene.prepared_asset.v1',
                    'prepared_id': 'a' * 64, 'profile_id': 'visual_prop_v1',
                    'main': 'main.usda', 'default_prim': '/Asset', 'body_map': {},
                    'source_ref': {'source_id': 'fixture', 'asset_id': 'selected', 'revision': 'frozen'},
                    'license': {'status': 'known', 'license': 'CC-BY-4.0'},
                    'files': [{'path': name, 'sha256': digest(original / name), 'size_bytes': (original / name).stat().st_size}
                              for name in ('main.usda', 'textures/albedo.png')]}
        (original / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        binding = {'manifest_path': str(original / 'manifest.json'), 'manifest_sha256': digest(original / 'manifest.json')}
        return original, binding

    def frozen_run(self, home, original, binding, name='old-run'):
        run = home / 'runs' / name
        snapshot = run / 'assets' / ('prepared-' + binding['manifest_sha256'])
        snapshot.parent.mkdir(parents=True)
        shutil.copytree(original, snapshot)
        record = {'kind': 'prepared_snapshot', 'prepared_id': 'a' * 64,
                  'manifest_relative_to_run': snapshot.relative_to(run).as_posix() + '/manifest.json',
                  'root_relative_to_run': snapshot.relative_to(run).as_posix() + '/main.usda',
                  'manifest_sha256': binding['manifest_sha256']}
        (run / 'asset-lock.json').write_text(json.dumps({'selected-object': record}, sort_keys=True))
        return run, snapshot, record

    def test_existing_valid_binding_is_returned_unchanged_without_history_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            with patch('simscene.cache_restore.get', side_effect=AssertionError('history lookup forbidden')):
                result = restore_prepared_reference(binding, str(original / 'main.usda'))
            self.assertEqual(result, {'asset_path': str(original / 'main.usda'), 'asset_binding': binding})
            self.assertIs(result['asset_binding'], binding)

    def test_evicted_package_restores_from_exact_snapshot_without_mutation_or_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            run, snapshot, _ = self.frozen_run(root / 'home', original, binding)
            before = {str(path.relative_to(run)): path.read_bytes() for path in run.rglob('*') if path.is_file()}
            selected = str(original / 'main.usda')
            shutil.rmtree(original)
            with patch('simscene.cache_restore.USDSearch', side_effect=AssertionError('network forbidden')):
                result = restore_prepared_reference(binding, selected, home=root / 'home')
            self.assertEqual(result['asset_path'], str(snapshot / 'main.usda'))
            self.assertEqual(result['asset_binding'], {'manifest_path': str(snapshot / 'manifest.json'), 'manifest_sha256': binding['manifest_sha256']})
            self.assertFalse(original.exists())
            after = {str(path.relative_to(run)): path.read_bytes() for path in run.rglob('*') if path.is_file()}
            self.assertEqual(after, before)
            # Reusing the relocated binding never scans/reconstructs history.
            self.assertEqual(restore_prepared_reference(result['asset_binding'], result['asset_path'], home=root / 'missing'), result)

    def test_missing_proof_or_self_hashed_replacement_cannot_replace_caller_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            run, snapshot, record = self.frozen_run(root / 'home', original, binding)
            selected = str(original / 'main.usda'); shutil.rmtree(original)
            (run / 'asset-lock.json').unlink()
            with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted:.*run asset_prepare with new request'):
                restore_prepared_reference(binding, selected, home=root / 'home')
            # An attacker/self-healing cache may hash a changed manifest, but
            # its new pin is not the caller's selected immutable identity.
            manifest = json.loads((snapshot / 'manifest.json').read_text())
            manifest['source_ref']['asset_id'] = 'different-selection'
            (snapshot / 'manifest.json').write_text(json.dumps(manifest))
            record['manifest_sha256'] = digest(snapshot / 'manifest.json')
            (run / 'asset-lock.json').write_text(json.dumps({'selected-object': record}))
            with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted'):
                restore_prepared_reference(binding, selected, home=root / 'home')

    def test_exact_record_rejects_manifest_or_dependency_hash_drift(self):
        for changed in ('manifest', 'dependency'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); original, binding = self.setup_package(root)
                run, snapshot, record = self.frozen_run(root / 'home', original, binding)
                selected = str(original / 'main.usda'); shutil.rmtree(original)
                target = snapshot / ('manifest.json' if changed == 'manifest' else 'textures/albedo.png')
                target.write_bytes(target.read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted'):
                    restore_prepared_reference(binding, selected, home=root / 'home')

    def test_unsafe_record_paths_wrong_root_and_wrong_identity_fail_closed(self):
        changes = ({'manifest_relative_to_run': '../other/manifest.json'},
                   {'manifest_relative_to_run': '/tmp/arbitrary/manifest.json'},
                   {'manifest_relative_to_run': 'assets//package/manifest.json'},
                   {'root_relative_to_run': 'assets/another-package/main.usda'},
                   {'root_relative_to_run': 'assets/pkg/../main.usda'},
                   {'prepared_id': 'b' * 64})
        for changeset in changes:
            with self.subTest(changes=changeset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); original, binding = self.setup_package(root)
                run, snapshot, record = self.frozen_run(root / 'home', original, binding)
                selected = str(original / 'main.usda'); shutil.rmtree(original)
                (run / 'asset-lock.json').write_text(json.dumps({'selected-object': dict(record, **changeset)}))
                with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted'):
                    restore_prepared_reference(binding, selected, home=root / 'home')

    def test_caller_asset_path_must_select_manifest_main(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            self.frozen_run(root / 'home', original, binding)
            wrong = str(original / 'textures/albedo.png'); shutil.rmtree(original)
            with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted'):
                restore_prepared_reference(binding, wrong, home=root / 'home')

    def test_symlinked_run_package_or_dependency_is_not_a_durable_proof(self):
        for changed in ('run', 'package', 'dependency'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); original, binding = self.setup_package(root)
                run, snapshot, record = self.frozen_run(root / 'home', original, binding)
                selected = str(original / 'main.usda'); shutil.rmtree(original)
                target = run if changed == 'run' else snapshot if changed == 'package' else snapshot / 'textures/albedo.png'
                moved = root / 'external'
                target.rename(moved)
                target.symlink_to(moved, target_is_directory=changed != 'dependency')
                with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted'):
                    restore_prepared_reference(binding, selected, home=root / 'home')

    def test_symlinked_home_is_rejected_with_refresh_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            home = root / 'home'; self.frozen_run(home, original, binding)
            linked = root / 'linked-home'; linked.symlink_to(home, target_is_directory=True)
            selected = str(original / 'main.usda'); shutil.rmtree(original)
            with self.assertRaisesRegex(ValueError, 'prepared_asset_evicted:.*run asset_prepare with new request'):
                restore_prepared_reference(binding, selected, home=linked)

    def test_existing_corrupt_package_does_not_silently_fall_back_to_an_old_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original, binding = self.setup_package(root)
            self.frozen_run(root / 'home', original, binding)
            (original / 'textures/albedo.png').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'existing prepared package'):
                restore_prepared_reference(binding, str(original / 'main.usda'), home=root / 'home')


if __name__ == '__main__':
    unittest.main()
