import hashlib
import tempfile
import unittest
from pathlib import Path

from asset_lock import verify_asset_files, verify_runtime


class AssetLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'jetbot.usda').write_bytes(b'root')
        (self.root / 'payloads').mkdir()
        (self.root / 'payloads/physics.usda').write_bytes(b'physics')
        self.lock = {'asset': 'jetbot.usda', 'total_bytes': 11, 'files': [
            {'path': 'jetbot.usda', 'bytes': 4, 'sha256': hashlib.sha256(b'root').hexdigest()},
            {'path': 'payloads/physics.usda', 'bytes': 7, 'sha256': hashlib.sha256(b'physics').hexdigest()},
        ]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_files_and_hashes_admitted(self):
        self.assertEqual(set(verify_asset_files(self.root / 'jetbot.usda', self.lock)),
                         {'jetbot.usda', 'payloads/physics.usda'})

    def test_corrupt_or_missing_file_rejected(self):
        (self.root / 'payloads/physics.usda').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            verify_asset_files(self.root / 'jetbot.usda', self.lock)
        (self.root / 'payloads/physics.usda').unlink()
        with self.assertRaises(ValueError):
            verify_asset_files(self.root / 'jetbot.usda', self.lock)

    def test_path_escape_duplicates_and_symlinks_rejected(self):
        self.lock['files'][1]['path'] = '../other.usda'
        with self.assertRaises(ValueError):
            verify_asset_files(self.root / 'jetbot.usda', self.lock)
        self.lock['files'][1]['path'] = 'jetbot.usda'
        with self.assertRaises(ValueError):
            verify_asset_files(self.root / 'jetbot.usda', self.lock)
        self.lock['files'][1]['path'] = 'payloads/physics.usda'
        (self.root / 'payloads/physics.usda').unlink()
        (self.root / 'payloads/physics.usda').symlink_to(self.root / 'jetbot.usda')
        with self.assertRaises(ValueError):
            verify_asset_files(self.root / 'jetbot.usda', self.lock)


class RuntimeLockTests(unittest.TestCase):
    def test_selected_runtime_version_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'python.sh').write_text('launcher')
            (root / 'VERSION').write_text('release-v1')
            (root / 'module.py').write_text('source')
            lock = {'isaac_version': 'release-v1', 'launcher_sha256': hashlib.sha256(b'launcher').hexdigest(), 'files': {
                'module.py': hashlib.sha256(b'source').hexdigest()}}
            self.assertEqual(verify_runtime(root / 'python.sh', lock), root)
            (root / 'module.py').write_text('changed')
            with self.assertRaises(ValueError):
                verify_runtime(root / 'python.sh', lock)
            lock['files'] = {'../escape': '0' * 64}
            with self.assertRaises(ValueError):
                verify_runtime(root / 'python.sh', lock)


if __name__ == '__main__':
    unittest.main()
