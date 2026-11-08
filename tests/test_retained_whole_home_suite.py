"""Synthetic orchestration and exact original-CSV prefix tests, no simulation."""
import ast
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import retained_whole_home_suite as new, whole_home_suite_v7 as old


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    return new.f.sha(path)


def clock_fixture(root):
    n, s, e = 600, 5800, 5798
    flags = [{'physics_step':step, 'simulation_time_s':step/60,
              'active':step % 31 != 0, 'body_ids':['cart'] if step % 31 else [],
              'stage_ids':['cart_phase'] if step % 31 else []} for step in range(n+1,s+1)]
    active=sum(row['active'] for row in flags)
    case={'profile':'P3','release_step':n,'activity':{'stages':[{'id':'cart_phase','bodies':[{'id':'cart'}]}],
          'limits':{'minimum_chain_duration_s':50,'minimum_net_effective_action_s':45,
                    'minimum_motion_occupancy':.85,'maximum_idle_s':2}}}
    metrics={'window_start_step':n,'window_end_step':s,'chain_duration_s':(s-n)/60,
             'net_effective_action_s':active/60,'motion_occupancy':active/(s-n),'maximum_idle_s':1/60}
    case_path=root/'case.json';case_sha=save(case_path,case)
    stock={'passed':True,'mode':'positive','profile':'P3','case_sha256':case_sha,
           'activity':{'passed':True,'metrics':metrics,'per_step_motion_flags':flags},
           'terminal':{'passed':True,'first_whole_entry_step':s}}
    report={'passed':True,'mode':'positive','scope':'Synthetic clock fixture only',
            'run_lock_sha256':'a'*64,'evidence_lock_sha256':'b'*64,'stock':stock,
            'suite_metadata':{'case':case,'lock':{'physics_dt_s':1/60,'created_at_utc':'2026-11-01T01:00:00Z',
                'spec_sha256':'d'*64},'evidence_sha256':{'result.json':'e'*64}}}
    report_path=root/'full-report.json';report_sha=save(report_path,report)
    receipt_path=root/'receipt.json';receipt_sha=save(receipt_path,{
        'recorded_at_utc':'2026-11-01T02:00:00Z','full_report':{'path':str(report_path),'sha256':report_sha}})
    inner=root/'inner.json';outer=root/'outer.json';review=root/'review.json';contract=root/'clock.json';freeze=root/'freeze.json'
    save(inner,{'schema':'synthetic_planes','planes':['inner']});save(outer,{'schema':'synthetic_planes','planes':['outer']})
    geometry=root/'geometry.json';save(geometry,{'synthetic_static_proof':True})
    save(review,{'scope':'independent_static_inner_outer_entry_bounds','passed':True,
        'inner_inside_physical_cavity':True,'physical_cavity_inside_outer':True,
        'files_sha256':{str(geometry):new.f.sha(geometry)}})
    save(contract,{'schema':new.entry.SCHEMA,'case_sha256':case_sha,'inner_contract_sha256':new.f.sha(inner),
        'outer_contract_sha256':new.f.sha(outer),'static_review_sha256':new.f.sha(review)})
    needed=[case_path,inner,outer,review,contract,Path(new.entry.__file__),Path(new.entry.h.__file__),Path(new.f.__file__)]
    save(freeze,{'schema':'simscene.bounded_entry_clock_freeze.v1','frozen_at_utc':'2026-10-31T00:00:00Z',
        'files_sha256':{str(path.resolve()):new.f.sha(path) for path in needed}})
    external={str(path.resolve()):new.f.sha(path) for path in [case_path,inner,outer,contract,review,freeze]}
    cert={'schema':new.entry.SCHEMA,'errors':[],**dict.fromkeys(('file_integrity_verified','supplemental_complete',
        'geometry_queries_complete','bounded_timing_floors_passed','physical_entry_no_escape_complete','inner_no_escape'),True),
        'provenance':{'helper_sha256':new.ORIGINAL_CLOCK_SHA256,'independently_retained_full_report_sha256':report_sha,
            'full_report_path':str(report_path),'original_files_sha256':{'run-lock.json':'a'*64,'evidence-lock.json':'b'*64,
                'result.json':'e'*64,'spec.json':'d'*64},'independently_retained_lock_sha256':{'run-lock.json':'a'*64,'evidence-lock.json':'b'*64},
            'external_files_sha256':external},'actual_first_entry_observed_step_bounds_inclusive':[e,e],
        'original_stock_entry_step':s,'inner_first_entry':{'physics_steps':e},'outer_first_entry':{'physics_steps':e},
        'every_possible_original_prefix':new.entry.prefixes(stock,case,e,e,1/60)}
    cert_path=root/'certificate.json';cert_sha=save(cert_path,cert)
    return report,{'receipt_path':str(receipt_path),'receipt_sha256':receipt_sha},{'path':str(cert_path),'sha256':cert_sha},cert


