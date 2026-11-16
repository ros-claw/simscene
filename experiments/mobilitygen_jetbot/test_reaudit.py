import json
from pathlib import Path
import tempfile
import unittest

from audit_output import audit_output
from evidence_lock import create_evidence_lock


class ReauditTests(unittest.TestCase):
    def test_changed_evidence_is_rejected_before_reading_result(self):
        for changed in ('telemetry.jsonl', 'metadata.json', 'result.json', 'process-exit.json', 'worker.log'):
            with self.subTest(file=changed), tempfile.TemporaryDirectory() as name:
                root = Path(name); locks = {}
                for mode in ('positive', 'zero'):
                    run = root / 'runs' / mode; run.mkdir(parents=True)
                    for filename in ('telemetry.jsonl', 'metadata.json', 'result.json', 'process-exit.json', 'worker.log'):
                        (run / filename).write_text(filename)
                    locks[mode] = create_evidence_lock(run, mode, 0)
                (root / 'run-manifest.json').write_text(json.dumps({
                    'schema': 'simscene.mobilitygen_jetbot.run.v1', 'evidence_locks': locks}))
                (root / 'runs' / 'positive' / changed).write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'evidence missing or changed'):
                    audit_output(root)


if __name__ == '__main__':
    unittest.main()
