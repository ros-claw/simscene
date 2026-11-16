import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from asset_lock import verify_runtime
from evidence_lock import create_evidence_lock, verify_evidence_lock


class RuntimeLauncherTests(unittest.TestCase):
    def test_launcher_is_hash_locked_before_any_simulator_starts(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'python.sh').write_bytes(b'changed launcher')
            (root / 'VERSION').write_text('version')
            (root / 'selected.py').write_bytes(b'selected')
            lock = {'isaac_version': 'version',
                    'launcher_sha256': hashlib.sha256(b'original launcher').hexdigest(),
                    'files': {'selected.py': hashlib.sha256(b'selected').hexdigest()}}
            with self.assertRaises(ValueError):
                verify_runtime(root / 'python.sh', lock)


class EvidenceLockTests(unittest.TestCase):
    def test_mutation_of_any_frozen_result_or_observation_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename in ('telemetry.jsonl', 'metadata.json', 'result.json', 'process-exit.json', 'worker.log'):
                (root / filename).write_text(filename)
            digest = create_evidence_lock(root, 'positive', 0)
            self.assertFalse(verify_evidence_lock(root, 'positive', digest)['partial'])
            (root / 'result.json').write_text('modified')
            with self.assertRaises(ValueError):
                verify_evidence_lock(root, 'positive', digest)

    def test_failed_partial_run_records_missing_files_and_is_not_complete(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'worker.log').write_text('failure')
            digest = create_evidence_lock(root, 'zero', 1)
            locked = verify_evidence_lock(root, 'zero', digest)
            self.assertTrue(locked['partial'])
            self.assertIsNone(locked['files']['result.json'])
            with self.assertRaises(FileExistsError):
                create_evidence_lock(root, 'zero', 1)


if __name__ == '__main__':
    unittest.main()