class RetainedClockTests(unittest.TestCase):
    def test_original_stock_csv_is_preserved_and_physical_clock_uses_exact_byte_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report,record,certificate,_=clock_fixture(root)
            clock=Path(__file__).parent/'fixtures/score_motion_clock.py';csv=root/'stock.csv'
            new.f.export_motion_csv(report['stock'],report['suite_metadata']['case'],csv,clock,1/60)
            before=csv.read_bytes()
            result=new.physical_entry_clock(report,record,certificate,root,clock,csv,'2026-11-01T03:00:00Z',write_csv=True)
            self.assertTrue(result['passed']);self.assertEqual(result['physical_entry_step'],5798)
            prefix=Path(result['physical_prefix_csv']).read_bytes()
            self.assertEqual(prefix,b''.join(before.splitlines(keepends=True)[:5199]))
            self.assertEqual(csv.read_bytes(),before)
            self.assertEqual(result['user_clock_metrics']['step_intervals'],5198)
            self.assertAlmostEqual(result['metrics']['chain_duration_s'],5198/60)
            self.assertTrue(result['prefix_rows_byte_identical'])

    def test_incomplete_foreign_or_changed_clock_proof_is_rejected(self):
        mutations=('schema','incomplete','escape','noncollapsed','wrong_report','wrong_result','wrong_mask','late_receipt',
                   'bad_prefix_metrics','static_changed','missing_freeze_source','failed_prefix','wrong_inner_step')
        for mutation in mutations:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);report,record,certificate,cert=clock_fixture(root)
                if mutation=='schema':cert['schema']='unknown'
                if mutation=='incomplete':cert['supplemental_complete']=False
                if mutation=='escape':cert['inner_no_escape']=False
                if mutation=='noncollapsed':cert['actual_first_entry_observed_step_bounds_inclusive'][1]+=1
                if mutation=='wrong_report':cert['provenance']['independently_retained_full_report_sha256']='0'*64
                if mutation=='wrong_result':cert['provenance']['original_files_sha256']['result.json']='0'*64
                if mutation=='wrong_mask':cert['every_possible_original_prefix']['original_full_masks_sha256']='0'*64
                if mutation=='bad_prefix_metrics':cert['every_possible_original_prefix']['prefixes'][0]['metrics']['net_effective_action_s']+=1/60
                if mutation=='failed_prefix':cert['every_possible_original_prefix']['prefixes'][0]['passed']=False
                if mutation=='wrong_inner_step':cert['inner_first_entry']['physics_steps']+=1
                if mutation=='static_changed':save(root/'geometry.json',{'changed':True})
                if mutation=='missing_freeze_source':
                    path=root/'freeze.json';value=json.loads(path.read_text());value['files_sha256'].pop(str(Path(new.entry.__file__).resolve()))
                    save(path,value);cert['provenance']['external_files_sha256'][str(path.resolve())]=new.f.sha(path)
                if mutation=='late_receipt':
                    path=Path(record['receipt_path']);value=json.loads(path.read_text());value['recorded_at_utc']='2026-11-01T04:00:00Z'
                    record['receipt_sha256']=save(path,value)
                certificate['sha256']=save(Path(certificate['path']),cert)
                with self.assertRaises((ValueError,KeyError)):
                    new.physical_entry_clock(report,record,certificate,root,None,None,'2026-11-01T03:00:00Z',write_csv=False)


