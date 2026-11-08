"""CPU fixtures only: no Codex, model, MCP, SDK or network execution."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from experiments import eval_catalog_efficiency as ev


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        protocol=ev.read(ev.DEFAULT_PROTOCOL)
        protocol['hardware'].update(host='fixture-host',gpu='fixture-gpu',isaac='fixture-sdk',usd='fixture-usd',renderer='fixture-renderer')
        self.protocol=self.root/'protocol.json'; ev.write_new(self.protocol,protocol)
        self.packages=[]
        for version in ('baseline','candidate'):
            package=self.root/version; (package/'server').mkdir(parents=True)
            (package/'server/launch.py').write_text('# fixture never launch\n')
            (package/'skills/build-scene').mkdir(parents=True)
            (package/'skills/build-scene/SKILL.md').write_text('fixture skill\n')
            self.packages.append(package)
        self.verifier=self.root/'host_verify.py'; self.verifier.write_text('# mocked host-only verifier\n')
        bindings={'verifier':str(self.verifier),'tasks':{}}
        for task in ev.read(ev.DEFAULT_TASKS)['tasks']:
            source=self.root/task['id'];source.mkdir();(source/'acceptance.json').write_text(json.dumps(task['acceptance']))
            (source/'assets.lock.json').write_text('{"source_sha256":"fixture"}')
            if task['cache']=='paired_warm':
                (source/'cache').mkdir();(source/'cache/frozen-native.usd').write_text('# source fixture')
            bindings['tasks'][task['id']]={'inputs':str(source),'acceptance_file':'acceptance.json'}
        self.bindings=self.root/'bindings.json';ev.write_new(self.bindings,bindings)

    def plan(self,pilot=True):
        return ev.freeze(self.protocol,ev.DEFAULT_TASKS,self.bindings,*self.packages,'c'*40,pilot=pilot)

    def events(self,events):
        path=self.root/'events.jsonl';path.write_text('\n'.join(json.dumps(e) for e in events)+'\n');return path

    def test_usage_identity_dedup_subsets_and_conflicting_or_unknown_counters(self):
        row={'type':'turn.completed','turn_id':'one','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':20,'reasoning_output_tokens':5}}
        value=ev.usage(self.events([row,row]))
        self.assertEqual(value['aggregate']['total_tokens'],120)
        self.assertEqual(value['aggregate']['uncached_input_tokens'],60)
        altered=copy.deepcopy(row);altered['usage']['output_tokens']=21
        self.assertIsNone(ev.usage(self.events([row,altered]))['aggregate'])
        anonymous=copy.deepcopy(row);anonymous.pop('turn_id')
        self.assertIsNone(ev.usage(self.events([anonymous,anonymous]))['aggregate'])
        failed={'type':'turn.failed','turn_id':'two'}
        partial=ev.usage(self.events([row,failed]));self.assertIsNone(partial['aggregate'])
        self.assertEqual(partial['known_reported_subtotal']['total_tokens'],120)
        self.assertIsNone(ev.usage(self.events([]))['aggregate'])

    def test_schedule_crosses_order_keeps_pair_cache_and_caps(self):
        pilot=self.plan();self.assertEqual(len(pilot['schedule']),4)
        self.assertEqual([r['version'] for r in pilot['schedule']],['baseline','candidate','candidate','baseline'])
        full=self.plan(False);self.assertEqual(len(full['schedule']),36)
        self.assertEqual(pilot['comparison_fingerprint'],full['comparison_fingerprint'])
        self.assertEqual(full['protocol']['max_full_wall_s'],36*full['protocol']['wall_limit_s'])
        for pair in {r['pair_id'] for r in full['schedule']}:
            rows=[r for r in full['schedule'] if r['pair_id']==pair]
            self.assertEqual(len(rows),2);self.assertEqual(rows[0]['cache'],rows[1]['cache'])
        self.assertEqual({t['group'] for t in full['tasks']},{'A','B'})

    def test_freeze_no_launch_model_explicit_and_input_drift_fails(self):
        with patch.object(ev.subprocess,'Popen',side_effect=AssertionError('no launch')),patch.object(ev.subprocess,'run',side_effect=AssertionError('no launch')):
            plan=self.plan();ev.verify_plan(plan)
        plan['protocol']['model']='changed'
        with self.assertRaisesRegex(ValueError,'hash changed'):ev.verify_plan(plan)
        plan=self.plan();(self.packages[0]/'server/launch.py').write_text('drift')
        with self.assertRaisesRegex(ValueError,'package drift'):ev.verify_plan(plan)

    def test_missing_hardware_or_warm_seed_prevents_freeze(self):
        protocol=ev.read(self.protocol);protocol['hardware']['gpu']=None;self.protocol.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError,'hardware'):self.plan()

    def test_phase_union_not_double_count_and_unknown_is_null(self):
        result=ev.phase_seconds([{'phase':'simulation','start_s':1,'end_s':4},{'phase':'simulation','start_s':3,'end_s':5}])
        self.assertEqual(result['simulation'],4);self.assertIsNone(result['render'])
        with self.assertRaises(ValueError):ev.phase_seconds([{'phase':'render','start_s':2,'end_s':1}])

    def row(self,plan,trial,status='passed',tokens=100):
        return dict(trial,plan_sha256=plan['plan_sha256'],status=status,
                    completion={'wall_s':10,'client_version':'codex-fixture'},usage={'aggregate':{'total_tokens':tokens} if tokens is not None else None},
                    manual_interventions=[],trace_sha256='fixture',verifier={'passed':status=='passed'})

    def test_aggregate_includes_failures_timeouts_unknown_and_no_capgap_savings(self):
        plan=self.plan();rows=[self.row(plan,t) for t in plan['schedule']]
        rows[0]['status']='timeout';rows[0]['usage']['aggregate']=None
        rows[2]['status']='capability_gap'
        report=ev.aggregate(plan,rows)
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['groups']['A']['versions']['baseline']['all_trial_wall_s'],10)
        self.assertEqual(report['groups']['A']['versions']['baseline']['missing_usage_trials'],1)
        self.assertIsNone(report['groups']['A']['median_paired_token_ratio'])
        self.assertIsNone(report['groups']['B']['median_paired_token_ratio'])
        self.assertIsNone(report['savings_claim'])
        with self.assertRaisesRegex(ValueError,'duplicate'):ev.aggregate(plan,rows+[rows[0]])
        rows[0]['cache']='forged'
        with self.assertRaisesRegex(ValueError,'pairing'):ev.aggregate(plan,rows)

    def test_actual_run_command_isolated_and_host_not_agent_decides_pass(self):
        plan=self.plan();output=self.root/'trial';processes=[]
        class Process:
            returncode=0
            def __init__(self,cmd,**kwargs):
                import io
                self.stdin=io.StringIO();processes.append((cmd,kwargs))
                for row in [
                    {'type':'turn.completed','turn_id':'turn-1','usage':{'input_tokens':10,'output_tokens':5}},
                    {'type':'item.completed','item':{'id':'answer','type':'agent_message','text':'PASS!'}}]:
                    kwargs['stdout'].write(json.dumps(row)+'\n')
                kwargs['stdout'].flush()
            def poll(self):return 0
        def run(cmd,**kwargs):
            from types import SimpleNamespace
            if cmd[:2]==['codex','--version']:return SimpleNamespace(stdout='codex-fixture',returncode=0)
            self.assertEqual(cmd[1],str(self.verifier));self.assertIn('--acceptance',cmd)
            return SimpleNamespace(stdout=json.dumps({'passed':True,'provenance_verified':True,'quality_verified':False}),stderr='',returncode=0)
        with patch.object(ev.subprocess,'Popen',Process),patch.object(ev.subprocess,'run',run):
            result=ev.run_trial(plan,plan['schedule'][0]['trial_id'],output)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['usage']['aggregate']['total_tokens'],15)
        cmd,kwargs=processes[0];self.assertEqual(cmd[0:2],['codex','exec'])
        self.assertIn(str(self.packages[0]/'server/launch.py'),' '.join(cmd))
        self.assertEqual(kwargs['env']['SIMSCENE_HOME'],str(output/'state'))
        self.assertTrue((output/'trial-result.json').is_file())
        with self.assertRaisesRegex(ValueError,'new output'):ev.run_trial(plan,plan['schedule'][0]['trial_id'],output)

    def test_actual_timeout_terminates_group_and_retains_reported_cost(self):
        plan=self.plan();output=self.root/'timeout';signals=[]
        class Process:
            pid=424242
            returncode=None
            def __init__(self,cmd,**kwargs):
                import io
                self.stdin=io.StringIO()
                kwargs['stdout'].write(json.dumps({'type':'turn.completed','turn_id':'turn-1','usage':{'input_tokens':10,'output_tokens':5}})+'\n')
                kwargs['stdout'].flush()
            def poll(self):return self.returncode
            def wait(self,timeout=None):self.returncode=-15;return self.returncode
        def run(cmd,**kwargs):
            from types import SimpleNamespace
            return SimpleNamespace(stdout='codex-fixture' if cmd[0]=='codex' else json.dumps({'passed':True,'provenance_verified':True,'quality_verified':True}),stderr='',returncode=0)
        with patch.object(ev.subprocess,'Popen',Process),patch.object(ev.subprocess,'run',run), patch.object(ev.time,'monotonic',side_effect=range(0,5000,100)),patch.object(ev.time,'sleep'),patch.object(ev.os,'killpg',side_effect=lambda *x:signals.append(x)):
            result=ev.run_trial(plan,plan['schedule'][0]['trial_id'],output)
        self.assertEqual(result['status'],'timeout');self.assertTrue(signals)
        self.assertEqual(result['usage']['aggregate']['total_tokens'],15)
        self.assertTrue((output/'completion.json').is_file())

    def test_trace_call_history_counted_once_including_tool_failure(self):
        plan=self.plan();output=self.root/'trace';(output/'work').mkdir(parents=True)
        call={'id':'same-call','type':'mcp_tool_call','server':'simscene','tool':'asset_search','result':{'text':'actual'},'status':'in_progress'}
        events=[{'type':'item.started','item':dict(call)}, {'type':'item.completed','item':dict(call,status='failed',error='fixture failure')}]
        (output/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
        result=ev.trial_result(plan,plan['schedule'][0],output,{'exit_code':1,'wall_s':3},{'passed':False})
        self.assertEqual(result['tool_calls'],1);self.assertEqual(result['failed_tool_calls'],1)
        self.assertEqual(result['tool_return_bytes'],len(json.dumps(call['result']).encode()))
        self.assertIsNone(result['usage']['aggregate'])

    def test_clean_pass_pair_ratio_and_client_drift_gate(self):
        plan=self.plan();rows=[self.row(plan,t,tokens=200 if t['version']=='baseline' else 150) for t in plan['schedule']]
        report=ev.aggregate(plan,rows)
        self.assertEqual(report['groups']['A']['median_paired_token_ratio'],.75)
        self.assertIsNone(report['groups']['B']['median_paired_token_ratio'])
        rows[0]['completion']['client_version']='different-client'
        self.assertIsNone(ev.aggregate(plan,rows)['groups']['A']['median_paired_token_ratio'])

    def test_live_poll_ignores_inflight_unterminated_json_line(self):
        path=self.root/'inflight.jsonl';path.write_text('{"type":"turn.completed",')
        self.assertEqual(ev.usage(path,live=True)['errors'],[])
        self.assertTrue(ev.usage(path)['errors'])

    def test_no_actual_results_remain_unknown(self):
        report=ev.aggregate(self.plan(),[])
        self.assertEqual(report['status'],'incomplete');self.assertEqual(len(report['missing_trials']),4)
        self.assertIsNone(report['groups']['A']['median_paired_token_ratio'])


if __name__=='__main__':unittest.main()
