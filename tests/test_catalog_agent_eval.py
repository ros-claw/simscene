"""Synthetic CLI/trace checks only; no model, MCP, network or simulator execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiments import eval_catalog_agent as harness


class CatalogAgentEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'portable'
        (self.package/'server/vendor/simscene').mkdir(parents=True)
        (self.package/'server/launch.py').write_text('raise AssertionError("must not execute in CPU fixtures")\n')
        (self.package/'server/vendor/simscene/__init__.py').write_text('# synthetic fixture\n')
        skill=self.package/'skills/build-scene';skill.mkdir(parents=True);(skill/'SKILL.md').write_text('Synthetic installed skill\n')
        self.task=self.root/'task';self.task.mkdir()
        definition={'schema_version':1,'task_id':'synthetic-contract','prompt_file':'prompt.md','recipe_file':'recipe.json',
                    'asset_lock_file':'assets.lock.json','case_template_file':'case.json'}
        (self.task/'agent-task.json').write_text(json.dumps(definition))
        (self.task/'prompt.md').write_text('Synthetic fixed task; never execute a model.\n')
        (self.task/'recipe.json').write_text(json.dumps({'objects':{},'run':{'steps':720}}))
        (self.task/'assets.lock.json').write_text(json.dumps({'assets':{}}))
        self.template={'schema':'simscene.rigid_asset_smoke.v1','schema_version':1,'objects':{'fixture':{'min_drop_m':.1}},
                       'prepared_manifest_sha256':harness.MARKER}
        (self.task/'case.json').write_text(json.dumps(self.template))

    def args(self, name='output', *extra):
        return harness.parser().parse_args(['--client','codex','--package',str(self.package),
            '--case',str(self.task/'agent-task.json'),'--output',str(self.root/name),'--model','unexecuted-test-model',
            '--reasoning-effort','medium','--dry-run',*extra])

    def prepared(self, name='output'):
        with (patch.object(harness.subprocess,'Popen',side_effect=AssertionError('no process allowed')),
              patch.object(harness.subprocess,'run',side_effect=AssertionError('no process allowed'))):
            return harness.prepare(self.args(name))

    def trace(self, output, usage=True):
        self.prepared_hash='a'*64;self.job_id='b'*32;self.prep_id='prep-'+'c'*32
        def event(identifier,tool,payload,args=None,status='completed'):
            return {'type':'item.completed','item':{'id':identifier,'type':'mcp_tool_call','server':'simscene',
                'tool':tool,'arguments':args or {},'result':{'structured_content':payload},'error':None,'status':status}}
        events=[event('search','catalog_search',{'items':[]},{'filters':{'source_ids':['abo-glb','nvidia-usd-search']}}),
                event('acquire','asset_acquire',{'job_id':'local-fixture'}),event('plan','asset_plan',{'ready_to_fetch':True}),
                event('prepare','asset_prepare',{'job_id':self.prep_id}),
                event('status','job_status',{'job_id':self.prep_id,'state':'completed','result':{'manifest_sha256':self.prepared_hash}}),
                event('simulate','simulation_start',{'job_id':self.job_id})]
        if usage:events.append({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':40,
            'output_tokens':20,'reasoning_output_tokens':5}})
        (output/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n')
        prep=output/'state/preparation_jobs'/self.prep_id;prep.mkdir(parents=True)
        (prep/'job.json').write_text(json.dumps({'job_id':self.prep_id,'state':'completed','result':{'manifest_sha256':self.prepared_hash},'actual_download_bytes':0}))
        case=deepcopy(self.template);case['prepared_manifest_sha256']=self.prepared_hash
        (output/'work/submission-case.json').write_text(json.dumps(case))
        (output/'work/submission.json').write_text(json.dumps({'attempted_simulation_job_ids':[self.job_id],'passed':True}))
        return events

    def fake_verifier(self, output, case):
        return {'runs':[{'job_id':self.job_id,'passed':True,'scope':'synthetic test report; no physics executed'}]}

    def test_import_and_dry_run_never_launch_processes(self):
        with (patch.object(harness.subprocess,'Popen',side_effect=AssertionError('unexpected process')),
              patch.object(harness.subprocess,'run',side_effect=AssertionError('unexpected process'))):
            spec=importlib.util.spec_from_file_location('fresh_catalog_eval',harness.__file__)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            args=self.args();self.assertEqual(module.main(['--package',args.package,'--case',args.case,
                '--output',args.output,'--model',args.model,'--dry-run']),0)
        output=Path(args.output);meta=json.loads((output/'evaluation-config.json').read_text())
        self.assertEqual(meta['model'],'unexecuted-test-model');self.assertIsNone(meta['client_version'])
        self.assertIn('--ignore-user-config',meta['command'])
        self.assertTrue(harness.NEW_TOOLS<=set(meta['tool_allowlist']))
        self.assertNotIn('environment_configure',meta['tool_allowlist'])
        self.assertEqual((output/'work/.agents/skills/build-scene/.simscene-plugin-root').read_text().strip(),str(self.package))
        self.assertFalse((output/'events.jsonl').exists())
        self.assertEqual(json.loads((output/'work/task/case.json').read_text()),self.template)

    def test_frozen_case_allows_only_actual_prepared_identity(self):
        bound=deepcopy(self.template);bound['prepared_manifest_sha256']='a'*64
        self.assertEqual(harness.validate_case(self.template,bound,{'a'*64}),'a'*64)
        with self.assertRaises(ValueError):harness.validate_case(self.template,bound,{'b'*64})
        bound['objects']['fixture']['min_drop_m']=0
        with self.assertRaises(ValueError):harness.validate_case(self.template,bound,{'a'*64})
        self.assertEqual(self.template['objects']['fixture']['min_drop_m'],.1)

    def test_trace_host_pass_and_cached_tokens_are_not_added_twice(self):
        output,_=self.prepared();self.trace(output)
        result=harness.evaluate_output(output,{'exit_code':0,'timed_out':False},self.fake_verifier)
        self.assertTrue(result['passed'],result['errors'])
        usage=result['usage']['aggregate_reported_usage']
        self.assertEqual(usage['total_tokens'],120);self.assertEqual(usage['uncached_input_tokens'],60)
        self.assertEqual(usage['cached_input_tokens'],40)
        self.assertEqual(result['usage']['usage_availability'],'aggregate_only')

    def test_agent_pass_flag_cannot_override_business_failure_or_timeout(self):
        output,_=self.prepared();self.trace(output,usage=False)
        result=harness.evaluate_output(output,{'exit_code':0,'timed_out':False},lambda *_:{'runs':[{'job_id':self.job_id,'passed':False}]})
        self.assertFalse(result['passed']);self.assertIsNone(result['usage']['aggregate_reported_usage'])
        result=harness.evaluate_output(output,{'exit_code':None,'timed_out':True},self.fake_verifier,result_filename='timeout-audit.json')
        self.assertFalse(result['passed']);self.assertEqual(result['usage']['usage_availability'],'unknown')

    def test_template_tampering_missing_tools_and_partial_proof_fail(self):
        output,_=self.prepared();events=self.trace(output)
        (output/'work/task/recipe.json').write_text('{}')
        result=harness.evaluate_output(output,{'exit_code':0},self.fake_verifier)
        self.assertFalse(result['passed']);self.assertIn('frozen task/package inputs changed',result['errors'])
        events=[e for e in events if e.get('item',{}).get('tool')!='asset_plan']
        (output/'events.jsonl').write_text('\n'.join(map(json.dumps,events))+'\n')
        result=harness.evaluate_output(output,{'exit_code':0},self.fake_verifier,result_filename='missing-tools-audit.json')
        self.assertFalse(result['passed']);self.assertFalse(result['trace']['required_new_tools_called'])

    def test_invalid_trace_and_unapproved_tools_preserve_errors_and_statuses(self):
        path=self.root/'trace.jsonl'
        started={'type':'item.started','item':{'id':'call','type':'mcp_tool_call','server':'other','tool':'publish',
                  'status':'in_progress'}}
        failed={'type':'item.completed','item':{'id':'call','type':'mcp_tool_call','server':'other','tool':'publish',
                 'status':'failed','error':{'message':'denied'}}}
        path.write_text(json.dumps(started)+'\nnot json\n'+json.dumps(failed)+'\n')
        observed=harness.analyze_trace(path)
        self.assertEqual(observed['invalid_lines'],[2]);self.assertTrue(observed['scope_violations'])
        self.assertEqual(observed['calls'][0]['statuses'],['in_progress','failed'])
        self.assertEqual(observed['calls'][0]['error'],{'message':'denied'})

    def test_public_four_body_task_dry_run_freezes_original_inputs(self):
        task=Path(harness.__file__).resolve().parents[1]/'examples/catalog_gravity_cell/agent-task.json'
        args=self.args('public-output');args.case=str(task)
        before=harness.hashes(task.parent)
        with patch.object(harness.subprocess,'Popen',side_effect=AssertionError('no client launch')):
            output,meta=harness.prepare(args)
        copied=json.loads((output/'work/task/case.json').read_text())
        self.assertEqual(len(copied['objects']),4)
        self.assertEqual(copied['prepared_manifest_sha256'],harness.MARKER)
        self.assertEqual(before,harness.hashes(task.parent))
        self.assertEqual(meta['cache_condition'],'unknown')

    def test_startup_failure_and_pending_job_remain_unknown_not_zero(self):
        output,meta=self.prepared();pending=output/'state/runs/pending';pending.mkdir(parents=True)
        (pending/'job.json').write_text(json.dumps({'job_id':'pending-job'}))
        with (patch.object(harness.subprocess,'run',side_effect=FileNotFoundError('codex unavailable')),
              patch.object(harness.subprocess,'Popen',side_effect=AssertionError('must not launch'))):
            result=harness.run(output,meta)
        self.assertFalse(result['passed']);self.assertIsNone(result['completion']['exit_code'])
        self.assertEqual(result['usage']['usage_availability'],'unknown')
        self.assertIsNone(result['usage']['aggregate_reported_usage'])
        self.assertEqual(result['persisted_run_receipts'][0]['status'],'unknown_without_exit_record')
        self.assertIsNone(result['persisted_run_receipts'][0]['process_exit'])

    def audit_command(self, script):
        path=self.root/'shell-trace.jsonl'
        command='/bin/bash -lc '+harness.shlex.quote(script)
        path.write_text(json.dumps({'type':'item.completed','item':{'id':'shell','type':'command_execution',
            'command':command,'status':'completed','exit_code':0}})+'\n')
        return harness.analyze_trace(path,self.root/'work')

    def test_quoted_data_heredocs_allow_recorded_paths_without_executing_them(self):
        for header in ["cat > submission.json <<'DATA_EOF'", 'tee submission.json <<"DATA_EOF"']:
            script=header+'\n'+json.dumps({'asset_path':'/external/cache/asset.usda','literal':'$(cat /etc/secret); import simscene'})+'\nDATA_EOF\n'
            observed=self.audit_command(script)
            self.assertEqual(observed['scope_violations'],[])
            event=observed['command_events'][0]
            self.assertEqual(event['masked_quoted_data_blocks'],1)
            self.assertNotIn('command',event)
            self.assertLessEqual(len(event['command_excerpt']),240)

    def test_heredoc_mask_preserves_following_external_reads_and_unsafe_bodies(self):
        scripts=[
            "cat > submission.json <<'EOF'\n{\"path\":\"/external/cache\"}\nEOF\ncat /etc/secret\n",
            "cat > submission.json <<'EOF'; cat /etc/secret\n{}\nEOF\n",
            "cat > submission.json <<EOF\n$(cat /etc/secret)\nEOF\n",
            "python3 - <<'PY'\nimport simscene\nPY\n",
            "cat /etc/secret > submission.json <<'EOF'\n{}\nEOF\n",
            "tee submission.json <<'EOF' | python3\nimport simscene\nEOF\n",
        ]
        for script in scripts:
            with self.subTest(header=script.splitlines()[0]):
                observed=self.audit_command(script)
                self.assertTrue(observed['scope_violations'])
                self.assertTrue(all('command' not in item and 'command_sha256' in item for item in observed['scope_violations']))
        self.assertTrue(self.audit_command('cat /etc/secret')['scope_violations'])

    def test_nullable_catalog_filters_do_not_crash_trace_analysis(self):
        path=self.root/'nullable.jsonl'
        path.write_text(json.dumps({'type':'item.completed','item':{'id':'nullable','type':'mcp_tool_call',
            'server':'simscene','tool':'catalog_search','arguments':{'filters':None},'result':{},'status':'completed'}})+'\n')
        self.assertEqual(harness.analyze_trace(path)['explicit_sources_searched'],[])

    def test_reassessment_is_new_file_with_original_and_evaluator_hashes(self):
        output,_=self.prepared();self.trace(output)
        harness.evaluate_output(output,{'exit_code':0,'timed_out':False},self.fake_verifier)
        original=(output/'evaluation-result.json').read_bytes();original_hash=harness.digest(output/'evaluation-result.json')
        with self.assertRaises(ValueError):harness.evaluate_output(output,{'exit_code':0},self.fake_verifier)
        result=harness.evaluate_output(output,{'exit_code':0},self.fake_verifier,result_filename='evaluation-result.audit-v2.json')
        self.assertTrue(result['passed'])
        self.assertEqual((output/'evaluation-result.json').read_bytes(),original)
        self.assertEqual(result['reassessment']['original_result_sha256'],original_hash)
        self.assertEqual(result['evaluator_sha256'],harness.digest(harness.__file__))
        self.assertEqual(result['trace_sha256'],harness.digest(output/'events.jsonl'))
        with self.assertRaises(ValueError):harness.evaluate_output(output,{'exit_code':0},self.fake_verifier,result_filename='../outside.json')

    def physical_fixture(self):
        example=Path(harness.__file__).resolve().parents[1]/'examples/catalog_gravity_cell'
        recipe=json.loads((example/'recipe.json').read_text());case=json.loads((example/'case.json').read_text())
        spec={'objects':deepcopy(recipe['objects'])};manifests={}
        for name,obj in spec['objects'].items():
            role=obj.pop('asset_role',None)
            if role=='notebook':
                obj['asset_path']='/resolved/prepared/main.usda';obj['asset_binding']={'manifest_sha256':'a'*64}
                manifests[name]={'profile_id':recipe['asset_roles']['notebook']['profile_id'],
                                 'parameters':deepcopy(recipe['asset_roles']['notebook']['parameters'])}
            elif role=='workbench':obj['asset_path']='/resolved/locked/table.usd'
        return recipe,spec,case,manifests

    def test_fixed_physical_recipe_and_source_coverage_reject_omitted_workbench(self):
        recipe,spec,case,manifests=self.physical_fixture()
        self.assertTrue(harness.validate_recipe_contract(recipe,spec,case,manifests))
        sources={name:True for name in case['objects']}
        with self.assertRaises(ValueError):harness.require_source_coverage(case,sources)
        sources['workbench']=True;self.assertTrue(harness.require_source_coverage(case,sources))
        del spec['objects']['workbench']
        with self.assertRaises(ValueError):harness.validate_recipe_contract(recipe,spec,case,manifests)

    def test_prepared_mass_scale_and_profile_must_equal_public_role(self):
        for field,value in [('mass_kg',.2),('target_longest_extent_m',.2),('profile_id','visual_prop_v1')]:
            recipe,spec,case,manifests=self.physical_fixture();manifest=manifests[next(iter(case['objects']))]
            if field=='profile_id':manifest[field]=value
            else:manifest['parameters'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                harness.validate_recipe_contract(recipe,spec,case,manifests)

    def test_physical_actor_and_material_changes_fail_tiny_float_differences_pass(self):
        recipe,spec,case,manifests=self.physical_fixture()
        spec['objects']['ramp_left']['position'][0]+=5e-7
        self.assertTrue(harness.validate_recipe_contract(recipe,spec,case,manifests))
        self.assertFalse(harness.recipe_equal(True,1))
        spec['objects']['unexpected']={'kind':'box','collision':True,'size':[1,1,1]}
        with self.assertRaises(ValueError):harness.validate_recipe_contract(recipe,spec,case,manifests)
        del spec['objects']['unexpected'];spec['objects']['ramp_left']['physics']['dynamic_friction']=.1
        with self.assertRaises(ValueError):harness.validate_recipe_contract(recipe,spec,case,manifests)
        recipe,spec,case,manifests=self.physical_fixture()
        spec['objects']['optional_camera']={'kind':'camera','position':[1,2,3]}
        spec['objects']['optional_visual']={'kind':'box','collision':False,'dynamic':False}
        self.assertTrue(harness.validate_recipe_contract(recipe,spec,case,manifests))

    def test_no_overwrite_path_traversal_and_shared_cache_are_explicit(self):
        config=self.root/'existing-v2.json';shared=self.root/'shared-cache'
        config.write_text(json.dumps({'index_directory':str(self.root/'shared-index')}));before=config.read_bytes()
        args=self.args('shared-output','--cache-root',str(shared),'--v2-config',str(config),'--cache-condition','warm')
        output,meta=harness.prepare(args)
        self.assertEqual(config.read_bytes(),before)
        self.assertEqual(meta['cache_condition'],'warm');self.assertEqual(meta['cache_root'],str(shared))
        self.assertEqual(json.loads((output/'v2.json').read_text())['prepared_directory'],str(shared.with_name(shared.name+'-prepared-v1')))
        with self.assertRaises(ValueError):harness.prepare(args)
        for unsafe in ('../outside.json','/absolute.json','nested/../case.json'):
            with self.subTest(path=unsafe),self.assertRaises(ValueError):harness.member(unsafe)


if __name__=='__main__':unittest.main()
