"""Online discovery alone must never count as acquisition and simulation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]

class OnlineVerifierTest(unittest.TestCase):
    def test_search_and_pending_download_do_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'state'/'runs').mkdir(parents=True)
            checker = root/'frozen-checker.py'; shutil.copyfile(ROOT/'experiments/verify_agent_online.py',checker)
            (root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest())
            (root/'exit-code.txt').write_text('0')
            def event(tool, args, value):
                return {'type':'item.completed','item':{'type':'mcp_tool_call','status':'completed',
                        'tool':tool,'arguments':args,'result':{'content':[{'type':'text','text':json.dumps(value)}]}}}
            url='https://example.com/model.usd'
            rows=[event('asset_search',{}, {'hits':[{'url':url}]}), event('asset_inspect',{'asset_url':url},{}),
                  event('asset_acquire',{'asset_url':url},{'job_id':'abc'}), event('job_status',{'job_id':'abc'},{'job_id':'abc','state':'running'})]
            (root/'trace.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
            proc=subprocess.run([sys.executable,str(checker),str(root)],capture_output=True,text=True,
                                env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),check=False)
            self.assertEqual(proc.returncode,1,proc.stderr)
            report=json.loads(proc.stdout)
            self.assertTrue(report['checks']['public_search_returned_candidates'])
            self.assertFalse(report['checks']['selected_result_was_inspected_and_acquired'])
            self.assertFalse(report['checks']['completed_run_used_selected_asset'])
            self.assertFalse(report['passed'])

if __name__ == '__main__': unittest.main()
