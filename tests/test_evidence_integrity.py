import json,tempfile,unittest
from pathlib import Path
from simscene.evidence_integrity import seal,verify

class EvidenceIntegrityTest(unittest.TestCase):
    def test_output_and_archive_ledger_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'camera.png';image.write_bytes(b'frame')
            video=root/'video.mp4';video.write_bytes(b'video')
            ledger=root/'archive-ledger.jsonl';ledger.write_text('{"part_id":"a"}\n')
            (root/'result.json').write_text(json.dumps({'images':{'view':str(image)},'videos':{'view':{'path':str(video)}},'archived_objects':{'a':{}}}))
            seal(root);self.assertTrue(verify(root)['passed'])
            ledger.write_text('{"part_id":"b"}\n')
            report=verify(root);self.assertFalse(report['passed']);self.assertFalse(report['checks']['archive-ledger.jsonl'])

    def test_external_artifact_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            root=Path(directory);outside=Path(other)/'image.png';outside.write_bytes(b'frame')
            (root/'result.json').write_text(json.dumps({'images':{'view':str(outside)}}))
            with self.assertRaisesRegex(ValueError,'outside the run'):seal(root)
