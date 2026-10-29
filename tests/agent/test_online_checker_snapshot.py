"""The online-agent evaluator recognizes the worker's locked asset snapshot."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OnlineCheckerSnapshot(unittest.TestCase):
    def test_snapshot_is_matched_by_locked_source_and_package(self):
        checker = Path(__file__).resolve().parents[2]/'experiments'/'verify_agent_online.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'state'/'runs'/'run1';run.mkdir(parents=True)
            url='https://assets.example.org/robot.usd';package='a'*64
            acquired='/cache/'+package+'/robot.usd';relative='assets/'+package+'/robot.usd'
            def event(tool,args,payload):
                return {'type':'item.completed','item':{'type':'mcp_tool_call','status':'completed',
                    'tool':tool,'arguments':args,'result':{'content':[{'type':'text','text':json.dumps(payload)}]}}}
            events=[event('asset_search',{}, {'hits':[{'url':url}]}),
                    event('asset_inspect',{'asset_url':url},{}),
                    event('asset_acquire',{'asset_url':url},{'job_id':'download'}),
                    event('job_status',{'job_id':'download'},{'job_id':'download','state':'completed',
                          'result':{'source':url,'root':acquired,'package_sha256':package,
                                    'dependency_status':'resolved_locally','unresolved_dependencies':[]}})]
            (root/'trace.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            (root/'exit-code.txt').write_text('0\n')
            (root/'frozen-checker.py').write_bytes(checker.read_bytes())
            (root/'frozen-checker.sha256').write_text(hashlib.sha256(checker.read_bytes()).hexdigest())
            (run/'spec.json').write_text(json.dumps({'objects':{'robot':{'kind':'asset','asset_path':str(run/relative)}}}))
            (run/'result.json').write_text(json.dumps({'requested_physics_steps':1,'actual_physics_steps':1}))
            lock={'robot':{'kind':'snapshot','source':url,'package_sha256':package,'root_relative_to_run':relative}}
            def evaluate():
                (run/'asset-lock.json').write_text(json.dumps(lock))
                result=subprocess.run([sys.executable,str(checker),str(root)],capture_output=True,text=True,check=False)
                return json.loads(result.stdout)['checks']
            self.assertTrue(evaluate()['completed_run_used_selected_asset'])
            lock['robot']['package_sha256']='b'*64
            self.assertFalse(evaluate()['completed_run_used_selected_asset'])
            lock['robot']['package_sha256']=package
            lock['robot']['source']='https://assets.example.org/other.usd'
            self.assertFalse(evaluate()['completed_run_used_selected_asset'])


if __name__=='__main__':unittest.main()