class OriginalGateIdentityTests(unittest.TestCase):
    def test_all_original_final_gates_are_identical_and_original_functions_reused(self):
        def gates(module):
            node=next(n for n in ast.parse(Path(module.__file__).read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='verify_suite')
            start=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='manifest_matches')
            end=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='checks')
            return [ast.dump(n,include_attributes=False) for n in node.body[start:end+1]]
        self.assertEqual(gates(new),gates(old))
        for name in ('verify_freeze','compare_variant','compare_variant_contract','consecutive_three',
                     'check_attempt_inventory','verify_native','save_run_report'):
            self.assertIs(getattr(new,name),getattr(old,name),name)
        tree=ast.parse(Path(new.__file__).read_text())
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='verify_one' for n in ast.walk(tree)))


def workflow_fixture(root):
    builder=root/'builder/state/runs';project=root/'project';replay_root=project/'state/runs'
    names=['positive_1','positive_2','positive_3','no_trigger','broken_rope','locked_door','variant','replay']
    rows={};records={};ledger=[]
    for index,name in enumerate(names):
        run=(replay_root if name=='replay' else builder)/('run'+str(index))
        lock={key:'same-'+key for key in new.f.m.PAIRED_MANIFEST_FIELDS}
        lock.update(run_id=run.name,created_at_utc=f'2026-11-01T01:{index:02d}:00Z',acceptance_case_sha256='c'*64)
        save(run/'run-lock.json',lock);save(run/'spec.json',{'synthetic':True})
        mode=name if name in ('no_trigger','broken_rope','locked_door') else 'positive'
        current={'passed':True,'mode':mode,'scope':'Synthetic workflow only','stock':{'passed':True,'mode':mode},
            'suite_metadata':{'passed':True,'lock':lock,'case':{'synthetic_case':True},'canonical_spec':{},
                'geometry_settings':{'synthetic':True},'integrity':{'case_sha256':'c'*64},'native_metadata':{}}}
        full=root/'retained'/name/'full.json';report_sha=save(full,current)
        receipt=root/'retained'/name/'receipt.json';receipt_sha=save(receipt,{'synthetic':True})
        records[name]={'receipt_path':str(receipt),'receipt_sha256':receipt_sha}
        rows[str(run)]=(current,{'passed':True,'original_full_report_sha256':report_sha})
        ledger.append({'kind':'main_positive' if name.startswith('positive') else name,'run_directory':str(run)})
    ledger_path=root/'attempts.json';save(ledger_path,ledger)
    source=project/'scene.json';save(source,{'synthetic_editable_source':True})
    export=root/'export.json';save(export,{'passed':True,'scope':'independent_editable_export_preflight',
        'source_run_directory':str(builder/'run0'),'project_directory':str(project),'files_sha256':{str(source):new.f.sha(source)}})
    declaration=root/'variant.json';save(declaration,{})
    manifest={'schema':new.SCHEMA,'software_freeze_path':str(root/'unused-software'),
        'contract_path':str(root/'main-contract'),'static_review_path':str(root/'main-review'),'freeze_path':str(root/'main-freeze'),
        'positive_runs':[str(builder/f'run{i}') for i in range(3)],
        'controls':{name:str(builder/('run'+str(names.index(name)))) for name in ('no_trigger','broken_rope','locked_door')},
        'variant':{'run_directory':str(builder/'run6'),'contract_path':str(root/'variant-contract'),
            'static_review_path':str(root/'variant-review'),'freeze_path':str(root/'variant-freeze'),'declaration_path':str(declaration)},
        'replay':{'run_directory':str(replay_root/'run7'),'export_preflight_path':str(export)},
        'attempt_ledger_path':str(ledger_path),'formal_runs_roots':[str(builder),str(replay_root)],
        'native_cameras':{'fixed':'fixed','tracking':'moving'},'native_positive_index':0,
        'clock_directory':str(root/'output'),'provided_clock_path':str(root/'unused-clock'),
        'retained_examinations':records,'bounded_entry_certificates':{name:{} for name in ('positive_1','positive_2','positive_3','variant','replay')},
        'aggregator_freeze_path':str(root/'unused-freeze'),'aggregator_freeze_sha256':'f'*64}
    for name in ('main-contract','variant-contract'):save(root/name,{'synthetic_contract':True})
    return manifest,rows


