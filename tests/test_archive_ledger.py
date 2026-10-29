import json,tempfile,unittest
from pathlib import Path
from simscene.verification.archive_ledger import verify

class ArchiveLedgerTest(unittest.TestCase):
    def test_ledger_must_match_each_terminal_event_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);event={'part_id':'part1','terminal_state':'correct','physics_step':120}
            run={'archived_objects':{'part1':event}}
            self.assertFalse(verify(root,run))
            path=root/'archive-ledger.jsonl';path.write_text(json.dumps(event)+'\n')
            self.assertTrue(verify(root,run))
            path.write_text(json.dumps(event)+'\n'+json.dumps(event)+'\n')
            self.assertFalse(verify(root,run))
            path.write_text(json.dumps(dict(event,physics_step=121))+'\n')
            self.assertFalse(verify(root,run))