class RetainedWorkflowTests(unittest.TestCase):
    def run_fixture(self,root,mutate=None,gate_failure=None):
        manifest,rows=workflow_fixture(root)
        if mutate:mutate(manifest,rows)
        seen=[]
        def load(directory,*args,**kwargs):
            seen.append((str(directory),kwargs));return copy.deepcopy(rows[str(directory)])
        with ExitStack() as stack:
            for target,name,replacement in ((new,'assert_dependencies',lambda:None),
                (new,'verify_generic_freeze',lambda *a:None),(new.f,'assert_software_freeze',lambda *a:{'passed':True}),
                (new,'verify_freeze',lambda *a:True),(new.retained,'load_retained',load),
                (new,'compare_variant',lambda *a:{'passed':gate_failure!='variant'}),
                (new,'compare_variant_contract',lambda *a:{'passed':gate_failure!='external_variant'}),
                (new,'verify_native',lambda *a,**k:{'passed':gate_failure!='native'}),
                (new.f,'export_motion_csv',lambda *a:{'csv_sha256':'0'*64}),
                (new,'physical_entry_clock',lambda *a,**k:{'passed':gate_failure!='physical_clock'})):
                stack.enter_context(patch.object(target,name,new=replacement))
            result=new.verify_suite(manifest)
        return result,seen

    def test_all_eight_original_reports_and_all_five_clocks_with_unchanged_old_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,seen=self.run_fixture(Path(tmp))
            self.assertTrue(result['passed']);self.assertFalse(result['original_suite7_rerun'])
            self.assertEqual(result['execution_mode'],'retained_original_report_aggregation')
            self.assertEqual(len(seen),8);self.assertEqual(len(result['physical_entry_clocks']),5)
            self.assertEqual([item[1]['mode'] for item in seen],['positive']*3+['no_trigger','broken_rope','locked_door']+['positive']*2)
            for _,kwargs in seen[3:6]:
                self.assertIsNotNone(kwargs['reference_record']);self.assertIsNotNone(kwargs['reference_run'])
            self.assertTrue(all(value for value in result['checks'].values()))

    def test_every_critical_old_or_additional_gate_still_blocks_acceptance(self):
        for gate in ('variant','external_variant','native','physical_clock','runtime','physical','memoized','export','chronology'):
            with self.subTest(gate=gate),tempfile.TemporaryDirectory() as tmp:
                def mutate(manifest,rows):
                    if gate=='runtime':rows[manifest['positive_runs'][1]][0]['suite_metadata']['lock']['seed']='changed'
                    if gate=='physical':rows[manifest['positive_runs'][1]][0]['passed']=False
                    if gate=='memoized':rows[manifest['positive_runs'][1]][1]['passed']=False
                    if gate=='export':
                        path=Path(manifest['replay']['export_preflight_path']);value=json.loads(path.read_text());value['passed']=False;save(path,value)
                    if gate=='chronology':
                        path=Path(manifest['positive_runs'][1])/'run-lock.json';value=json.loads(path.read_text());value['created_at_utc']='2026-11-01T00:00:00Z';save(path,value)
                    # Update only the MOCK custody proof after synthetic mutation;
                    # real helper rejects edits without its independent receipt.
                    for key,(report,proof) in rows.items():
                        proof['original_full_report_sha256']=hashlib.sha256((json.dumps(report,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
                try:
                    result,_=self.run_fixture(Path(tmp),mutate,gate)
                except ValueError:
                    self.assertEqual(gate,'chronology')
                else:
                    self.assertFalse(result['passed'])


if __name__=='__main__':unittest.main()
